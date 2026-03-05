"""
ETH Aggressive Momentum Live

Live adaptation of the aggressive ETH momentum backtest.

Key differences vs backtest:
- Lower default position sizing.
- Uses a broker-friendly live pair by default (`ETH/USD`).
- Adds basic live guardrails (daily loss limit, cooldown after exits).
- Keeps local minute->hour aggregation to stay close to tested signal behavior.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np
from lumibot.entities import Asset
from lumibot.strategies import Strategy


class ETHAggressiveMomentumLive(Strategy):
    parameters = {
        # Asset / data
        "symbol": "ETH/USD",
        "quote_symbol": "USD",
        "sleeptime": "1M",          # poll every minute, aggregate locally
        "bar_unit": "minute",
        "aggregation_minutes": 60,  # synthetic hourly bars
        "history_bars": 500,        # hourly bars after aggregation

        # Trend regime
        "ma_fast": 12,
        "ma_mid": 36,
        "ma_slow": 120,
        "ma_slope_lookback": 24,
        "min_slow_slope": 0.0,

        # Volatility / noise filters
        "atr_period": 14,
        "rsi_period": 14,
        "max_atr_pct_for_breakout": 0.055,
        "min_atr_pct_for_breakout": 0.008,

        # Breakout entry
        "breakout_lookback": 24,
        "breakout_buffer": 0.0015,
        "breakout_rsi_min": 53,
        "breakout_momentum_lookback": 4,
        "breakout_momentum_min": 0.0075,

        # Pullback entry
        "pullback_local_high_lookback": 36,
        "pullback_min_drawdown": 0.02,
        "pullback_max_drawdown": 0.08,
        "pullback_to_fast_ma_tolerance": 0.012,
        "pullback_rsi_min": 42,
        "pullback_rsi_max": 58,
        "pullback_reversal_momentum_min": 0.003,

        # Risk management (live-safe defaults)
        "position_size": 0.25,          # start much lower than backtest
        "stop_loss": 0.020,
        "trailing_activation_profit": 0.008,
        "trailing_stop": 0.018,
        "hard_take_profit": 0.10,
        "max_hold_bars": 60,
        "cooldown_bars": 2,
        "rsi_exit_overbought": 72,
        "trend_loss_exit_confirm": True,

        # Live guardrails
        "max_daily_loss_pct": 0.03,     # stop opening new trades after -3% day
        "max_entries_per_day": 6,
    }

    def initialize(self):
        self.sleeptime = self.parameters.get("sleeptime", "1M")
        self.symbol = self.parameters.get("symbol", "ETH/USD")
        self.quote_symbol = self.parameters.get("quote_symbol", "USD")
        self.bar_unit = self.parameters.get("bar_unit", "minute")
        self.market_hours = None  # crypto 24/7

        if hasattr(self, "broker") and self.broker:
            self.broker.market = "24/7"

        base_symbol = self.symbol.split("/")[0]
        self.base_asset = Asset(symbol=base_symbol, asset_type="crypto")
        quote_type = "forex" if self.quote_symbol.upper() == "USD" else "crypto"
        self.quote_asset = Asset(symbol=self.quote_symbol, asset_type=quote_type)

        self.iteration_index = 0
        self.last_exit_bar_index = -10_000
        self.total_entries = 0

        self.entry_price: Optional[float] = None
        self.entry_bar_index: Optional[int] = None
        self.peak_price_since_entry: Optional[float] = None
        self.entry_mode: Optional[str] = None

        self.day_start_value: Optional[float] = None
        self.current_day = datetime.utcnow().date()
        self.entries_today = 0

        self.log_message("=" * 78)
        self.log_message("ETH AGGRESSIVE MOMENTUM LIVE")
        self.log_message(
            f"Pair={self.symbol} pos={self.parameters['position_size']:.0%} "
            f"SL={self.parameters['stop_loss']:.1%} trail_act={self.parameters['trailing_activation_profit']:.1%} "
            f"trail={self.parameters['trailing_stop']:.1%}"
        )
        self.log_message("=" * 78)

    def is_market_open(self):
        return True

    def should_continue_trading(self):
        return True

    def _roll_day_if_needed(self):
        today = datetime.utcnow().date()
        if today != self.current_day:
            self.current_day = today
            self.day_start_value = float(self.portfolio_value or 0.0)
            self.entries_today = 0
            self.log_message(f"[DAY] Reset counters for {today.isoformat()}")
        elif self.day_start_value is None:
            self.day_start_value = float(self.portfolio_value or 0.0)

    def _daily_loss_exceeded(self) -> bool:
        if not self.day_start_value:
            return False
        current_value = float(self.portfolio_value or 0.0)
        if current_value <= 0:
            return False
        day_pnl_pct = current_value / self.day_start_value - 1.0
        limit = -float(self.parameters["max_daily_loss_pct"])
        if day_pnl_pct <= limit:
            self.log_message(
                f"[RISK] Daily loss limit reached: {day_pnl_pct:.2%} <= {limit:.2%}. New entries disabled."
            )
            return True
        return False

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
        requested_bars = int(self.parameters["history_bars"])
        requested_unit = self.bar_unit
        analysis_unit = self.bar_unit

        if self.bar_unit == "minute":
            agg_n = int(self.parameters.get("aggregation_minutes", 60))
            requested_bars *= agg_n
            analysis_unit = "hour"

        bars = self.get_historical_prices(
            self.base_asset,
            requested_bars,
            requested_unit,
            quote=self.quote_asset,
        )
        if not bars or not hasattr(bars, "df") or bars.df is None or bars.df.empty:
            return None, None, None, analysis_unit

        df = bars.df.copy()
        closes = df["close"].astype(float).to_numpy()
        highs = df["high"].astype(float).to_numpy() if "high" in df.columns else closes
        lows = df["low"].astype(float).to_numpy() if "low" in df.columns else closes

        if self.bar_unit == "minute":
            agg_n = int(self.parameters.get("aggregation_minutes", 60))
            n = len(closes) // agg_n
            if n <= 0:
                return None, None, None, analysis_unit
            closes = closes[-n * agg_n :].reshape(n, agg_n)[:, -1]
            highs = highs[-n * agg_n :].reshape(n, agg_n).max(axis=1)
            lows = lows[-n * agg_n :].reshape(n, agg_n).min(axis=1)

        return closes, highs, lows, analysis_unit

    def on_trading_iteration(self):
        self.iteration_index += 1
        self._roll_day_if_needed()

        closes, highs, lows, analysis_unit = self._fetch_bars()
        if closes is None:
            self.log_message("[DATA] No bars available")
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
            self.log_message(f"[DATA] Insufficient bars {len(closes)}/{needed}")
            return

        price = float(closes[-1])
        prev_price = float(closes[-2])

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
            f"rsi={rsi:.1f} atr={atr_pct:.2%} breakout_mom={breakout_mom:.2%} pullback_dd={pullback_dd:.2%}"
        )

        position = self.get_position(self.base_asset)
        has_position = bool(position and getattr(position, "quantity", 0))
        qty = float(getattr(position, "quantity", 0) or 0.0)

        if has_position and self.entry_price:
            pnl_pct = (price - self.entry_price) / self.entry_price
            self.peak_price_since_entry = max(float(self.peak_price_since_entry or price), price)

            if pnl_pct <= -float(self.parameters["stop_loss"]):
                self._exit(qty, price, f"Stop {pnl_pct:.2%}")
                return

            if pnl_pct >= float(self.parameters["trailing_activation_profit"]) and self.peak_price_since_entry:
                trail_dd = (self.peak_price_since_entry - price) / self.peak_price_since_entry
                if trail_dd >= float(self.parameters["trailing_stop"]):
                    self._exit(qty, price, f"Trail {trail_dd:.2%} peak={self.peak_price_since_entry:.2f}")
                    return

            if pnl_pct >= float(self.parameters["hard_take_profit"]):
                self._exit(qty, price, f"Hard TP {pnl_pct:.2%}")
                return

            hold_bars = self.iteration_index - int(self.entry_bar_index or self.iteration_index)
            if hold_bars >= int(self.parameters["max_hold_bars"]):
                self._exit(qty, price, f"Max hold {hold_bars}")
                return
            if price < ma_mid and prev_price > price and rsi >= float(self.parameters["rsi_exit_overbought"]):
                self._exit(qty, price, f"Momentum fade RSI={rsi:.1f}")
                return
            if bool(self.parameters["trend_loss_exit_confirm"]) and price < ma_fast and ma_fast < ma_mid:
                if short_reversal_mom <= 0:
                    self._exit(qty, price, "Trend loss")
                    return
            return

        if (self.iteration_index - self.last_exit_bar_index) < int(self.parameters["cooldown_bars"]):
            return
        if self.entries_today >= int(self.parameters["max_entries_per_day"]):
            self.log_message(f"[RISK] Max entries reached today: {self.entries_today}")
            return
        if self._daily_loss_exceeded():
            return
        if not uptrend:
            return
        if not (float(self.parameters["min_atr_pct_for_breakout"]) <= atr_pct <= float(self.parameters["max_atr_pct_for_breakout"])):
            return

        breakout_entry = (
            price >= recent_high * (1 + float(self.parameters["breakout_buffer"]))
            and rsi >= float(self.parameters["breakout_rsi_min"])
            and breakout_mom >= float(self.parameters["breakout_momentum_min"])
        )
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
        self.entries_today += 1
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
        self.log_message(
            f"Strategy closing. Entries executed={self.total_entries} entries_today={self.entries_today}"
        )
