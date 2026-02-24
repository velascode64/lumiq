"""
Live crypto mean reversion strategy focused on ETH/BTC/SOL for overnight testing.

Design goals:
- 24/7 crypto trading
- aggressive cadence (every 5 minutes)
- symbols restricted to ETH, BTC, SOL
- runtime parameter updates supported while strategy is live
"""

from datetime import datetime
from typing import List

from lumibot.entities import Asset
from lumibot.strategies import Strategy


class LiveCryptoMeanReaversionStrategy(Strategy):
    """
    Aggressive mean reversion strategy for crypto.

    Notes:
    - Keeps to long-only entries on negative z-score dislocations.
    - Exits on mean reversion, stop-loss, or take-profit.
    - Can auto-tune aggression based on progress vs target.
    """

    parameters = {
        # Universe restriction
        "symbols": ["ETH", "BTC", "SOLANA"],
        # Execution profile
        "sleeptime": "1M",
        "lookback_bars": 240,        # minute bars
        "mean_window": 60,
        "std_window": 60,
        # Entry/exit thresholds
        "zscore_entry": 1.05,        # aggressive
        "zscore_exit": 0.20,
        "stop_loss_pct": 0.025,      # 2.5%
        "take_profit_pct": 0.04,     # 4%
        # Sizing/risk
        "base_position_pct": 0.22,   # 22% of cash base sizing (aggressive)
        "max_position_pct": 0.35,    # hard cap per symbol
        "max_open_positions": 3,
        "min_notional_usd": 30.0,
        "aggressive_factor": 1.0,
        "max_aggressive_factor": 1.8,
        # Targeting
        "starting_budget_usd": 10000.0,
        "goal_profit_usd": 1000.0,
        "profit_horizon_hours": 24.0,
        "max_loss_before_derisk_usd": 700.0,
        # Auto-tuning
        "enable_auto_tuning": True,
        "tuning_interval_minutes": 30,
    }

    _ALLOWED = {"ETH", "BTC", "SOL"}
    _MAP = {
        "ETH": "ETH",
        "ETH/USD": "ETH",
        "BTC": "BTC",
        "BTC/USD": "BTC",
        "SOL": "SOL",
        "SOLANA": "SOL",
        "SOL/USD": "SOL",
    }

    def initialize(self):
        # 24/7 setup for crypto
        self.market_hours = None
        self.sleeptime = str(self.parameters.get("sleeptime", "5M"))
        self.usd_quote = Asset(symbol="USD", asset_type="forex")
        try:
            self.set_market("24/7")
        except Exception:
            pass
        if hasattr(self, "broker") and self.broker is not None:
            try:
                self.broker.market = "24/7"
            except Exception:
                pass

        self._sanitize_symbols()
        self._refresh_runtime_params()

        self.vars.start_dt = self.get_datetime()
        self.vars.start_portfolio_value = float(self.portfolio_value or 0.0)
        self.vars.last_tune_dt = self.get_datetime()

        self.log_message("=" * 72)
        self.log_message("LIVE CRYPTO MEAN REAVERSION STRATEGY")
        self.log_message(f"Symbols: {', '.join(self.symbols)}")
        self.log_message(f"Cadence: {self.sleeptime} | Market: 24/7")
        self.log_message(
            f"Target: +${self.goal_profit_usd:,.2f} from baseline "
            f"${self.vars.start_portfolio_value:,.2f}"
        )
        self.log_message(
            f"Aggressive config: entry_z={self.zscore_entry:.2f}, "
            f"base_pos={self.base_position_pct:.2f}, max_pos={self.max_position_pct:.2f}"
        )
        self.log_message("=" * 72)

    def on_parameters_updated(self, updated_params: dict):
        self.log_message(f"[PARAMS] Updated: {updated_params}")
        if "symbols" in updated_params:
            self._sanitize_symbols()
        self._refresh_runtime_params()

    def is_market_open(self):
        return True

    def should_continue_trading(self):
        return True

    def on_trading_iteration(self):
        self._refresh_runtime_params()
        now = self.get_datetime()

        if self.enable_auto_tuning:
            last_tune = self.vars.last_tune_dt
            elapsed_min = (now - last_tune).total_seconds() / 60.0
            if elapsed_min >= self.tuning_interval_minutes:
                self._auto_tune(now)
                self.vars.last_tune_dt = now

        for symbol in self.symbols:
            self._trade_symbol(symbol)

    def _sanitize_symbols(self):
        raw = self.parameters.get("symbols", ["ETH", "BTC", "SOLANA"])
        normalized: List[str] = []
        for item in raw:
            key = str(item).strip().upper()
            mapped = self._MAP.get(key)
            if mapped in self._ALLOWED and mapped not in normalized:
                normalized.append(mapped)
        if not normalized:
            normalized = ["ETH", "BTC", "SOL"]
        self.symbols = normalized
        self.parameters["symbols"] = normalized

    def _refresh_runtime_params(self):
        self.lookback_bars = int(self.parameters.get("lookback_bars", 240))
        self.mean_window = int(self.parameters.get("mean_window", 60))
        self.std_window = int(self.parameters.get("std_window", 60))
        self.zscore_entry = float(self.parameters.get("zscore_entry", 1.05))
        self.zscore_exit = float(self.parameters.get("zscore_exit", 0.20))
        self.stop_loss_pct = float(self.parameters.get("stop_loss_pct", 0.025))
        self.take_profit_pct = float(self.parameters.get("take_profit_pct", 0.04))
        self.base_position_pct = float(self.parameters.get("base_position_pct", 0.22))
        self.max_position_pct = float(self.parameters.get("max_position_pct", 0.35))
        self.max_open_positions = int(self.parameters.get("max_open_positions", 3))
        self.min_notional_usd = float(self.parameters.get("min_notional_usd", 30.0))
        self.aggressive_factor = float(self.parameters.get("aggressive_factor", 1.0))
        self.max_aggressive_factor = float(self.parameters.get("max_aggressive_factor", 1.8))
        self.goal_profit_usd = float(self.parameters.get("goal_profit_usd", 1000.0))
        self.profit_horizon_hours = float(self.parameters.get("profit_horizon_hours", 24.0))
        self.max_loss_before_derisk_usd = float(self.parameters.get("max_loss_before_derisk_usd", 700.0))
        self.enable_auto_tuning = bool(self.parameters.get("enable_auto_tuning", True))
        self.tuning_interval_minutes = int(self.parameters.get("tuning_interval_minutes", 30))

    def _trade_symbol(self, symbol: str):
        asset = Asset(symbol=symbol, asset_type="crypto")

        bars = self.get_historical_prices(asset, self.lookback_bars, "minute", quote=self.usd_quote)
        if not bars:
            self.log_message(f"[NO-DATA] {symbol}: historical bars unavailable")
            return

        df = getattr(bars, "pandas_df", None)
        if df is None:
            df = getattr(bars, "df", None)
        if df is None:
            self.log_message(f"[NO-DATA] {symbol}: bars dataframe missing")
            return
        if len(df) < max(self.mean_window, self.std_window) + 2:
            self.log_message(
                f"[NO-ENTRY] {symbol}: insufficient history "
                f"({len(df)}/{max(self.mean_window, self.std_window) + 2})"
            )
            return

        close = float(df["close"].iloc[-1])
        rolling_mean = float(df["close"].rolling(self.mean_window).mean().iloc[-1])
        rolling_std = float(df["close"].rolling(self.std_window).std().iloc[-1] or 0.0)
        if rolling_std <= 0:
            self.log_message(f"[NO-ENTRY] {symbol}: rolling_std <= 0")
            return

        zscore = (close - rolling_mean) / rolling_std
        self.log_message(
            f"[CHECK] {symbol}: price={close:.3f} mean={rolling_mean:.3f} "
            f"std={rolling_std:.5f} z={zscore:.2f}"
        )
        position = self.get_position(asset)
        qty = float(position.quantity) if position and float(position.quantity) > 0 else 0.0
        avg_price = float(
            (getattr(position, "avg_entry_price", 0.0) if position else 0.0)
            or (getattr(position, "avg_price", 0.0) if position else 0.0)
            or close
        )

        # Exit logic for existing position.
        if qty > 0:
            pnl_pct = (close - avg_price) / avg_price if avg_price > 0 else 0.0
            should_exit = (
                pnl_pct <= -self.stop_loss_pct
                or pnl_pct >= self.take_profit_pct
                or zscore >= self.zscore_exit
            )
            if should_exit:
                order = self.create_order(asset, qty, "sell", type="market", quote=self.usd_quote)
                self.submit_order(order)
                self.log_message(
                    f"[EXIT] {symbol} qty={qty:.6f} price={close:.3f} "
                    f"pnl={pnl_pct*100:.2f}% z={zscore:.2f}"
                )
            else:
                self.log_message(
                    f"[HOLD] {symbol}: open position kept | "
                    f"pnl={pnl_pct*100:.2f}% (SL={-self.stop_loss_pct*100:.2f}% TP={self.take_profit_pct*100:.2f}%) "
                    f"z={zscore:.2f} (exit_z={self.zscore_exit:.2f})"
                )
            return

        # Entry logic (long-only mean reversion).
        open_positions = self._open_positions_count()
        if open_positions >= self.max_open_positions:
            self.log_message(
                f"[NO-ENTRY] {symbol}: max open positions reached "
                f"({open_positions}/{self.max_open_positions})"
            )
            return
        if zscore > -self.zscore_entry:
            self.log_message(
                f"[NO-ENTRY] {symbol}: zscore condition failed "
                f"(z={zscore:.2f} > entry_threshold={-self.zscore_entry:.2f})"
            )
            return

        portfolio = float(self.portfolio_value or 0.0)
        cash = float(self.cash or 0.0)
        risk_fraction = min(self.max_position_pct, self.base_position_pct * self.aggressive_factor)
        notional = min(portfolio * self.max_position_pct, cash * risk_fraction)
        if notional < self.min_notional_usd:
            self.log_message(
                f"[NO-ENTRY] {symbol}: notional too low "
                f"(${notional:.2f} < min ${self.min_notional_usd:.2f}) "
                f"| cash=${cash:.2f} risk_fraction={risk_fraction:.3f}"
            )
            return

        quantity = notional / close
        if quantity <= 0:
            self.log_message(f"[NO-ENTRY] {symbol}: computed quantity <= 0")
            return

        self.log_message(
            f"[ENTRY-CHECK] {symbol}: PASSED | notional=${notional:.2f} qty={quantity:.6f} "
            f"risk_fraction={risk_fraction:.3f} z={zscore:.2f}"
        )
        order = self.create_order(asset, quantity, "buy", type="market", quote=self.usd_quote)
        self.submit_order(order)
        self.log_message(
            f"[ENTRY] {symbol} qty={quantity:.6f} notional=${notional:.2f} "
            f"price={close:.3f} z={zscore:.2f} aggress={self.aggressive_factor:.2f}"
        )

    def _open_positions_count(self) -> int:
        count = 0
        for pos in self.get_positions():
            try:
                if float(pos.quantity) > 0:
                    sym = str(getattr(pos.asset, "symbol", "")).upper()
                    if sym in {"ETH", "BTC", "SOL"}:
                        count += 1
            except Exception:
                continue
        return count

    def _auto_tune(self, now: datetime):
        current_value = float(self.portfolio_value or 0.0)
        pnl_usd = current_value - float(self.vars.start_portfolio_value or 0.0)
        hours_elapsed = max(0.01, (now - self.vars.start_dt).total_seconds() / 3600.0)

        expected_progress = min(1.0, hours_elapsed / max(1.0, self.profit_horizon_hours))
        actual_progress = max(0.0, pnl_usd / max(1.0, self.goal_profit_usd))

        # Hit target: de-risk and preserve gains.
        if pnl_usd >= self.goal_profit_usd:
            self.aggressive_factor = max(0.75, self.aggressive_factor * 0.90)
            self.base_position_pct = max(0.10, self.base_position_pct - 0.01)
            self.zscore_entry = min(1.40, self.zscore_entry + 0.05)
            self.log_message(
                f"[TUNE] target reached pnl=${pnl_usd:.2f}. De-risking to lock gains."
            )
        # Behind schedule: increase aggressiveness moderately.
        elif actual_progress + 0.15 < expected_progress:
            self.aggressive_factor = min(self.max_aggressive_factor, self.aggressive_factor * 1.10)
            self.base_position_pct = min(self.max_position_pct, self.base_position_pct + 0.01)
            self.zscore_entry = max(0.75, self.zscore_entry - 0.05)
            self.log_message(
                f"[TUNE] behind target pnl=${pnl_usd:.2f}. Increasing aggression."
            )
        # Too much drawdown: de-risk.
        elif pnl_usd <= -abs(self.max_loss_before_derisk_usd):
            self.aggressive_factor = max(0.70, self.aggressive_factor * 0.85)
            self.base_position_pct = max(0.10, self.base_position_pct - 0.01)
            self.zscore_entry = min(1.60, self.zscore_entry + 0.05)
            self.log_message(
                f"[TUNE] drawdown detected pnl=${pnl_usd:.2f}. Reducing aggression."
            )

        # Persist tuned values into parameters so runtime updates remain consistent.
        self.parameters["aggressive_factor"] = round(self.aggressive_factor, 4)
        self.parameters["base_position_pct"] = round(self.base_position_pct, 4)
        self.parameters["zscore_entry"] = round(self.zscore_entry, 4)
