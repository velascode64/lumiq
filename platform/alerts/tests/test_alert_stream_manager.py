"""
Tests for AlertStreamManager rule evaluation.
"""

from datetime import datetime, timedelta, timezone

import pandas as pd

from alerts.streaming.alpaca_stream import AlertStreamManager


class DummyAlertSystem:
    def __init__(self, data_service=None, technical_analyzer=None):
        self.updated = []
        self.data_service = data_service
        self.technical_analyzer = technical_analyzer

    def update_rule(self, rule_id, updates):
        self.updated.append((rule_id, updates))
        return {**updates}


class DummyDataService:
    def __init__(self, bars: pd.DataFrame):
        self._bars = bars

    def get_stock_bars(self, symbol: str, days: int = 90):
        return self._bars


class DummyAnalyzer:
    def __init__(self, rsi=25.0, macd=None, signal=None, bollinger=None):
        self._rsi = rsi
        self._macd = macd
        self._signal = signal
        self._bollinger = bollinger or (None, None, None)

    def calculate_rsi(self, prices, period=None):
        return float(self._rsi)

    def calculate_macd(self, prices, fast=12, slow=26, signal=9):
        return self._macd, self._signal

    def calculate_bollinger_bands(self, prices, period=20, stddev=2.0):
        return self._bollinger


def test_evaluate_target_price_triggers():
    system = DummyAlertSystem()
    manager = AlertStreamManager(system, send_callback=lambda chat_id, msg: None)
    now = datetime.now(timezone.utc)

    rule = {
        "id": "r1",
        "type": "target_price",
        "symbol": "AAPL",
        "target": 100.0,
        "cooldown_seconds": 300,
    }
    triggered, msg = manager._evaluate_rule(rule, price=101.0, now=now)
    assert triggered is True
    assert "AAPL" in msg
    assert system.updated


def test_evaluate_percent_drop_sets_reference():
    system = DummyAlertSystem()
    manager = AlertStreamManager(system, send_callback=lambda chat_id, msg: None)
    now = datetime.now(timezone.utc)

    rule = {
        "id": "r2",
        "type": "percent_drop",
        "symbol": "ETH/USD",
        "threshold": 1.0,
        "reference_price": None,
        "cooldown_seconds": 300,
    }
    triggered, msg = manager._evaluate_rule(rule, price=2000.0, now=now)
    assert triggered is False
    assert msg is None
    assert system.updated
    assert system.updated[0][1]["reference_price"] == 2000.0


def test_evaluate_percent_drop_triggers_and_respects_cooldown():
    system = DummyAlertSystem()
    manager = AlertStreamManager(system, send_callback=lambda chat_id, msg: None)
    now = datetime.now(timezone.utc)

    rule = {
        "id": "r3",
        "type": "percent_drop",
        "symbol": "SPY",
        "threshold": 1.0,
        "reference_price": 100.0,
        "cooldown_seconds": 300,
    }
    triggered, msg = manager._evaluate_rule(rule, price=98.0, now=now)
    assert triggered is True
    assert "SPY" in msg
    assert system.updated[-1][1]["reference_price"] == 98.0

    # within cooldown, should not trigger
    rule["last_triggered_at"] = now.isoformat()
    triggered2, msg2 = manager._evaluate_rule(rule, price=97.0, now=now + timedelta(seconds=60))
    assert triggered2 is False
    assert msg2 is None


def test_evaluate_max_price_triggers():
    system = DummyAlertSystem()
    manager = AlertStreamManager(system, send_callback=lambda chat_id, msg: None)
    now = datetime.now(timezone.utc)

    rule = {
        "id": "r4",
        "type": "max_price",
        "symbol": "QQQ",
        "reference_price": 100.0,
        "cooldown_seconds": 300,
    }
    triggered, msg = manager._evaluate_rule(rule, price=101.0, now=now)
    assert triggered is True
    assert "QQQ" in msg
    assert system.updated[-1][1]["reference_price"] == 101.0


def test_evaluate_min_price_triggers():
    system = DummyAlertSystem()
    manager = AlertStreamManager(system, send_callback=lambda chat_id, msg: None)
    now = datetime.now(timezone.utc)

    rule = {
        "id": "r5",
        "type": "min_price",
        "symbol": "QQQ",
        "reference_price": 100.0,
        "cooldown_seconds": 300,
    }
    triggered, msg = manager._evaluate_rule(rule, price=99.0, now=now)
    assert triggered is True
    assert "QQQ" in msg
    assert system.updated[-1][1]["reference_price"] == 99.0


def test_evaluate_rsi_oversold_triggers():
    bars = pd.DataFrame({"close": [100 + i for i in range(60)]})
    analyzer = DummyAnalyzer(rsi=25.0)
    system = DummyAlertSystem(
        data_service=DummyDataService(bars),
        technical_analyzer=analyzer,
    )
    manager = AlertStreamManager(system, send_callback=lambda chat_id, msg: None)
    now = datetime.now(timezone.utc)

    rule = {
        "id": "r6",
        "type": "rsi_oversold",
        "symbol": "AAPL",
        "threshold": 30.0,
        "period": 14,
        "cooldown_seconds": 300,
    }
    triggered, msg = manager._evaluate_rule(rule, price=95.0, now=now)
    assert triggered is True
    assert "RSI" in msg


def test_evaluate_macd_bullish_cross_triggers():
    bars = pd.DataFrame({"close": [100 + i for i in range(60)]})
    macd = pd.Series([-0.5, 0.2])
    signal = pd.Series([-0.2, -0.1])
    analyzer = DummyAnalyzer(macd=macd, signal=signal)
    system = DummyAlertSystem(
        data_service=DummyDataService(bars),
        technical_analyzer=analyzer,
    )
    manager = AlertStreamManager(system, send_callback=lambda chat_id, msg: None)
    now = datetime.now(timezone.utc)

    rule = {
        "id": "r7",
        "type": "macd_bullish_cross",
        "symbol": "SPY",
        "cooldown_seconds": 300,
    }
    triggered, msg = manager._evaluate_rule(rule, price=101.0, now=now)
    assert triggered is True
    assert "MACD" in msg


def test_evaluate_bollinger_middle_cross_triggers():
    bars = pd.DataFrame({"close": [95.0, 96.0, 97.0, 98.0, 99.0]})
    analyzer = DummyAnalyzer(bollinger=(90.0, 100.0, 110.0))
    system = DummyAlertSystem(
        data_service=DummyDataService(bars),
        technical_analyzer=analyzer,
    )
    manager = AlertStreamManager(system, send_callback=lambda chat_id, msg: None)
    now = datetime.now(timezone.utc)

    rule = {
        "id": "r8",
        "type": "bollinger_middle_cross",
        "symbol": "QQQ",
        "direction": "above",
        "cooldown_seconds": 300,
    }
    triggered, msg = manager._evaluate_rule(rule, price=101.0, now=now)
    assert triggered is True
    assert "banda media" in msg
