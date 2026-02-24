"""
Tests for alert rules persistence and evaluation.
"""

from pathlib import Path
from unittest.mock import Mock, patch

from alerts.storage import alert_rules_store, default_alert_rules


def _make_system():
    with patch("alerts.alert_system.AlpacaDataService") as mock_data:
        with patch("alerts.alert_system.TelegramService") as mock_telegram:
            mock_data.return_value = Mock()
            telegram = Mock()
            telegram.send_message = Mock(return_value=True)
            mock_telegram.return_value = telegram
            from alerts.alert_system import AlertSystem

            return AlertSystem(api_key="k", secret_key="s")


def test_rule_crud(tmp_path: Path):
    system = _make_system()
    store = alert_rules_store(tmp_path / "rules.json")
    store.write(default_alert_rules(now_iso="2024-01-01T00:00:00Z"))
    system._alerts_store = store

    rule = {
        "id": "r1",
        "symbol": "SPY",
        "type": "target_price",
        "target": 500.0,
        "active": True,
    }
    system.add_rule(rule)
    assert len(system.list_rules()) == 1

    updated = system.update_rule("r1", {"active": False})
    assert updated["active"] is False

    removed = system.remove_rule("r1")
    assert removed is True
    assert system.list_rules() == []


def test_evaluate_rules_target_price(tmp_path: Path):
    system = _make_system()
    store = alert_rules_store(tmp_path / "rules.json")
    store.write(default_alert_rules(now_iso="2024-01-01T00:00:00Z"))
    system._alerts_store = store

    system.add_rule({
        "id": "r1",
        "symbol": "SPY",
        "type": "target_price",
        "target": 400.0,
        "active": True,
    })

    system.data_service.get_latest_price = Mock(return_value=410.0)
    messages = system.evaluate_rules()
    assert any("SPY" in m for m in messages)


def test_send_rule_alerts(tmp_path: Path):
    system = _make_system()
    store = alert_rules_store(tmp_path / "rules.json")
    store.write(default_alert_rules(now_iso="2024-01-01T00:00:00Z"))
    system._alerts_store = store

    system.add_rule({
        "id": "r1",
        "symbol": "SPY",
        "type": "target_price",
        "target": 400.0,
        "active": True,
    })

    system.data_service.get_latest_price = Mock(return_value=410.0)
    count = system.send_rule_alerts()
    assert count == 1


def test_evaluate_rules_percent_drop(tmp_path: Path):
    system = _make_system()
    store = alert_rules_store(tmp_path / "rules.json")
    store.write(default_alert_rules(now_iso="2024-01-01T00:00:00Z"))
    system._alerts_store = store

    system.add_rule({
        "id": "r1",
        "symbol": "AAPL",
        "type": "percent_drop",
        "threshold": 5.0,
        "reference_price": 100.0,
        "active": True,
    })

    system.data_service.get_latest_price = Mock(return_value=94.0)
    messages = system.evaluate_rules()
    assert any("AAPL" in m for m in messages)
