"""
ETH/USDC Aggressive Momentum Backtest (YTD-oriented)

Diseñada para buscar retorno alto en ETH con enfoque agresivo:
- Trend-following + breakout
- Pullback buys en tendencia alcista
- Stop loss corto + trailing stop corto
- Re-entries frecuentes

Nota:
- No garantiza 50% anual. Es una base agresiva para iterar.
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


class ETHAggressiveMomentumYTDStrategy(Strategy):
    parameters = {
        # Asset / data
        "symbol": "ETH/USDC",
        "quote_symbol": "USDC",
        "sleeptime": "1H",
        "bar_unit": "minute",         # AlpacaBacktesting supports minute/day
        "aggregation_minutes": 60,    # synthetic hourly bars
        "history_bars": 500,          # ~20 days hourly

        # Trend regime
        "ma_fast": 12,
        "ma_mid": 36,
        "ma_slow": 120,
        "ma_slope_lookback": 24,
        "min_slow_slope": 0.0,

        # Volatility / noise filters
        "atr_period": 14,
        "rsi_period": 14,
        "max_atr_pct_for_breakout": 0.055,  # avoid extreme chop
        "min_atr_pct_for_breakout": 0.008,  # avoid dead market

        # Breakout entry
        "breakout_lookback": 24,
        "breakout_buffer": 0.0015,        # 0.15% above recent high
        "breakout_rsi_min": 53,
        "breakout_momentum_lookback": 4,
        "breakout_momentum_min": 0.0075,  # +0.75%

        # Pullback entry in uptrend
        "pullback_local_high_lookback": 36,
        "pullback_min_drawdown": 0.02,
        "pullback_max_drawdown": 0.08,
        "pullback_to_fast_ma_tolerance": 0.012,  # within 1.2% of MA fast
        "pullback_rsi_min": 42,
        "pullback_rsi_max": 58,
        "pullback_reversal_momentum_min": 0.003,  # +0.3% short-term bounce

        # Risk management (aggressive)
        "position_size": 1.30,              # 130% notional (aggressive / margin-like)
        "stop_loss": 0.020,                 # 2.0%
        "trailing_activation_profit": 0.008,  # +0.8%
        "trailing_stop": 0.018,             # 1.8%
        "take_profit": 0.0,                 # disable hard TP by default
        "hard_take_profit": 0.10,           # emergency cash-out at +10%
        "max_hold_bars": 60,                # ~2.5 days
        "cooldown_bars": 1,                 # quick re-entry

        # Exit quality
        "rsi_exit_overbought": 72,
        "trend_loss_exit_confirm": True,
    }

    def initialize(self):
        self.sleeptime = self.parameters.get("sleeptime", "1H")
        self.symbol = self.parameters.get("symbol", "ETH/USDC")
        self.quote_symbol = self.parameters.get("quote_symbol", "USDC")
        self.bar_unit = self.parameters.get("bar_unit", "minute")
        self.market_hours = None  # crypto 24/7

        self.base_asset = Asset(symbol="ETH", asset_type="crypto")
        quote_type = "forex" if self.quote_symbol.upper() == "USD" else "crypto"
        self.quote_asset = Asset(symbol=self.quote_symbol, asset_type=quote_type)

        self.iteration_index = 0
        self.last_exit_bar_index = -10_000
        self.total_entries = 0

        # Position state
        self.entry_price: Optional[float] = None
        self.entry_bar_index: Optional[int] = None
        self.peak_price_since_entry: Optional[float] = None
        self.entry_mode: Optional[str] = None

        self.log_message("=" * 78)
        self.log_message("ETH AGGRESSIVE MOMENTUM YTD BACKTEST (ETH/USDC)")
        self.log_message(
            f"Risk: pos={self.parameters['position_size']:.0%} SL={self.parameters['stop_loss']:.1%} "
            f"trail_act={self.parameters['trailing_activation_profit']:.1%} trail={self.parameters['trailing_stop']:.1%}"
        )
        self.log_message("=" * 78)

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

    def _calc_atr_pct(self, highs, lows, closes, period: int) -> float:
        if len(closes) < period + 2:
            return 0.0
        trs = []
        for i in range(-period, 0):
            h = float(highs[i])
            l = float(lows[i])
            pc = float(closes[i - 1])
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        atr = float(np.mean(trs))
        return atr / float(closes[-1]) if float(closes[-1]) > 0 else 0.0

    def _fetch_bars(self):
        requested_unit = self.bar_unit
        requested_bars = int(self.parameters["history_bars"])
        analysis_unit = self.bar_unit
        if self.bar_unit == "minute":
            agg_n = int(self.parameters.get("aggregation_minutes", 60))
            requested_bars *= agg_n
            requested_unit = "minute"
            analysis_unit = "hour"

        bars = self.get_historical_prices(self.base_asset, requested_bars, requested_unit, quote=self.quote_asset)
        if not bars or not hasattr(bars, "df") or bars.df is None or bars.df.empty:
            return None, None, None, None, analysis_unit

        df = bars.df.copy()
        closes = df["close"].astype(float).to_numpy()
        highs = df["high"].astype(float).to_numpy() if "high" in df.columns else closes
        lows = df["low"].astype(float).to_numpy() if "low" in df.columns else closes

        if self.bar_unit == "minute":
            agg_n = int(self.parameters.get("aggregation_minutes", 60))
            n = len(closes) // agg_n
            if n <= 0:
                return None, None, None, None, analysis_unit
            closes = closes[-n * agg_n :].reshape(n, agg_n)[:, -1]
            highs = highs[-n * agg_n :].reshape(n, agg_n).max(axis=1)
            lows = lows[-n * agg_n :].reshape(n, agg_n).min(axis=1)
        return closes, highs, lows, df, analysis_unit

    def on_trading_iteration(self):
        self.iteration_index += 1

        closes, highs, lows, _df, analysis_unit = self._fetch_bars()
        if closes is None:
            self.log_message("No bars available")
            return

        needed = max(
            int(self.parameters["ma_slow"]) + int(self.parameters["ma_slope_lookback"]) + 2,
            int(self.parameters["breakout_lookback"]) + 2,
            int(self.parameters["pullback_local_high_lookback"]) + 2,
            int(self.parameters["atr_period"]) + 2,
            int(self.parameters["breakout_momentum_lookback"]) + 2,
            int(self.parameters["rsi_period"]) + 2,
        )
        if len(closes) < needed:
            self.log_message(f"Insufficient bars {len(closes)}/{needed}")
            return

        price = float(closes[-1])
        prev_price = float(closes[-2])

        # Indicators
        ma_fast_n = int(self.parameters["ma_fast"])
        ma_mid_n = int(self.parameters["ma_mid"])
        ma_slow_n = int(self.parameters["ma_slow"])
        slope_lb = int(self.parameters["ma_slope_lookback"])
        ma_fast = float(np.mean(closes[-ma_fast_n:]))
        ma_mid = float(np.mean(closes[-ma_mid_n:]))
        ma_slow = float(np.mean(closes[-ma_slow_n:]))
        ma_slow_prev = float(np.mean(closes[-(ma_slow_n + slope_lb):-slope_lb]))
        ma_slow_slope = (ma_slow / ma_slow_prev - 1.0) if ma_slow_prev > 0 else 0.0

        uptrend = (
            price > ma_mid
            and ma_fast > ma_mid
            and ma_mid > ma_slow
            and ma_slow_slope >= float(self.parameters["min_slow_slope"])
        )

        rsi = self._calc_rsi(closes, int(self.parameters["rsi_period"]))
        atr_pct = self._calc_atr_pct(highs, lows, closes, int(self.parameters["atr_period"]))

        breakout_lb = int(self.parameters["breakout_lookback"])
        recent_high = float(np.max(highs[-(breakout_lb + 1):-1]))
        breakout_mom_lb = int(self.parameters["breakout_momentum_lookback"])
        breakout_mom_base = float(closes[-(breakout_mom_lb + 1)])
        breakout_mom = (price / breakout_mom_base - 1.0) if breakout_mom_base > 0 else 0.0

        pb_lb = int(self.parameters["pullback_local_high_lookback"])
        local_high = float(np.max(highs[-pb_lb:]))
        pullback_dd = (local_high - price) / local_high if local_high > 0 else 0.0
        dist_to_fast_ma = abs(price / ma_fast - 1.0) if ma_fast > 0 else 0.0
        short_reversal_mom = (price / float(closes[-4]) - 1.0) if len(closes) >= 4 else 0.0

        self.log_message(
            f"[CHECK] {self.symbol} unit={analysis_unit} price={price:.2f} uptrend={uptrend} "
            f"maF={ma_fast:.2f} maM={ma_mid:.2f} maS={ma_slow:.2f} slope={ma_slow_slope:.2%} "
            f"rsi={rsi:.1f} atr%={atr_pct:.2%} breakout_mom={breakout_mom:.2%} pullback_dd={pullback_dd:.2%}"
        )

        position = self.get_position(self.base_asset)
        has_position = bool(position and getattr(position, "quantity", 0))
        qty = float(getattr(position, "quantity", 0) or 0.0)

        # Manage open position
        if has_position and self.entry_price:
            pnl_pct = (price - self.entry_price) / self.entry_price
            self.peak_price_since_entry = max(float(self.peak_price_since_entry or price), price)

            if pnl_pct <= -float(self.parameters["stop_loss"]):
                self._exit(qty, price, f"Stop {pnl_pct:.2%}")
                return

            # Trailing after some profit
            if pnl_pct >= float(self.parameters["trailing_activation_profit"]) and self.peak_price_since_entry:
                trail_dd = (self.peak_price_since_entry - price) / self.peak_price_since_entry
                if trail_dd >= float(self.parameters["trailing_stop"]):
                    self._exit(qty, price, f"Trail {trail_dd:.2%} peak={self.peak_price_since_entry:.2f}")
                    return

            hard_tp = float(self.parameters["hard_take_profit"])
            if pnl_pct >= hard_tp:
                self._exit(qty, price, f"Hard TP {pnl_pct:.2%}")
                return

            # Momentum / trend loss exits
            hold_bars = self.iteration_index - int(self.entry_bar_index or self.iteration_index)
            if hold_bars >= int(self.parameters["max_hold_bars"]):
                self._exit(qty, price, f"Max hold {hold_bars}")
                return
            if price < ma_mid and prev_price > price and rsi >= float(self.parameters["rsi_exit_overbought"]):
                self._exit(qty, price, f"Momentum fade RSI={rsi:.1f}")
                return
            if bool(self.parameters["trend_loss_exit_confirm"]) and price < ma_fast and ma_fast < ma_mid:
                # Protective exit if trend degrades and no strong bounce
                if short_reversal_mom <= 0:
                    self._exit(qty, price, "Trend loss")
                    return
            return

        # Cooldown
        if (self.iteration_index - self.last_exit_bar_index) < int(self.parameters["cooldown_bars"]):
            return

        if not uptrend:
            return

        # Volatility gating
        if not (float(self.parameters["min_atr_pct_for_breakout"]) <= atr_pct <= float(self.parameters["max_atr_pct_for_breakout"])):
            return

        # Entry mode A: breakout continuation
        breakout_entry = (
            price >= recent_high * (1 + float(self.parameters["breakout_buffer"]))
            and rsi >= float(self.parameters["breakout_rsi_min"])
            and breakout_mom >= float(self.parameters["breakout_momentum_min"])
        )

        # Entry mode B: pullback buy in uptrend with rebound confirmation
        pullback_entry = (
            float(self.parameters["pullback_min_drawdown"]) <= pullback_dd <= float(self.parameters["pullback_max_drawdown"])
            and dist_to_fast_ma <= float(self.parameters["pullback_to_fast_ma_tolerance"])
            and float(self.parameters["pullback_rsi_min"]) <= rsi <= float(self.parameters["pullback_rsi_max"])
            and short_reversal_mom >= float(self.parameters["pullback_reversal_momentum_min"])
            and price > prev_price
        )

        mode = None
        if breakout_entry:
            mode = "breakout"
        elif pullback_entry:
            mode = "pullback"
        else:
            return

        allocation_value = float(self.portfolio_value or 0.0) * float(self.parameters["position_size"])
        quantity = allocation_value / price if price > 0 else 0.0
        if quantity <= 0:
            return

        order = self.create_order(self.base_asset, quantity, "buy", type="market", quote=self.quote_asset)
        self.submit_order(order)
        self.entry_price = price
        self.entry_bar_index = self.iteration_index
        self.peak_price_since_entry = price
        self.entry_mode = mode
        self.total_entries += 1
        self.log_message(
            f"[ENTRY-{mode.upper()}] BUY {self.symbol} qty={quantity:.6f} @ {price:.2f} "
            f"rsi={rsi:.1f} atr={atr_pct:.2%} breakout_mom={breakout_mom:.2%} pullback_dd={pullback_dd:.2%}"
        )

    def _exit(self, quantity: float, price: float, reason: str):
        if quantity <= 0:
            return
        order = self.create_order(self.base_asset, quantity, "sell", type="market", quote=self.quote_asset)
        self.submit_order(order)
        pnl_pct = (price - self.entry_price) / self.entry_price if self.entry_price else 0.0
        self.log_message(
            f"[EXIT-{(self.entry_mode or 'pos').upper()}] SELL {self.symbol} qty={quantity:.6f} @ {price:.2f} "
            f"| {reason} | pnl={pnl_pct:.2%}"
        )
        self.entry_price = None
        self.entry_bar_index = None
        self.peak_price_since_entry = None
        self.entry_mode = None
        self.last_exit_bar_index = self.iteration_index

    def on_abrupt_closing(self):
        self.log_message(f"Strategy closing. Entries executed: {self.total_entries}")


def run_backtest(source: str = "alpaca", start: Optional[dt.datetime] = None, end: Optional[dt.datetime] = None):
    load_dotenv()
    tzinfo = pytz.timezone("UTC")
    backtesting_start = start or tzinfo.localize(dt.datetime(2025, 2, 1))
    backtesting_end = end or tzinfo.localize(dt.datetime(2026, 2, 1))

    print("🧪 ETH/USDC Aggressive Momentum YTD Backtest")
    print("=" * 78)
    print(f"Source: {source}")
    print(f"Period: {backtesting_start} -> {backtesting_end}")

    if source == "alpaca":
        from lumibot.backtesting import AlpacaBacktesting
        from lumibot.credentials import ALPACA_TEST_CONFIG

        if not ALPACA_TEST_CONFIG:
            raise RuntimeError("ALPACA_TEST_CONFIG not found. Configure Alpaca paper keys in .env")

        results, strategy = ETHAggressiveMomentumYTDStrategy.run_backtest(
            datasource_class=AlpacaBacktesting,
            backtesting_start=backtesting_start,
            backtesting_end=backtesting_end,
            benchmark_asset=Asset("ETH", asset_type="crypto"),
            analyze_backtest=True,
            show_progress_bar=True,
            budget=100000,
            parameters={
                **ETHAggressiveMomentumYTDStrategy.parameters.copy(),
                # AlpacaBacktesting + Lumibot in this env fails valuing USDC quote in portfolio updates.
                # Use ETH/USD as proxy pair for backtest; strategy logic stays the same.
                "symbol": "ETH/USD",
                "quote_symbol": "USD",
            },
            timestep="minute",
            market="24/7",
            config=ALPACA_TEST_CONFIG,
            refresh_cache=False,
            warm_up_trading_days=0,
            auto_adjust=False,
        )
    else:
        from lumibot.backtesting import YahooDataBacktesting

        params = ETHAggressiveMomentumYTDStrategy.parameters.copy()
        params.update(
            {
                "symbol": "ETH-USD",
                "quote_symbol": "USD",
                "sleeptime": "1D",
                "bar_unit": "day",
                "history_bars": 300,
                "ma_fast": 10,
                "ma_mid": 20,
                "ma_slow": 50,
                "ma_slope_lookback": 10,
                "atr_period": 10,
                "breakout_lookback": 10,
                "breakout_momentum_lookback": 2,
                "pullback_local_high_lookback": 15,
                "rebound_momentum_lookback_bars": 2,
            }
        )
        results, strategy = ETHAggressiveMomentumYTDStrategy.run_backtest(
            datasource_class=YahooDataBacktesting,
            backtesting_start=backtesting_start,
            backtesting_end=backtesting_end,
            benchmark_asset="ETH-USD",
            analyze_backtest=True,
            show_progress_bar=True,
            budget=100000,
            parameters=params,
        )

    print("=" * 78)
    print("✅ Backtest finished")
    print(results)
    return results, strategy


def _parse_args():
    parser = argparse.ArgumentParser(description="Run ETH/USDC aggressive momentum YTD backtest")
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
