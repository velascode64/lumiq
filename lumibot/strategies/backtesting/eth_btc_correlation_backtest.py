"""
ETH/BTC lead-lag swing strategy backtest.

Hypothesis:
- BTC often leads crypto risk-on moves.
- ETH tends to catch up after BTC has already moved.
- We buy ETH when BTC momentum is strong, ETH is lagging, and ETH begins
  showing catch-up confirmation.

This is intentionally designed as a swing strategy:
- analysis on synthetic hourly bars (aggregated from minute data)
- holding period from hours to a few days
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
    """
    Build an AlpacaBacktesting config directly from env vars.

    We avoid importing `lumibot.credentials` here because that module can
    initialize trading-related objects, which is noisy and problematic in this
    workspace when network access is restricted.
    """
    oauth_token = os.getenv("ALPACA_OAUTH_TOKEN")
    test_api_key = os.getenv("ALPACA_TEST_API_KEY")
    test_api_secret = os.getenv("ALPACA_TEST_API_SECRET")
    api_key = os.getenv("ALPACA_API_KEY")
    api_secret = os.getenv("ALPACA_API_SECRET")

    if oauth_token:
        return {
            "OAUTH_TOKEN": oauth_token,
            "PAPER": True,
        }

    if test_api_key and test_api_secret:
        return {
            "API_KEY": test_api_key,
            "API_SECRET": test_api_secret,
            "PAPER": True,
        }

    if api_key and api_secret:
        return {
            "API_KEY": api_key,
            "API_SECRET": api_secret,
            "PAPER": True,
        }

    raise RuntimeError(
        "No usable Alpaca config found. Set ALPACA_TEST_API_KEY/SECRET, "
        "ALPACA_API_KEY/ALPACA_API_SECRET, or ALPACA_OAUTH_TOKEN in .env"
    )


class CryptoLeadLagStrategy(Strategy):
    """
    ETH swing strategy with BTC confirmation.

    Practical interpretation:
    - BTC acts as market regime / confirmation filter.
    - ETH is the traded asset.
    - We still use relative BTC vs ETH strength, but we avoid relying only on
      "lag catch-up", which was too weak in the first version.
    """

    parameters = {
        # Symbols / data
        "btc_symbol": "BTC/USD",
        "eth_symbol": "ETH/USD",
        "quote_symbol": "USD",
        "sleeptime": "1H",
        "bar_unit": "minute",         # aggregate locally to hourly
        "aggregation_minutes": 60,
        "history_bars": 320,          # hourly bars after aggregation

        # Regime filter
        "ma_fast": 12,
        "ma_mid": 36,
        "ma_slow": 120,
        "ma_slope_lookback": 12,
        "min_btc_slow_slope": 0.0,    # allow more regimes, just avoid obvious weakness

        # Signal windows
        "return_lookback_bars": 8,    # 8h
        "short_momentum_bars": 3,     # 3h confirmation
        "btc_breakout_lookback": 24,  # 1d breakout context
        "rsi_period": 14,

        # ETH trigger structure
        "eth_breakout_lookback": 24,
        "eth_breakout_buffer": 0.0015,
        "eth_breakout_rsi_min": 52,
        "eth_breakout_momentum_min": 0.005,
        "eth_pullback_local_high_lookback": 36,
        "eth_pullback_min_drawdown": 0.02,
        "eth_pullback_max_drawdown": 0.08,
        "eth_pullback_to_fast_ma_tolerance": 0.012,
        "eth_pullback_rsi_min": 42,
        "eth_pullback_rsi_max": 58,
        "eth_pullback_reversal_momentum_min": 0.003,

        # Entry thresholds
        "btc_lead_threshold": 0.0,         # BTC can be flat-to-strong; regime filter matters more
        "spread_entry_threshold": -0.10,   # effectively disable hard spread gating
        "btc_breakout_buffer": -0.0025,    # accept BTC slightly below prior high

        # Volatility gating on ETH
        "atr_period": 14,
        "min_eth_atr_pct": 0.008,
        "max_eth_atr_pct": 0.055,

        # Risk / exits
        "position_size": 1.75,
        "stop_loss": 0.020,
        "trailing_activation_profit": 0.007,
        "trailing_stop": 0.018,
        "hard_take_profit": 0.10,
        "max_hold_bars": 72,               # let winners run longer
        "cooldown_bars": 0,

        # Spread exit
        "spread_take_ratio": -1.0,         # disable spread exit
        "spread_exit_floor": -1.0,         # disable spread exit
        "btc_reversal_threshold": -0.018,  # need clearer BTC weakness before bailing
    }

    def initialize(self):
        self.sleeptime = self.parameters.get("sleeptime", "1H")
        self.market_hours = None  # crypto 24/7

        quote_symbol = self.parameters.get("quote_symbol", "USD")
        quote_type = "forex" if quote_symbol.upper() == "USD" else "crypto"

        self.quote_asset = Asset(symbol=quote_symbol, asset_type=quote_type)
        self.btc_asset = Asset(symbol="BTC", asset_type="crypto")
        self.eth_asset = Asset(symbol="ETH", asset_type="crypto")

        self.iteration_index = 0
        self.last_exit_bar_index = -10_000
        self.total_entries = 0

        self.entry_price: Optional[float] = None
        self.entry_bar_index: Optional[int] = None
        self.peak_price_since_entry: Optional[float] = None
        self.entry_spread: Optional[float] = None

        self.log_message("=" * 78)
        self.log_message("ETH/BTC CONFIRMED MOMENTUM SWING BACKTEST")
        self.log_message(
            f"lead={self.parameters['btc_lead_threshold']:.2%} "
            f"spread={self.parameters['spread_entry_threshold']:.2%} "
            f"pos={self.parameters['position_size']:.0%}"
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

    def _fetch_series(self, asset: Asset):
        requested_bars = int(self.parameters["history_bars"])
        requested_unit = self.parameters["bar_unit"]

        if requested_unit == "minute":
            requested_bars *= int(self.parameters["aggregation_minutes"])

        bars = self.get_historical_prices(asset, requested_bars, requested_unit, quote=self.quote_asset)
        if not bars or not hasattr(bars, "df") or bars.df is None or bars.df.empty:
            return None, None, None, "hour" if requested_unit == "minute" else requested_unit

        df = bars.df.copy()
        closes = df["close"].astype(float).to_numpy()
        highs = df["high"].astype(float).to_numpy() if "high" in df.columns else closes
        lows = df["low"].astype(float).to_numpy() if "low" in df.columns else closes
        unit = requested_unit

        if requested_unit == "minute":
            agg_n = int(self.parameters["aggregation_minutes"])
            n = len(closes) // agg_n
            if n <= 0:
                return None, None, None, "hour"
            closes = closes[-n * agg_n :].reshape(n, agg_n)[:, -1]
            highs = highs[-n * agg_n :].reshape(n, agg_n).max(axis=1)
            lows = lows[-n * agg_n :].reshape(n, agg_n).min(axis=1)
            unit = "hour"

        return closes, highs, lows, unit

    def on_trading_iteration(self):
        self.iteration_index += 1

        btc_closes, btc_highs, _btc_lows, unit = self._fetch_series(self.btc_asset)
        eth_closes, eth_highs, eth_lows, _ = self._fetch_series(self.eth_asset)

        if btc_closes is None or eth_closes is None:
            self.log_message("[DATA] Missing BTC/ETH bars")
            return

        needed = max(
            int(self.parameters["ma_slow"]) + int(self.parameters["ma_slope_lookback"]) + 2,
            int(self.parameters["btc_breakout_lookback"]) + 2,
            int(self.parameters["return_lookback_bars"]) + 2,
            int(self.parameters["atr_period"]) + 2,
            int(self.parameters["short_momentum_bars"]) + 2,
        )
        if len(btc_closes) < needed or len(eth_closes) < needed:
            self.log_message(f"[DATA] Insufficient bars btc={len(btc_closes)} eth={len(eth_closes)} need={needed}")
            return

        btc_price = float(btc_closes[-1])
        eth_price = float(eth_closes[-1])

        ma_fast_n = int(self.parameters["ma_fast"])
        ma_mid_n = int(self.parameters["ma_mid"])
        ma_slow_n = int(self.parameters["ma_slow"])
        slope_lb = int(self.parameters["ma_slope_lookback"])

        btc_ma_fast = float(np.mean(btc_closes[-ma_fast_n:]))
        btc_ma_mid = float(np.mean(btc_closes[-ma_mid_n:]))
        btc_ma_slow = float(np.mean(btc_closes[-ma_slow_n:]))
        btc_ma_slow_prev = float(np.mean(btc_closes[-(ma_slow_n + slope_lb):-slope_lb]))
        btc_slow_slope = (btc_ma_slow / btc_ma_slow_prev - 1.0) if btc_ma_slow_prev > 0 else 0.0

        eth_ma_fast = float(np.mean(eth_closes[-ma_fast_n:]))
        eth_ma_mid = float(np.mean(eth_closes[-ma_mid_n:]))
        eth_ma_slow = float(np.mean(eth_closes[-ma_slow_n:]))
        eth_rsi = self._calc_rsi(eth_closes, int(self.parameters["rsi_period"]))

        btc_regime = (
            btc_price > btc_ma_mid
            and btc_ma_fast > btc_ma_mid > btc_ma_slow
            and btc_slow_slope >= float(self.parameters["min_btc_slow_slope"])
        )
        eth_supportive = eth_price > eth_ma_slow and eth_ma_fast > eth_ma_mid

        ret_lb = int(self.parameters["return_lookback_bars"])
        short_lb = int(self.parameters["short_momentum_bars"])

        btc_base = float(btc_closes[-(ret_lb + 1)])
        eth_base = float(eth_closes[-(ret_lb + 1)])
        btc_return = (btc_price / btc_base - 1.0) if btc_base > 0 else 0.0
        eth_return = (eth_price / eth_base - 1.0) if eth_base > 0 else 0.0
        spread = btc_return - eth_return

        btc_short_base = float(btc_closes[-(short_lb + 1)])
        eth_short_base = float(eth_closes[-(short_lb + 1)])
        btc_short_mom = (btc_price / btc_short_base - 1.0) if btc_short_base > 0 else 0.0
        eth_short_mom = (eth_price / eth_short_base - 1.0) if eth_short_base > 0 else 0.0

        btc_recent_high = float(np.max(btc_highs[-(int(self.parameters["btc_breakout_lookback"]) + 1):-1]))
        btc_breakout_ok = btc_price >= btc_recent_high * (1 + float(self.parameters["btc_breakout_buffer"]))

        eth_recent_high = float(np.max(eth_highs[-(int(self.parameters["eth_breakout_lookback"]) + 1):-1]))
        eth_breakout_ok = eth_price >= eth_recent_high * (1 + float(self.parameters["eth_breakout_buffer"]))

        eth_local_high = float(np.max(eth_highs[-int(self.parameters["eth_pullback_local_high_lookback"]):]))
        eth_pullback_dd = (eth_local_high - eth_price) / eth_local_high if eth_local_high > 0 else 0.0
        eth_dist_to_fast_ma = abs(eth_price / eth_ma_fast - 1.0) if eth_ma_fast > 0 else 0.0

        eth_atr_pct = self._calc_atr_pct(eth_highs, eth_lows, eth_closes, int(self.parameters["atr_period"]))

        self.log_message(
            f"[CHECK] unit={unit} BTC={btc_price:.2f} ETH={eth_price:.2f} "
            f"btc_ret={btc_return:.2%} eth_ret={eth_return:.2%} spread={spread:.2%} "
            f"btc_short={btc_short_mom:.2%} eth_short={eth_short_mom:.2%} rsi={eth_rsi:.1f} "
            f"btc_regime={btc_regime} eth_ok={eth_supportive} atr={eth_atr_pct:.2%}"
        )

        position = self.get_position(self.eth_asset)
        has_position = bool(position and getattr(position, "quantity", 0))
        qty = float(getattr(position, "quantity", 0) or 0.0)

        if has_position and self.entry_price:
            pnl_pct = (eth_price - self.entry_price) / self.entry_price
            self.peak_price_since_entry = max(float(self.peak_price_since_entry or eth_price), eth_price)

            if pnl_pct <= -float(self.parameters["stop_loss"]):
                self._exit(qty, eth_price, f"Stop {pnl_pct:.2%}")
                return

            if pnl_pct >= float(self.parameters["trailing_activation_profit"]) and self.peak_price_since_entry:
                trail_dd = (self.peak_price_since_entry - eth_price) / self.peak_price_since_entry
                if trail_dd >= float(self.parameters["trailing_stop"]):
                    self._exit(qty, eth_price, f"Trail {trail_dd:.2%}")
                    return

            if pnl_pct >= float(self.parameters["hard_take_profit"]):
                self._exit(qty, eth_price, f"Hard TP {pnl_pct:.2%}")
                return

            hold_bars = self.iteration_index - int(self.entry_bar_index or self.iteration_index)
            if hold_bars >= int(self.parameters["max_hold_bars"]):
                self._exit(qty, eth_price, f"Max hold {hold_bars}")
                return

            if btc_short_mom <= float(self.parameters["btc_reversal_threshold"]):
                self._exit(qty, eth_price, f"BTC reversal {btc_short_mom:.2%}")
                return

            if not btc_regime and pnl_pct > 0:
                self._exit(qty, eth_price, "BTC regime lost")
                return
            return

        if (self.iteration_index - self.last_exit_bar_index) < int(self.parameters["cooldown_bars"]):
            return

        if not btc_regime or not eth_supportive:
            return

        if not (float(self.parameters["min_eth_atr_pct"]) <= eth_atr_pct <= float(self.parameters["max_eth_atr_pct"])):
            return

        entry_signal = (
            (btc_breakout_ok or (btc_price > btc_ma_fast and btc_short_mom > -0.002))
            and btc_return >= float(self.parameters["btc_lead_threshold"])
            and spread >= float(self.parameters["spread_entry_threshold"])
            and btc_short_mom >= -0.002
        )
        if not entry_signal:
            return

        eth_breakout_entry = (
            eth_breakout_ok
            and eth_rsi >= float(self.parameters["eth_breakout_rsi_min"])
            and eth_short_mom >= float(self.parameters["eth_breakout_momentum_min"])
        )
        eth_pullback_entry = (
            float(self.parameters["eth_pullback_min_drawdown"]) <= eth_pullback_dd <= float(self.parameters["eth_pullback_max_drawdown"])
            and eth_dist_to_fast_ma <= float(self.parameters["eth_pullback_to_fast_ma_tolerance"])
            and float(self.parameters["eth_pullback_rsi_min"]) <= eth_rsi <= float(self.parameters["eth_pullback_rsi_max"])
            and eth_short_mom >= float(self.parameters["eth_pullback_reversal_momentum_min"])
        )
        if not (eth_breakout_entry or eth_pullback_entry):
            return

        mode = "breakout" if eth_breakout_entry else "pullback"

        allocation_value = float(self.portfolio_value or 0.0) * float(self.parameters["position_size"])
        quantity = allocation_value / eth_price if eth_price > 0 else 0.0
        if quantity <= 0:
            return

        order = self.create_order(self.eth_asset, quantity, "buy", type="market", quote=self.quote_asset)
        self.submit_order(order)
        self.entry_price = eth_price
        self.entry_bar_index = self.iteration_index
        self.peak_price_since_entry = eth_price
        self.entry_spread = spread
        self.total_entries += 1
        self.log_message(
            f"[ENTRY-{mode.upper()}] BUY ETH qty={quantity:.6f} @ {eth_price:.2f} "
            f"btc_ret={btc_return:.2%} eth_ret={eth_return:.2%} spread={spread:.2%} "
            f"rsi={eth_rsi:.1f}"
        )

    def _exit(self, quantity: float, price: float, reason: str):
        if quantity <= 0:
            return
        order = self.create_order(self.eth_asset, quantity, "sell", type="market", quote=self.quote_asset)
        self.submit_order(order)
        pnl_pct = (price - self.entry_price) / self.entry_price if self.entry_price else 0.0
        self.log_message(f"[EXIT] SELL ETH qty={quantity:.6f} @ {price:.2f} | {reason} | pnl={pnl_pct:.2%}")
        self.entry_price = None
        self.entry_bar_index = None
        self.peak_price_since_entry = None
        self.entry_spread = None
        self.last_exit_bar_index = self.iteration_index

    def on_abrupt_closing(self):
        self.log_message(f"Strategy closing. Entries executed: {self.total_entries}")


def run_backtest(
    source: str = "alpaca",
    start: Optional[dt.datetime] = None,
    end: Optional[dt.datetime] = None,
):
    _load_env()
    tzinfo = pytz.timezone("UTC")
    backtesting_start = start or tzinfo.localize(dt.datetime(2025, 2, 1))
    backtesting_end = end or tzinfo.localize(dt.datetime(2026, 2, 1))

    print("🧪 ETH/BTC LEAD-LAG SWING BACKTEST")
    print("=" * 78)
    print(f"Source: {source}")
    print(f"Period: {backtesting_start} -> {backtesting_end}")

    if source == "alpaca":
        from lumibot.backtesting import AlpacaBacktesting
        alpaca_config = _build_alpaca_backtest_config()

        results, strategy = CryptoLeadLagStrategy.run_backtest(
            datasource_class=AlpacaBacktesting,
            backtesting_start=backtesting_start,
            backtesting_end=backtesting_end,
            benchmark_asset=Asset("ETH", asset_type="crypto"),
            analyze_backtest=True,
            show_progress_bar=True,
            budget=100000,
            parameters=CryptoLeadLagStrategy.parameters.copy(),
            timestep="minute",
            market="24/7",
            config=alpaca_config,
            refresh_cache=False,
            warm_up_trading_days=0,
            auto_adjust=False,
        )
    else:
        from lumibot.backtesting import YahooDataBacktesting

        params = CryptoLeadLagStrategy.parameters.copy()
        params.update(
            {
                "btc_symbol": "BTC-USD",
                "eth_symbol": "ETH-USD",
                "quote_symbol": "USD",
                "sleeptime": "1D",
                "bar_unit": "day",
                "history_bars": 220,
                "ma_fast": 8,
                "ma_mid": 21,
                "ma_slow": 55,
                "ma_slope_lookback": 8,
                "return_lookback_bars": 5,
                "short_momentum_bars": 2,
                "btc_breakout_lookback": 12,
                "max_hold_bars": 8,
            }
        )
        results, strategy = CryptoLeadLagStrategy.run_backtest(
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
    parser = argparse.ArgumentParser(description="Run ETH/BTC lead-lag swing backtest")
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
