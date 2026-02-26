from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

CORE_DIR = Path(__file__).resolve().parents[1]
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from alpaca_pnl import get_realized_pnl_summary


def _make_activity(
    symbol: str,
    side: str,
    qty: float,
    price: float,
    fee: float = 0.0,
    client_order_id: str | None = None,
    order_id: str | None = None,
) -> dict:
    return {
        "symbol": symbol,
        "side": side,
        "qty": str(qty),
        "price": str(price),
        "fee": str(fee),
        "client_order_id": client_order_id,
        "order_id": order_id,
    }


def _patch_alpaca(monkeypatch, activities):
    class FakeApi:
        def __init__(self, activities):
            self._activities = activities

        def get_activities(self, **kwargs):
            return list(self._activities)

    class FakeAlpaca:
        def __init__(self, broker_config):
            self.api = FakeApi(activities)

    monkeypatch.setattr("alpaca_pnl.Alpaca", FakeAlpaca)


def test_realized_pnl_with_strategy_filter(monkeypatch):
    activities = [
        _make_activity("AAPL", "buy", 1, 100, fee=0.5, client_order_id="foo-1"),
        _make_activity("AAPL", "sell", 1, 110, fee=0.5, client_order_id="foo-2"),
        _make_activity("BTCUSD", "sell", 2, 50, client_order_id="bar-1"),
        _make_activity("BTCUSD", "buy", 1, 40, client_order_id="bar-2"),
    ]
    _patch_alpaca(monkeypatch, activities)

    summary = get_realized_pnl_summary(
        broker_config={"API_KEY": "k", "API_SECRET": "s", "IS_PAPER": True},
        period="weekly",
        strategy_name="foo",
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 8, tzinfo=timezone.utc),
    )

    assert summary["strategy_filter"]["applied"] is True
    assert summary["strategy_filter"]["matched_orders"] == 2
    assert pytest.approx(summary["total_realized_pnl"], rel=1e-6) == 10.0
    assert pytest.approx(summary["total_fees"], rel=1e-6) == 1.0
    assert "AAPL" in summary["per_symbol"]
    assert "BTCUSD" not in summary["per_symbol"]


def test_realized_pnl_without_client_order_ids(monkeypatch):
    activities = [
        _make_activity("ETHUSD", "buy", 2, 100),
        _make_activity("ETHUSD", "sell", 1, 115),
    ]
    _patch_alpaca(monkeypatch, activities)

    summary = get_realized_pnl_summary(
        broker_config={"API_KEY": "k", "API_SECRET": "s", "IS_PAPER": True},
        period="daily",
        strategy_name="ETHMomentumLive",
        start=datetime(2024, 2, 1, tzinfo=timezone.utc),
        end=datetime(2024, 2, 2, tzinfo=timezone.utc),
    )

    assert summary["strategy_filter"]["applied"] is False
    assert pytest.approx(summary["total_realized_pnl"], rel=1e-6) == 15.0
    assert summary["total_fills"] == 2
