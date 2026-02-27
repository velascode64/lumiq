"""
Alpaca streaming manager for real-time alert rules.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from alpaca.data.enums import DataFeed
from alpaca.data.live import StockDataStream, CryptoDataStream
import pandas as pd


logger = logging.getLogger(__name__)


def _is_crypto_symbol(symbol: str) -> bool:
    return "/" in symbol or "-" in symbol or symbol.upper().endswith("USD")


def _normalize_crypto_symbol(symbol: str) -> str:
    sym = symbol.upper().replace("-", "/")
    if "/" in sym:
        return sym
    if sym.endswith("USD") and len(sym) > 3:
        return f"{sym[:-3]}/USD"
    return sym


class AlertStreamManager:
    """
    Manage Alpaca data streams to evaluate alert rules in real-time.
    """

    def __init__(self, alert_system, send_callback: Callable[[int, str], None]):
        self.alert_system = alert_system
        self.send_callback = send_callback
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._stock_stream: Optional[StockDataStream] = None
        self._crypto_stream: Optional[CryptoDataStream] = None
        self._stock_symbols: Set[str] = set()
        self._crypto_symbols: Set[str] = set()
        self._bars_cache: Dict[Tuple[str, int], Tuple[datetime, pd.DataFrame]] = {}
        self._bars_cache_ttl = int(os.getenv("ALERT_BARS_CACHE_TTL", "60"))

    def start_in_thread(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="alert-stream", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._stock_stream:
            self._stock_stream.stop()
        if self._crypto_stream:
            self._crypto_stream.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def refresh_subscriptions(self) -> None:
        stock, crypto = self._collect_symbols()
        if stock != self._stock_symbols or crypto != self._crypto_symbols:
            self._stock_symbols = stock
            self._crypto_symbols = crypto
            if self._stock_stream:
                self._stock_stream.unsubscribe_trades()
                if stock:
                    self._stock_stream.subscribe_trades(self._on_trade, *sorted(stock))
            if self._crypto_stream:
                self._crypto_stream.unsubscribe_trades()
                if crypto:
                    self._crypto_stream.subscribe_trades(self._on_trade, *sorted(crypto))

    def _collect_symbols(self) -> Tuple[Set[str], Set[str]]:
        stock_symbols: Set[str] = set()
        crypto_symbols: Set[str] = set()
        for rule in self.alert_system.list_rules():
            if not rule.get("active", True):
                continue
            symbol = rule.get("symbol")
            if not symbol:
                continue
            if _is_crypto_symbol(symbol):
                crypto_symbols.add(_normalize_crypto_symbol(symbol))
            else:
                stock_symbols.add(symbol.upper())
        return stock_symbols, crypto_symbols

    def _run(self) -> None:
        feed = os.getenv("ALPACA_DATA_FEED", "IEX").strip().upper()
        data_feed = DataFeed.IEX if feed == "IEX" else DataFeed.SIP

        api_key = self.alert_system.data_service.api_key
        api_secret = self.alert_system.data_service.secret_key

        self._stock_stream = StockDataStream(api_key, api_secret, feed=data_feed)
        self._crypto_stream = CryptoDataStream(api_key, api_secret)

        self.refresh_subscriptions()

        # Run both streams in their own threads
        stock_thread = threading.Thread(target=self._stock_stream.run, daemon=True)
        crypto_thread = threading.Thread(target=self._crypto_stream.run, daemon=True)
        stock_thread.start()
        crypto_thread.start()

        while not self._stop_event.is_set():
            self._stop_event.wait(0.5)

    async def _on_trade(self, trade) -> None:
        self._handle_trade(trade)

    def _get_cached_bars(self, symbol: str, days: int, now: datetime) -> Optional[pd.DataFrame]:
        key = (symbol, days)
        cached = self._bars_cache.get(key)
        if cached:
            fetched_at, bars = cached
            if (now - fetched_at).total_seconds() < self._bars_cache_ttl:
                return bars
        bars = self.alert_system.data_service.get_stock_bars(symbol, days=days)
        if bars is None or bars.empty:
            return None
        self._bars_cache[key] = (now, bars)
        return bars

    def _prepare_prices(self, bars: pd.DataFrame, price: float) -> Optional[pd.Series]:
        if bars is None or bars.empty or "close" not in bars:
            return None
        prices = bars["close"].copy()
        if len(prices) == 0:
            return None
        prices.iloc[-1] = float(price)
        return prices

    def _handle_trade(self, trade) -> None:
        try:
            symbol = getattr(trade, "symbol", "")
            price = float(getattr(trade, "price", 0.0))
            if not symbol or price <= 0:
                return
            now = datetime.now(timezone.utc)
            for rule in self.alert_system.list_rules():
                if not rule.get("active", True):
                    continue
                if rule.get("symbol") is None:
                    continue
                rule_symbol = rule.get("symbol")
                if _is_crypto_symbol(rule_symbol):
                    rule_symbol = _normalize_crypto_symbol(rule_symbol)
                else:
                    rule_symbol = rule_symbol.upper()
                if rule_symbol != symbol:
                    continue
                triggered, message = self._evaluate_rule(rule, price, now)
                if triggered and message:
                    chat_id = rule.get("chat_id")
                    if chat_id is None:
                        chat_id = self.alert_system.get_default_chat_id()
                    if chat_id is None:
                        logger.warning("Alert triggered but no chat_id configured (rule=%s, symbol=%s)", rule.get("id"), symbol)
                        continue
                    logger.info("Sending alert (rule=%s, symbol=%s, chat_id=%s)", rule.get("id"), symbol, chat_id)
                    try:
                        self.send_callback(int(chat_id), message)
                    except Exception as exc:
                        logger.error("Failed to send alert (rule=%s, chat_id=%s): %s", rule.get("id"), chat_id, exc)
        except Exception as exc:
            logger.error("Stream trade handling failed: %s", exc)

    def _evaluate_rule(self, rule: Dict, price: float, now: datetime) -> Tuple[bool, Optional[str]]:
        rule_id = rule.get("id")
        rule_type = rule.get("type")
        symbol = rule.get("symbol", "")
        cooldown = int(rule.get("cooldown_seconds") or 3600)

        last_triggered = rule.get("last_triggered_at")
        if last_triggered:
            try:
                last_dt = datetime.fromisoformat(last_triggered)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                if (now - last_dt).total_seconds() < cooldown:
                    return False, None
            except Exception:
                pass

        if rule_type == "target_price":
            target = rule.get("target")
            if target is None:
                return False, None
            if price >= float(target):
                self.alert_system.update_rule(rule_id, {"last_triggered_at": now.isoformat()})
                msg = f"🎯 {symbol} alcanzó ${float(target):.2f} (ahora ${price:.2f})"
                return True, msg
            return False, None

        if rule_type == "max_price":
            reference = rule.get("reference_price")
            if reference is None:
                self.alert_system.update_rule(rule_id, {"reference_price": float(price)})
                return False, None
            if price >= float(reference):
                self.alert_system.update_rule(
                    rule_id,
                    {"last_triggered_at": now.isoformat(), "reference_price": float(price)},
                )
                msg = f"📈 {symbol} alcanzó un máximo reciente (precio ${price:.2f})"
                return True, msg
            return False, None

        if rule_type == "min_price":
            reference = rule.get("reference_price")
            if reference is None:
                self.alert_system.update_rule(rule_id, {"reference_price": float(price)})
                return False, None
            if price <= float(reference):
                self.alert_system.update_rule(
                    rule_id,
                    {"last_triggered_at": now.isoformat(), "reference_price": float(price)},
                )
                msg = f"📉 {symbol} alcanzó un mínimo reciente (precio ${price:.2f})"
                return True, msg
            return False, None

        if rule_type in {"percent_drop", "percent_rise"}:
            threshold = rule.get("threshold")
            reference = rule.get("reference_price")
            if threshold is None:
                return False, None
            if reference is None:
                # first trade sets reference price
                self.alert_system.update_rule(rule_id, {"reference_price": float(price)})
                return False, None
            change = (price - float(reference)) / float(reference) * 100
            if rule_type == "percent_drop" and change <= -abs(float(threshold)):
                self.alert_system.update_rule(
                    rule_id,
                    {"last_triggered_at": now.isoformat(), "reference_price": float(price)},
                )
                msg = f"📉 {symbol} cayó {abs(change):.2f}% (precio ${price:.2f})"
                return True, msg
            if rule_type == "percent_rise" and change >= abs(float(threshold)):
                self.alert_system.update_rule(
                    rule_id,
                    {"last_triggered_at": now.isoformat(), "reference_price": float(price)},
                )
                msg = f"📈 {symbol} subió {abs(change):.2f}% (precio ${price:.2f})"
                return True, msg

        if rule_type in {"rsi_oversold", "rsi_overbought", "macd_bullish_cross", "bollinger_middle_cross"}:
            symbol_key = symbol
            if _is_crypto_symbol(symbol):
                symbol_key = _normalize_crypto_symbol(symbol)
            else:
                symbol_key = symbol.upper()

            if rule_type == "rsi_oversold":
                period = int(rule.get("period") or 14)
                threshold = float(rule.get("threshold") or 30.0)
                lookback_days = int(rule.get("lookback_days") or max(60, period * 3))
                bars = self._get_cached_bars(symbol_key, lookback_days, now)
                prices = self._prepare_prices(bars, price) if bars is not None else None
                if prices is None:
                    return False, None
                rsi = self.alert_system.technical_analyzer.calculate_rsi(prices, period)
                if rsi <= threshold:
                    self.alert_system.update_rule(rule_id, {"last_triggered_at": now.isoformat()})
                    msg = f"📉 {symbol} RSI {rsi:.2f} por debajo de {threshold:.2f}"
                    return True, msg
                return False, None

            if rule_type == "rsi_overbought":
                period = int(rule.get("period") or 14)
                threshold = float(rule.get("threshold") or 70.0)
                lookback_days = int(rule.get("lookback_days") or max(60, period * 3))
                bars = self._get_cached_bars(symbol_key, lookback_days, now)
                prices = self._prepare_prices(bars, price) if bars is not None else None
                if prices is None:
                    return False, None
                rsi = self.alert_system.technical_analyzer.calculate_rsi(prices, period)
                if rsi >= threshold:
                    self.alert_system.update_rule(rule_id, {"last_triggered_at": now.isoformat()})
                    msg = f"📈 {symbol} RSI {rsi:.2f} por encima de {threshold:.2f}"
                    return True, msg
                return False, None

            if rule_type == "macd_bullish_cross":
                fast = int(rule.get("fast") or 12)
                slow = int(rule.get("slow") or 26)
                signal = int(rule.get("signal") or 9)
                lookback_days = int(rule.get("lookback_days") or max(90, slow * 3))
                bars = self._get_cached_bars(symbol_key, lookback_days, now)
                prices = self._prepare_prices(bars, price) if bars is not None else None
                if prices is None:
                    return False, None
                macd_series, signal_series = self.alert_system.technical_analyzer.calculate_macd(
                    prices,
                    fast=fast,
                    slow=slow,
                    signal=signal,
                )
                if macd_series is None or signal_series is None or len(macd_series) < 2:
                    return False, None
                prev_macd = float(macd_series.iloc[-2])
                prev_signal = float(signal_series.iloc[-2])
                curr_macd = float(macd_series.iloc[-1])
                curr_signal = float(signal_series.iloc[-1])
                if prev_macd <= prev_signal and curr_macd > curr_signal:
                    self.alert_system.update_rule(rule_id, {"last_triggered_at": now.isoformat()})
                    msg = (
                        f"📊 {symbol} MACD cruzó al alza "
                        f"(MACD {curr_macd:.2f} > señal {curr_signal:.2f})"
                    )
                    return True, msg
                return False, None

            if rule_type == "bollinger_middle_cross":
                period = int(rule.get("period") or 20)
                stddev = float(rule.get("stddev") or 2.0)
                direction = str(rule.get("direction") or "above").lower()
                lookback_days = int(rule.get("lookback_days") or max(60, period * 3))
                bars = self._get_cached_bars(symbol_key, lookback_days, now)
                prices = self._prepare_prices(bars, price) if bars is not None else None
                if prices is None or len(prices) < 2:
                    return False, None
                _, middle, _ = self.alert_system.technical_analyzer.calculate_bollinger_bands(
                    prices,
                    period=period,
                    stddev=stddev,
                )
                if middle is None:
                    return False, None
                prev_price = float(prices.iloc[-2])
                if direction in {"above", "up", "upper"}:
                    if prev_price < middle <= price:
                        self.alert_system.update_rule(rule_id, {"last_triggered_at": now.isoformat()})
                        msg = f"📈 {symbol} cruzó por encima de la banda media ({middle:.2f})"
                        return True, msg
                elif direction in {"below", "down", "lower"}:
                    if prev_price > middle >= price:
                        self.alert_system.update_rule(rule_id, {"last_triggered_at": now.isoformat()})
                        msg = f"📉 {symbol} cruzó por debajo de la banda media ({middle:.2f})"
                        return True, msg
                return False, None

        return False, None
