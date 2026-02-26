"""
ETH Volatility Regime Backtest (ETH/USD)

Nueva iteración alineada al estilo descrito por el usuario:
- Comprar caídas fuertes de ETH, pero SOLO dentro de tendencia alcista
- Esperar confirmación de rebote (no comprar knife catch)
- Stop loss corto (~2%)
- Trailing stop corto (~2%) una vez que hay ganancia

Objetivo:
- Validar si el patrón de oscilación/caída + rebote confirmado tiene edge en ETH/USD
- Iterar hacia mejor retorno/riesgo

Nota:
- No se puede garantizar 90% anual ex-ante. Este script deja una base clara para seguir iterando.
"""

from __future__ import annotations

import argparse
import datetime as dt
from typing import Optional

import numpy as np
import pytz
from dotenv import load_dotenv
from lumibot.entities import Asset
from lumibot.strategies.strategy import Strategy


class ETHVolatilityRegimeStrategy(Strategy):
    """
    Estrategia long-only de buy-the-dip con filtro de tendencia + confirmación de rebote.

    Flujo:
    1) Detecta "dip fuerte" en tendencia alcista
    2) Arma ventana de observación
    3) Entra cuando rebote se confirma (momentum + RSI + reclaim)
    4) Sale con SL 2%, trailing 2%, o pérdida de momentum
    """

    parameters = {
        # Símbolo / datos
        "symbol": "ETH/USD",
        "sleeptime": "1H",
        "bar_unit": "minute",           # AlpacaBacktesting acepta minute/day
        "aggregation_minutes": 60,      # agregamos minute -> hour para análisis
        "history_bars": 360,            # 360 horas (~15 días)

        # Filtro de tendencia (higher timeframe simple)
        "trend_fast_bars": 24,          # ~1 día
        "trend_mid_bars": 72,           # ~3 días
        "trend_slow_bars": 168,         # ~7 días
        "trend_slope_lookback": 24,     # pendiente del MA lento
        "min_trend_slope": 0.0,         # slope >= 0

        # Patrón de oscilación / régimen
        "range_window_bars": 12,        # ~12h
        "low_regime_max_range": 0.025,  # <= 2.5%
        "high_regime_min_range": 0.040, # >= 4.0%

        # Detección de dip / soporte
        "support_lookback_bars": 48,     # ~2 días
        "support_touch_tolerance": 0.008, # ±0.8%
        "min_support_touches": 1,
        "breakdown_buffer": 0.004,       # 0.4% bajo soporte
        "dip_min_drawdown_from_local_high": 0.03,  # caída >=3% desde máximo local reciente
        "dip_min_below_fast_ma": 0.015,  # precio >=1.5% debajo de MA rápida para considerar dip

        # RSI / momentum para dip y confirmación
        "rsi_period": 14,
        "rsi_dip": 42,                   # detectar sobreventa suave
        "rsi_rebound_confirm": 45,       # confirmación de rebote
        "rsi_exit": 60,                  # salida por fatiga
        "rebound_confirm_window_bars": 18,  # tiempo para confirmar rebote tras armar señal
        "reclaim_buffer": 0.004,         # recuperar soporte +0.4%
        "rebound_momentum_lookback_bars": 3,
        "min_rebound_momentum": 0.004,   # +0.4%

        # Gestión de riesgo (alineado al estilo del usuario)
        "position_size": 0.45,           # 45% del portfolio por trade
        "stop_loss": 0.02,               # 2%
        "trailing_activation_profit": 0.01,  # activa trailing a +1%
        "trailing_stop": 0.02,           # trailing 2%
        "take_profit": 0.0,              # 0 = disabled; se prioriza trailing
        "cooldown_bars": 2,
        "max_hold_bars": 72,             # ~3 días
    }

    def initialize(self):
        self.sleeptime = self.parameters.get("sleeptime", "1H")
        self.symbol = self.parameters.get("symbol", "ETH/USD")
        self.bar_unit = self.parameters.get("bar_unit", "minute")
        self.market_hours = None  # crypto 24/7

        self.base_asset = Asset(symbol="ETH", asset_type="crypto")
        self.usd_quote = Asset(symbol="USD", asset_type="forex")

        self.iteration_index = 0
        self.last_exit_bar_index = -10_000
        self.total_trades = 0

        # Posición
        self.entry_price: Optional[float] = None
        self.entry_time = None
        self.entry_support: Optional[float] = None
        self.entry_bar_index: Optional[int] = None
        self.peak_price_since_entry: Optional[float] = None

        # Estado de señal armada (dip detectado, esperando confirmación)
        self.armed_until_bar: Optional[int] = None
        self.armed_support: Optional[float] = None
        self.armed_local_high: Optional[float] = None
        self.armed_reason: Optional[str] = None

        self.log_message("=" * 74)
        self.log_message("ETH DIP BUY (UPTREND + REBOUND CONFIRM) - BACKTEST")
        self.log_message(
            f"Symbol={self.symbol} | Sleeptime={self.sleeptime} | "
            f"bar_unit={self.bar_unit} agg={self.parameters.get('aggregation_minutes', 60)}m"
        )
        self.log_message(
            f"Risk: pos={self.parameters['position_size']:.0%}, SL={self.parameters['stop_loss']:.1%}, "
            f"trail_act={self.parameters['trailing_activation_profit']:.1%}, trail={self.parameters['trailing_stop']:.1%}"
        )
        self.log_message("=" * 74)

    def _reset_arm(self):
        self.armed_until_bar = None
        self.armed_support = None
        self.armed_local_high = None
        self.armed_reason = None

    def _calc_rsi(self, prices, period: int) -> float:
        if len(prices) < period + 1:
            return 50.0
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100 - (100 / (1 + rs)))

    def _window_range_pct(self, highs, lows) -> float:
        low = float(np.min(lows))
        high = float(np.max(highs))
        if low <= 0:
            return 0.0
        return (high - low) / low

    def _count_support_touches(self, lows, support_price: float, tolerance: float) -> int:
        if support_price <= 0:
            return 0
        touches = 0
        for low in lows:
            if abs((float(low) / support_price) - 1.0) <= tolerance:
                touches += 1
        return touches

    def _fetch_analysis_bars(self):
        trade_asset = self.base_asset if self.symbol in {"ETH", "ETH/USD", "ETH-USD"} else self.symbol
        quote_asset = self.usd_quote if self.symbol in {"ETH", "ETH/USD", "ETH-USD"} else None

        requested_unit = self.bar_unit
        requested_bars = int(self.parameters["history_bars"])
        analysis_unit = self.bar_unit

        if self.bar_unit == "minute":
            agg_n = int(self.parameters.get("aggregation_minutes", 60))
            requested_bars *= agg_n
            requested_unit = "minute"
            analysis_unit = "hour"

        bars = self.get_historical_prices(trade_asset, requested_bars, requested_unit, quote=quote_asset)
        if not bars or not hasattr(bars, "df") or bars.df is None or bars.df.empty:
            return None, None, None, None, analysis_unit, trade_asset, quote_asset

        df = bars.df.copy()
        closes = df["close"].astype(float).to_numpy()
        highs = df["high"].astype(float).to_numpy() if "high" in df.columns else closes
        lows = df["low"].astype(float).to_numpy() if "low" in df.columns else closes

        if self.bar_unit == "minute":
            agg_n = int(self.parameters.get("aggregation_minutes", 60))
            full_chunks = len(closes) // agg_n
            if full_chunks <= 0:
                return None, None, None, None, analysis_unit, trade_asset, quote_asset
            closes = closes[-full_chunks * agg_n :].reshape(full_chunks, agg_n)[:, -1]
            highs = highs[-full_chunks * agg_n :].reshape(full_chunks, agg_n).max(axis=1)
            lows = lows[-full_chunks * agg_n :].reshape(full_chunks, agg_n).min(axis=1)

        return closes, highs, lows, df, analysis_unit, trade_asset, quote_asset

    def on_trading_iteration(self):
        self.iteration_index += 1

        closes, highs, lows, _df, analysis_unit, trade_asset, quote_asset = self._fetch_analysis_bars()
        if closes is None or highs is None or lows is None:
            self.log_message("No historical bars available yet")
            return

        needed = max(
            int(self.parameters["trend_slow_bars"]) + int(self.parameters["trend_slope_lookback"]) + 2,
            int(self.parameters["support_lookback_bars"]),
            int(self.parameters["range_window_bars"]) * 2,
            int(self.parameters["rsi_period"]) + 2,
            int(self.parameters["rebound_momentum_lookback_bars"]) + 2,
        )
        if len(closes) < needed:
            self.log_message(f"Insufficient data after aggregation: {len(closes)}/{needed}")
            return

        current_price = float(closes[-1])
        prev_close = float(closes[-2])

        # Trend filter
        tf = int(self.parameters["trend_fast_bars"])
        tm = int(self.parameters["trend_mid_bars"])
        ts = int(self.parameters["trend_slow_bars"])
        slope_lb = int(self.parameters["trend_slope_lookback"])
        ma_fast = float(np.mean(closes[-tf:]))
        ma_mid = float(np.mean(closes[-tm:]))
        ma_slow = float(np.mean(closes[-ts:]))
        ma_slow_prev = float(np.mean(closes[-(ts + slope_lb):-slope_lb])) if len(closes) >= ts + slope_lb else ma_slow
        ma_slow_slope = (ma_slow / ma_slow_prev - 1.0) if ma_slow_prev > 0 else 0.0

        uptrend = (
            current_price > ma_mid
            and ma_fast > ma_mid
            and ma_mid > ma_slow
            and ma_slow_slope >= float(self.parameters["min_trend_slope"])
        )

        # Regime / support context
        rw = int(self.parameters["range_window_bars"])
        sw = int(self.parameters["support_lookback_bars"])
        current_range = self._window_range_pct(highs[-rw:], lows[-rw:])
        previous_range = self._window_range_pct(highs[-2 * rw:-rw], lows[-2 * rw:-rw])
        support_zone = float(np.min(lows[-sw:]))
        support_touches = self._count_support_touches(
            lows[-sw:], support_zone, float(self.parameters["support_touch_tolerance"])
        )
        local_high = float(np.max(highs[-sw:]))
        drawdown_from_local_high = (local_high - current_price) / local_high if local_high > 0 else 0.0
        below_fast_ma = (ma_fast - current_price) / ma_fast if ma_fast > 0 else 0.0
        rsi = self._calc_rsi(closes, int(self.parameters["rsi_period"]))

        # Rebound confirmation features
        mom_lb = int(self.parameters["rebound_momentum_lookback_bars"])
        mom_base = float(closes[-(mom_lb + 1)])
        recent_momentum = (current_price / mom_base - 1.0) if mom_base > 0 else 0.0
        reclaim_from_support = (current_price / support_zone - 1.0) if support_zone > 0 else 0.0
        support_intact = current_price >= support_zone * (1 - float(self.parameters["breakdown_buffer"]))
        breakdown = current_price < support_zone * (1 - float(self.parameters["breakdown_buffer"]))

        range_expansion = (
            previous_range <= float(self.parameters["low_regime_max_range"])
            and current_range >= float(self.parameters["high_regime_min_range"])
        )

        position = self.get_position(trade_asset)
        has_position = bool(position and getattr(position, "quantity", 0))
        qty = float(getattr(position, "quantity", 0) or 0.0)

        self.log_message(
            f"[CHECK] {self.symbol} unit={analysis_unit} price={current_price:.2f} "
            f"uptrend={uptrend} ma_fast={ma_fast:.2f} ma_mid={ma_mid:.2f} ma_slow={ma_slow:.2f} "
            f"slope={ma_slow_slope:.2%} rsi={rsi:.1f} dd={drawdown_from_local_high:.2%} "
            f"below_fast={below_fast_ma:.2%} range_prev={previous_range:.2%} range_now={current_range:.2%} "
            f"support={support_zone:.2f} touches={support_touches} mom={recent_momentum:.2%} reclaim={reclaim_from_support:.2%}"
        )

        # Arm dip signal only in uptrend
        dip_signal = (
            uptrend
            and support_touches >= int(self.parameters["min_support_touches"])
            and drawdown_from_local_high >= float(self.parameters["dip_min_drawdown_from_local_high"])
            and below_fast_ma >= float(self.parameters["dip_min_below_fast_ma"])
            and rsi <= float(self.parameters["rsi_dip"])
            and (range_expansion or current_range >= float(self.parameters["high_regime_min_range"]))
        )
        if dip_signal:
            self.armed_until_bar = self.iteration_index + int(self.parameters["rebound_confirm_window_bars"])
            self.armed_support = support_zone
            self.armed_local_high = local_high
            self.armed_reason = (
                f"dip dd={drawdown_from_local_high:.2%}, below_fast={below_fast_ma:.2%}, "
                f"rsi={rsi:.1f}, range={current_range:.2%}"
            )
            self.log_message(
                f"[ARM] Dip detected -> waiting rebound confirm for {self.parameters['rebound_confirm_window_bars']} bars | "
                f"{self.armed_reason}"
            )

        if self.armed_until_bar is not None and self.iteration_index > self.armed_until_bar:
            self.log_message("[ARM] expired")
            self._reset_arm()

        armed_active = bool(self.armed_until_bar is not None and self.iteration_index <= self.armed_until_bar)

        # Position management
        if has_position and self.entry_price:
            pnl_pct = (current_price - self.entry_price) / self.entry_price
            self.peak_price_since_entry = max(float(self.peak_price_since_entry or current_price), current_price)

            # Hard exits
            if pnl_pct <= -float(self.parameters["stop_loss"]):
                self._close_position(qty, current_price, reason=f"Stop loss {pnl_pct:.2%}")
                return
            if breakdown and self.entry_support is not None and current_price < self.entry_support:
                self._close_position(qty, current_price, reason="Support failed")
                return

            # Trailing stop (activates after profit threshold)
            if pnl_pct >= float(self.parameters["trailing_activation_profit"]) and self.peak_price_since_entry:
                trail_drawdown = (self.peak_price_since_entry - current_price) / self.peak_price_since_entry
                if trail_drawdown >= float(self.parameters["trailing_stop"]):
                    self._close_position(
                        qty,
                        current_price,
                        reason=f"Trailing stop {trail_drawdown:.2%} (peak {self.peak_price_since_entry:.2f})",
                    )
                    return

            take_profit = float(self.parameters.get("take_profit", 0.0))
            if take_profit > 0 and pnl_pct >= take_profit:
                self._close_position(qty, current_price, reason=f"Take profit {pnl_pct:.2%}")
                return

            hold_bars = self.iteration_index - int(self.entry_bar_index or self.iteration_index)
            # Exit on momentum loss after some profit or if hold too long
            if hold_bars >= int(self.parameters["max_hold_bars"]):
                self._close_position(qty, current_price, reason=f"Max hold {hold_bars} bars")
                return
            if pnl_pct > 0 and current_price < ma_fast and rsi >= float(self.parameters["rsi_exit"]):
                self._close_position(qty, current_price, reason=f"Momentum fade (RSI {rsi:.1f})")
                return
            # Small profit quick-exit if rebound stalls
            if pnl_pct > 0 and recent_momentum < 0 and current_price < prev_close:
                self._close_position(qty, current_price, reason="Rebound stalled")
                return
            return

        # Cooldown after exit
        if (self.iteration_index - self.last_exit_bar_index) < int(self.parameters["cooldown_bars"]):
            return

        # Entry: only after dip was armed and rebound confirms
        armed_support = float(self.armed_support) if self.armed_support is not None else support_zone
        rebound_confirmed = (
            armed_active
            and uptrend
            and support_intact
            and current_price > ma_fast
            and current_price > prev_close
            and rsi >= float(self.parameters["rsi_rebound_confirm"])
            and recent_momentum >= float(self.parameters["min_rebound_momentum"])
            and current_price >= armed_support * (1 + float(self.parameters["reclaim_buffer"]))
        )
        if not rebound_confirmed:
            return

        allocation_value = float(self.portfolio_value or 0.0) * float(self.parameters["position_size"])
        quantity = allocation_value / current_price if current_price > 0 else 0.0
        if quantity <= 0:
            return

        order = self.create_order(trade_asset, quantity, "buy", type="market", quote=quote_asset)
        self.submit_order(order)
        self.entry_price = current_price
        self.entry_time = self.get_datetime()
        self.entry_support = armed_support
        self.entry_bar_index = self.iteration_index
        self.peak_price_since_entry = current_price
        self.total_trades += 1

        self.log_message(
            f"[ENTRY] BUY {self.symbol} qty={quantity:.6f} @ {current_price:.2f} | "
            f"armed_reason={self.armed_reason or 'n/a'} | rebound mom={recent_momentum:.2%} "
            f"rsi={rsi:.1f} reclaim={reclaim_from_support:.2%}"
        )
        self._reset_arm()

    def _close_position(self, quantity: float, current_price: float, reason: str):
        if quantity <= 0:
            return
        trade_asset = self.base_asset if self.symbol in {"ETH", "ETH/USD", "ETH-USD"} else self.symbol
        order = self.create_order(trade_asset, quantity, "sell", type="market", quote=self.usd_quote)
        self.submit_order(order)
        pnl_pct = (current_price - self.entry_price) / self.entry_price if self.entry_price else 0.0
        self.log_message(
            f"[EXIT] SELL {self.symbol} qty={quantity:.6f} @ {current_price:.2f} | {reason} | pnl={pnl_pct:.2%}"
        )

        self.entry_price = None
        self.entry_time = None
        self.entry_support = None
        self.entry_bar_index = None
        self.peak_price_since_entry = None
        self.last_exit_bar_index = self.iteration_index

    def on_abrupt_closing(self):
        self.log_message(f"Strategy closing. Trades executed: {self.total_trades}")


def run_backtest(source: str = "alpaca", start: Optional[dt.datetime] = None, end: Optional[dt.datetime] = None):
    """Run backtest using AlpacaBacktesting (preferred for crypto) or Yahoo fallback."""
    load_dotenv()

    tzinfo = pytz.timezone("UTC")
    backtesting_start = start or tzinfo.localize(dt.datetime(2025, 2, 1))
    backtesting_end = end or tzinfo.localize(dt.datetime(2026, 2, 1))

    print("🧪 ETH Volatility Regime Backtest (Dip Buy + Rebound Confirm)")
    print("=" * 74)
    print(f"Source: {source}")
    print(f"Period: {backtesting_start} -> {backtesting_end}")

    if source == "alpaca":
        from lumibot.backtesting import AlpacaBacktesting
        from lumibot.credentials import ALPACA_TEST_CONFIG

        if not ALPACA_TEST_CONFIG:
            raise RuntimeError("ALPACA_TEST_CONFIG not found. Configure Alpaca paper keys in .env")

        results, strategy = ETHVolatilityRegimeStrategy.run_backtest(
            datasource_class=AlpacaBacktesting,
            backtesting_start=backtesting_start,
            backtesting_end=backtesting_end,
            benchmark_asset=Asset("ETH", asset_type="crypto"),  # buy & hold ETH
            analyze_backtest=True,
            show_progress_bar=True,
            budget=100000,
            parameters={
                "symbol": "ETH/USD",
                "sleeptime": "1H",
                "bar_unit": "minute",
                "aggregation_minutes": 60,
                "history_bars": 360,

                # Trend filter
                "trend_fast_bars": 24,
                "trend_mid_bars": 72,
                "trend_slow_bars": 168,
                "trend_slope_lookback": 24,
                "min_trend_slope": 0.0,

                # Regime + support + dip
                "range_window_bars": 12,
                "low_regime_max_range": 0.025,
                "high_regime_min_range": 0.040,
                "support_lookback_bars": 48,
                "support_touch_tolerance": 0.008,
                "min_support_touches": 1,
                "breakdown_buffer": 0.004,
                "dip_min_drawdown_from_local_high": 0.03,
                "dip_min_below_fast_ma": 0.015,
                "rsi_period": 14,
                "rsi_dip": 42,

                # Rebound confirmation
                "rebound_confirm_window_bars": 18,
                "reclaim_buffer": 0.004,
                "rsi_rebound_confirm": 45,
                "rebound_momentum_lookback_bars": 3,
                "min_rebound_momentum": 0.004,

                # Risk mgmt (aligned to user style)
                "position_size": 0.45,
                "stop_loss": 0.02,
                "trailing_activation_profit": 0.01,
                "trailing_stop": 0.02,
                "take_profit": 0.0,
                "rsi_exit": 60,
                "cooldown_bars": 2,
                "max_hold_bars": 72,
            },
            # AlpacaBacktesting only supports "day" or "minute"
            timestep="minute",
            market="24/7",
            config=ALPACA_TEST_CONFIG,
            refresh_cache=False,
            warm_up_trading_days=0,
            auto_adjust=False,
        )
    else:
        from lumibot.backtesting import YahooDataBacktesting

        # Fallback diario (menos fiel para intraday/crypto, solo para validación gruesa)
        results, strategy = ETHVolatilityRegimeStrategy.run_backtest(
            datasource_class=YahooDataBacktesting,
            backtesting_start=backtesting_start,
            backtesting_end=backtesting_end,
            benchmark_asset="ETH-USD",
            analyze_backtest=True,
            show_progress_bar=True,
            budget=100000,
            parameters={
                "symbol": "ETH-USD",
                "sleeptime": "1D",
                "bar_unit": "day",
                "history_bars": 240,
                "trend_fast_bars": 10,
                "trend_mid_bars": 20,
                "trend_slow_bars": 50,
                "trend_slope_lookback": 10,
                "range_window_bars": 5,
                "low_regime_max_range": 0.03,
                "high_regime_min_range": 0.06,
                "support_lookback_bars": 20,
                "support_touch_tolerance": 0.015,
                "dip_min_drawdown_from_local_high": 0.05,
                "dip_min_below_fast_ma": 0.02,
                "rsi_dip": 40,
                "rebound_confirm_window_bars": 5,
                "reclaim_buffer": 0.01,
                "rsi_rebound_confirm": 48,
                "rebound_momentum_lookback_bars": 2,
                "min_rebound_momentum": 0.01,
                "position_size": 0.45,
                "stop_loss": 0.03,
                "trailing_activation_profit": 0.02,
                "trailing_stop": 0.03,
                "take_profit": 0.0,
                "rsi_exit": 60,
                "cooldown_bars": 1,
                "max_hold_bars": 20,
            },
        )

    print("=" * 74)
    print("✅ Backtest finished")
    print(results)
    return results, strategy


def _parse_args():
    parser = argparse.ArgumentParser(description="Run ETH volatility regime backtest")
    parser.add_argument("--source", choices=["alpaca", "yahoo"], default="alpaca")
    parser.add_argument("--start", help="Start date YYYY-MM-DD", default=None)
    parser.add_argument("--end", help="End date YYYY-MM-DD", default=None)
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    tz = pytz.timezone("UTC")
    start_dt = tz.localize(dt.datetime.fromisoformat(args.start)) if args.start else None
    end_dt = tz.localize(dt.datetime.fromisoformat(args.end)) if args.end else None
    run_backtest(source=args.source, start=start_dt, end=end_dt)
