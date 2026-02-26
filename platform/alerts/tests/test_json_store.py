"""
Tests for JSON persistence stores.
"""

from pathlib import Path

from alerts.storage import (
    alert_rules_store,
    default_alert_rules,
    default_portfolio,
    portfolio_store,
)


def test_portfolio_store_write_and_read(tmp_path: Path):
    path = tmp_path / "portfolio.json"
    store = portfolio_store(path)

    data = default_portfolio(now_iso="2024-01-01T00:00:00Z")
    data["positions"] = [{"symbol": "SPY", "qty": 10, "avg_price": 450.0}]
    data["cash"] = 1000.0

    store.write(data)
    loaded = store.read()

    assert loaded["schema_version"] == 1
    assert loaded["positions"][0]["symbol"] == "SPY"
    assert loaded["cash"] == 1000.0


def test_alert_rules_store_write_and_read(tmp_path: Path):
    path = tmp_path / "alert_rules.json"
    store = alert_rules_store(path)

    data = default_alert_rules(now_iso="2024-01-01T00:00:00Z")
    data["rules"] = [
        {"id": "r1", "symbol": "SPY", "type": "percent_drop", "threshold": 5.0, "active": True},
        {"id": "r2", "symbol": "AAPL", "type": "target_price", "target": 180.0, "active": True},
    ]

    store.write(data)
    loaded = store.read()

    assert loaded["schema_version"] == 1
    assert len(loaded["rules"]) == 2
    assert loaded["rules"][0]["id"] == "r1"


def test_store_creates_default_when_missing(tmp_path: Path):
    path = tmp_path / "missing.json"
    store = portfolio_store(path)

    loaded = store.read()

    assert loaded["schema_version"] == 1
    assert loaded["positions"] == []
