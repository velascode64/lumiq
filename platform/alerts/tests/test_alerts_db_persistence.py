from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lumiq.platform.db.core import DatabaseManager, alerts_state, sa
from lumiq.platform.db.repositories import DbAlertRulesStoreAdapter
from lumiq.platform.alerts.alert_system import AlertSystem


def test_alert_rules_db_adapter_roundtrip_sqlite(tmp_path: Path):
    db_path = tmp_path / "alerts.db"
    manager = DatabaseManager(db_url=f"sqlite+pysqlite:///{db_path}", auto_create=True, echo=False)
    store = DbAlertRulesStoreAdapter(manager)

    payload = {
        "schema_version": 1,
        "updated_at": "2026-02-27T00:00:00Z",
        "rules": [
            {
                "id": "r1",
                "chat_id": 123,
                "symbol": "ETH/USD",
                "type": "percent_drop",
                "threshold": 0.03,
                "active": True,
            }
        ],
    }
    store.write(payload)
    loaded = store.read()

    assert loaded["schema_version"] == 1
    assert len(loaded["rules"]) == 1
    assert loaded["rules"][0]["symbol"] == "ETH/USD"

    store.log_event(alert_id="r1", symbol="ETH/USD", event_type="triggered", payload={"price": 3100})
    loaded_after_event = store.read()
    assert "events" in loaded_after_event
    assert len(loaded_after_event["events"]) == 1
    assert loaded_after_event["events"][0]["event_type"] == "triggered"

    with manager.connect() as conn:
        row = conn.execute(sa.select(alerts_state).where(alerts_state.c.id == 1)).mappings().first()
    assert row is not None


def test_alert_system_persists_rules_in_single_json_table(tmp_path: Path):
    db_path = tmp_path / "alerts_system.db"
    manager = DatabaseManager(db_url=f"sqlite+pysqlite:///{db_path}", auto_create=True, echo=False)
    alerts_store = DbAlertRulesStoreAdapter(manager)

    class _PortfolioStore:
        def __init__(self):
            self._value = {"schema_version": 1, "updated_at": "2026-02-27T00:00:00Z", "positions": []}

        def read(self):
            return self._value

        def write(self, value):
            self._value = value

    with patch("lumiq.platform.alerts.alert_system.AlpacaDataService"), patch(
        "lumiq.platform.alerts.alert_system.TelegramService"
    ):
        system = AlertSystem(
            api_key="k",
            secret_key="s",
            telegram_token="t",
            telegram_chat_id="1",
            alerts_store_override=alerts_store,
            portfolio_store_override=_PortfolioStore(),
        )

    created = system.add_rule(
        {
            "symbol": "ETH/USD",
            "type": "percent_drop",
            "threshold": 0.05,
            "chat_id": 111,
        }
    )
    assert created["symbol"] == "ETH/USD"
    assert created["type"] == "percent_drop"

    rules = system.list_rules()
    assert len(rules) == 1
    assert rules[0]["id"] == created["id"]

    removed = system.remove_rule(created["id"])
    assert removed is True
    assert system.list_rules() == []

    with manager.connect() as conn:
        row = conn.execute(sa.select(alerts_state.c.payload).where(alerts_state.c.id == 1)).scalar_one_or_none()
    assert isinstance(row, dict)
    assert row.get("rules") == []
