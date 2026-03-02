"""
ETH post-drop oscillation backtest.

Design:
- Detect a sharp ETH selloff (shock).
- Wait for the market to stabilize into a flat, repeatedly tested range.
- Trade only while that oscillation regime is active.
- Exit and pause when the range breaks with force.

This is a state-machine strategy intended to avoid forcing trades during trends.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path
from typing import Optional

import numpy as np
import pytz
from dotenv import load_dotenv
from lumibot.entities import Asset
from lumibot.strategies.strategy import Strategy


def _load_env() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    for env_path in (repo_root / ".env", repo_root.parent / ".env"):
        if env_path.exists():
            load_dotenv(env_path, override=True)
            break
    else:
        load_dotenv(override=True)


def _build_alpaca_backtest_config() -> dict:
    oauth_token = os.getenv("ALPACA_OAUTH_TOKEN")
    test_api_key = os.getenv("ALPACA_TEST_API_KEY")
    test_api_secret = os.getenv("ALPACA_TEST_API_SECRET")
    api_key = os.getenv("ALPACA_API_KEY")
    api_secret = os.getenv("ALPACA_API_SECRET")

    if oauth_token:
        return {"OAUTH_TOKEN": oauth_token, "PAPER": True}
    if test_api_key and test_api_secret:
        return {"API_KEY": test_api_key, "API_SECRET": test_api_secret, "PAPER": True}
    if api_key and api_secret:
        return {"API_KEY": api_key, "API_SECRET": api_secret, "PAPER": True}

    raise RuntimeError(
        "No usable Alpaca config found. Set ALPACA_TEST_API_KEY/SECRET, "
        "ALPACA_API_KEY/ALPACA_API_SECRET, or ALPACA_OAUTH_TOKEN in .env"
    )


class ETHPostDropOscillationStrategy(Strategy):
    parameters = {
        # Asset / data
        "symbol": "ETH/USD",
        "quote_symbol": "USD",
        "sleeptime": "1H",
        "bar_unit": "minute",
        "aggregation_minutes": 60,
        "history_bars": 360,

        # Shock detection
        "macro_drop_lookback_bars": 120,       # ~5 days
        "shock_drawdown_threshold": 0.07,
        "shock_release_ratio": 0.55,
        "min_watch_bars": 6,
        "max_watch_bars": 24 * 21,             # ~3 weeks after a shock

        # Oscillation regime validation
        "range_lookback_bars": 30,             # ~30h rolling box
        "range_min_pct": 0.035,
        "range_max_pct": 0.18,
        "upper_touch_tolerance": 0.993,
        "lower_touch_tolerance": 1.007,
        "min_upper_touches": 3,
        "min_lower_touches": 3,
        "max_touch_imbalance": 4,
        "center_slope_lookback_bars": 12,
        "max_center_slope_abs": 0.018,
        "max_box_drift_ratio": 0.55,

        # Entry / exit locations inside the box
        "entry_range_position_max": 0.38,
        "exit_range_position_min": 0.58,

        # Entry confirmation
        "rsi_period": 8,
        "rsi_entry_max": 55,
        "reversal_low_tolerance": 0.995,

        # Breakout pause / cooldown
        "strong_move_threshold": 0.045,
        "breakout_pause_bars": 6,
        "cooldown_bars": 1,

        # Risk / exits
        "position_size": 1.60,
        "stop_loss": 0.018,
        "take_profit": 0.022,
        "hard_take_profit": 0.040,
        "breakdown_exit_buffer": 0.012,
        "failed_bounce_bars": 3,
        "failed_bounce_loss": 0.008,
    }

    def initialize(self):
        self.sleeptime = self.parameters.get("sleeptime", "1H")
        self.market_hours = None

        quote_symbol = self.parameters.get("quote_symbol", "USD")
        quote_type = "forex" if quote_symbol.upper() == "USD" else "crypto"
        base_symbol = self.parameters.get("symbol", "ETH/USD").split("/")[0]

        self.base_asset = Asset(symbol=base_symbol, asset_type="crypto")
        self.quote_asset = Asset(symbol=quote_symbol, asset_type=quote_type)

        self.iteration_index = 0
        self.last_exit_bar_index = -10_000
        self.pause_until_bar_index = -1
        self.last_shock_bar_index = -10_000
        self.prev_macro_drawdown = 0.0
        self.regime_state = "OFF"
        self.total_entries = 0

        self.entry_price: Optional[float] = None
        self.entry_bar_index: Optional[int] = None

        self.log_message("=" * 78)
        self.log_message("ETH POST-DROP OSCILLATION BACKTEST")
        self.log_message(
            f"shock>={self.parameters['shock_drawdown_threshold']:.0%} "
            f"range={self.parameters['range_min_pct']:.1%}-{self.parameters['range_max_pct']:.0%} "
            f"buy<={self.parameters['entry_range_position_max']:.0%} "
            f"sell>={self.parameters['exit_range_position_min']:.0%} "
            f"pos={self.parameters['position_size']:.0%}"
        )
        self.log_message("=" * 78)

    def _fetch_bars(self):
        requested_bars = int(self.parameters["history_bars"]) * int(self.parameters["aggregation_minutes"])
        bars = self.get_historical_prices(self.base_asset, requested_bars, "minute", quote=self.quote_asset)
        if not bars or not hasattr(bars, "df") or bars.df is None or bars.df.empty:
            return None, None, None

        df = bars.df.copy()
        closes = df["close"].astype(float).to_numpy()
        highs = df["high"].astype(float).to_numpy() if "high" in df.columns else closes
        lows = df["low"].astype(float).to_numpy() if "low" in df.columns else closes

        agg_n = int(self.parameters["aggregation_minutes"])
        n = len(closes) // agg_n
        if n <= 0:
            return None, None, None

        closes = closes[-n * agg_n :].reshape(n, agg_n)[:, -1]
        highs = highs[-n * agg_n :].reshape(n, agg_n).max(axis=1)
        lows = lows[-n * agg_n :].reshape(n, agg_n).min(axis=1)
        return closes, highs, lows

    def _calc_rsi(self, prices: np.ndarray, period: int) -> float:
        if len(prices) < period + 1:
            return 50.0
        deltas = np.diff(prices[-(period + 1):])
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = float(np.mean(gains)) if len(gains) else 0.0
        avg_loss = float(np.mean(losses)) if len(losses) else 0.0
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return float(100 - (100 / (1 + rs)))

    def _set_state(self, state: str):
        if state != self.regime_state:
            self.regime_state = state
            self.log_message(f"[STATE] -> {state}")

    def on_trading_iteration(self):
        self.iteration_index += 1

        closes, highs, lows = self._fetch_bars()
        if closes is None:
            self.log_message("[DATA] Missing bars")
            return

        macro_lb = int(self.parameters["macro_drop_lookback_bars"])
        range_lb = int(self.parameters["range_lookback_bars"])
        center_lb = int(self.parameters["center_slope_lookback_bars"])
        needed = max(macro_lb, range_lb + center_lb, int(self.parameters["rsi_period"]) + 4, 8)
        if len(closes) < needed:
            self.log_message(f"[DATA] Insufficient bars {len(closes)}/{needed}")
            return

        price = float(closes[-1])
        prev_price = float(closes[-2])
        prev2_price = float(closes[-3])
        prev3_price = float(closes[-4])
        bar_move = (price / prev_price - 1.0) if prev_price > 0 else 0.0

        macro_high = float(np.max(highs[-macro_lb:]))
        macro_drawdown = (macro_high - price) / macro_high if macro_high > 0 else 0.0
        shock_threshold = float(self.parameters["shock_drawdown_threshold"])
        shock_cross = macro_drawdown >= shock_threshold and self.prev_macro_drawdown < shock_threshold
        self.prev_macro_drawdown = macro_drawdown
        if shock_cross:
            self.last_shock_bar_index = self.iteration_index

        shock_age = self.iteration_index - self.last_shock_bar_index
        in_watch_window = int(self.parameters["min_watch_bars"]) <= shock_age <= int(self.parameters["max_watch_bars"])
        shock_released = macro_drawdown <= shock_threshold * float(self.parameters["shock_release_ratio"])

        window_high = float(np.max(highs[-range_lb:]))
        window_low = float(np.min(lows[-range_lb:]))
        range_width = max(window_high - window_low, 1e-9)
        range_pct = range_width / price if price > 0 else 0.0
        range_position = (price - window_low) / range_width
        upper_touches = int(np.sum(highs[-range_lb:] >= window_high * float(self.parameters["upper_touch_tolerance"])))
        lower_touches = int(np.sum(lows[-range_lb:] <= window_low * float(self.parameters["lower_touch_tolerance"])))
        touch_imbalance = abs(upper_touches - lower_touches)

        box_center = (window_high + window_low) / 2.0
        prev_window_high = float(np.max(highs[-(range_lb + center_lb):-center_lb]))
        prev_window_low = float(np.min(lows[-(range_lb + center_lb):-center_lb]))
        prev_box_center = (prev_window_high + prev_window_low) / 2.0
        center_slope = (box_center / prev_box_center - 1.0) if prev_box_center > 0 else 0.0
        box_drift = abs(price / float(closes[-(range_lb + 1)]) - 1.0) if len(closes) > range_lb else 0.0
        drift_ratio = (box_drift / range_pct) if range_pct > 0 else 0.0
        rsi = self._calc_rsi(closes, int(self.parameters["rsi_period"]))

        breakout_risk = abs(bar_move) >= float(self.parameters["strong_move_threshold"]) and (
            price >= window_high * 0.998 or price <= window_low * 1.002
        )
        if breakout_risk:
            self.pause_until_bar_index = max(
                self.pause_until_bar_index,
                self.iteration_index + int(self.parameters["breakout_pause_bars"]),
            )

        range_is_tradeable = float(self.parameters["range_min_pct"]) <= range_pct <= float(self.parameters["range_max_pct"])
        enough_touches = (
            upper_touches >= int(self.parameters["min_upper_touches"])
            and lower_touches >= int(self.parameters["min_lower_touches"])
        )
        balanced_touches = touch_imbalance <= int(self.parameters["max_touch_imbalance"])
        flat_box = abs(center_slope) <= float(self.parameters["max_center_slope_abs"])
        contained_drift = drift_ratio <= float(self.parameters["max_box_drift_ratio"])

        oscillation_ready = (
            in_watch_window
            and range_is_tradeable
            and enough_touches
            and balanced_touches
            and flat_box
            and contained_drift
            and not breakout_risk
        )

        position = self.get_position(self.base_asset)
        has_position = bool(position and getattr(position, "quantity", 0))
        qty = float(getattr(position, "quantity", 0) or 0.0)

        if self.iteration_index < self.pause_until_bar_index:
            self._set_state("BREAKOUT_PAUSE")
        elif oscillation_ready:
            self._set_state("OSCILLATION_ACTIVE")
        elif shock_cross or (not shock_released and shock_age <= int(self.parameters["max_watch_bars"])):
            self._set_state("POST_DROP_WATCH")
        else:
            self._set_state("OFF")

        self.log_message(
            f"[CHECK] state={self.regime_state} price={price:.2f} dd={macro_drawdown:.2%} "
            f"range={range_pct:.2%} pos={range_position:.2f} touches=({lower_touches}/{upper_touches}) "
            f"rsi={rsi:.1f} move={bar_move:.2%} center={center_slope:.2%} drift={drift_ratio:.2f} age={shock_age}"
        )

        if has_position and self.entry_price:
            pnl_pct = (price - self.entry_price) / self.entry_price
            hold_bars = self.iteration_index - int(self.entry_bar_index or self.iteration_index)

            if hold_bars >= int(self.parameters["failed_bounce_bars"]) and pnl_pct <= -float(self.parameters["failed_bounce_loss"]):
                self._exit(qty, price, f"Failed bounce {pnl_pct:.2%}")
                return
            if price < window_low * (1 - float(self.parameters["breakdown_exit_buffer"])):
                self._exit(qty, price, f"Support broke {pnl_pct:.2%}")
                return
            if pnl_pct <= -float(self.parameters["stop_loss"]):
                self._exit(qty, price, f"Stop {pnl_pct:.2%}")
                return
            if pnl_pct >= float(self.parameters["hard_take_profit"]):
                self._exit(qty, price, f"Hard take profit {pnl_pct:.2%}")
                return
            if pnl_pct >= float(self.parameters["take_profit"]):
                self._exit(qty, price, f"Take profit {pnl_pct:.2%}")
                return
            if range_position >= float(self.parameters["exit_range_position_min"]):
                self._exit(qty, price, f"Range exit pos={range_position:.2f}")
                return
            if self.regime_state == "BREAKOUT_PAUSE" and pnl_pct > 0:
                self._exit(qty, price, f"Breakout pause take {pnl_pct:.2%}")
                return
            if self.regime_state == "OFF":
                self._exit(qty, price, f"Regime off {pnl_pct:.2%}")
                return
            return

        if self.regime_state != "OSCILLATION_ACTIVE":
            return
        if self.iteration_index < self.pause_until_bar_index:
            return
        if (self.iteration_index - self.last_exit_bar_index) < int(self.parameters["cooldown_bars"]):
            return

        near_support = range_position <= float(self.parameters["entry_range_position_max"])
        reversal_confirmed = (
            price > prev_price
            and prev_price >= prev2_price * float(self.parameters["reversal_low_tolerance"])
            and prev2_price <= prev3_price * 1.01
        )
        if not (near_support and reversal_confirmed and rsi <= float(self.parameters["rsi_entry_max"])):
            return

        allocation_value = float(self.portfolio_value or 0.0) * float(self.parameters["position_size"])
        quantity = allocation_value / price if price > 0 else 0.0
        if quantity <= 0:
            return

        order = self.create_order(self.base_asset, quantity, "buy", type="market", quote=self.quote_asset)
        self.submit_order(order)
        self.entry_price = price
        self.entry_bar_index = self.iteration_index
        self.total_entries += 1
        self.log_message(
            f"[ENTRY] BUY qty={quantity:.6f} @ {price:.2f} dd={macro_drawdown:.2%} "
            f"pos={range_position:.2f} range={range_pct:.2%} touches=({lower_touches}/{upper_touches})"
        )

    def _exit(self, quantity: float, price: float, reason: str):
        if quantity <= 0:
            return
        order = self.create_order(self.base_asset, quantity, "sell", type="market", quote=self.quote_asset)
        self.submit_order(order)
        pnl_pct = (price - self.entry_price) / self.entry_price if self.entry_price else 0.0
        self.log_message(f"[EXIT] SELL qty={quantity:.6f} @ {price:.2f} | {reason} | pnl={pnl_pct:.2%}")
        self.entry_price = None
        self.entry_bar_index = None
        self.last_exit_bar_index = self.iteration_index

    def on_abrupt_closing(self):
        self.log_message(f"Strategy closing. Entries executed={self.total_entries}")


def run_backtest(source: str = "alpaca", start: Optional[dt.datetime] = None, end: Optional[dt.datetime] = None):
    _load_env()
    tzinfo = pytz.timezone("UTC")
    backtesting_start = start or tzinfo.localize(dt.datetime(2026, 2, 1))
    backtesting_end = end or tzinfo.localize(dt.datetime(2026, 2, 26))

    print("🧪 ETH POST-DROP OSCILLATION BACKTEST")
    print("=" * 78)
    print(f"Source: {source}")
    print(f"Period: {backtesting_start} -> {backtesting_end}")

    if source == "alpaca":
        from lumibot.backtesting import AlpacaBacktesting

        results, strategy = ETHPostDropOscillationStrategy.run_backtest(
            datasource_class=AlpacaBacktesting,
            backtesting_start=backtesting_start,
            backtesting_end=backtesting_end,
            benchmark_asset=Asset("ETH", asset_type="crypto"),
            analyze_backtest=True,
            show_progress_bar=True,
            budget=100000,
            parameters=ETHPostDropOscillationStrategy.parameters.copy(),
            timestep="minute",
            market="24/7",
            config=_build_alpaca_backtest_config(),
            refresh_cache=False,
            warm_up_trading_days=0,
            auto_adjust=False,
        )
    else:
        from lumibot.backtesting import YahooDataBacktesting

        params = ETHPostDropOscillationStrategy.parameters.copy()
        params.update(
            {
                "symbol": "ETH-USD",
                "quote_symbol": "USD",
                "sleeptime": "1D",
                "bar_unit": "day",
                "aggregation_minutes": 1,
                "history_bars": 180,
                "macro_drop_lookback_bars": 60,
                "range_lookback_bars": 12,
            }
        )
        results, strategy = ETHPostDropOscillationStrategy.run_backtest(
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
    parser = argparse.ArgumentParser(description="Run ETH post-drop oscillation backtest")
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
