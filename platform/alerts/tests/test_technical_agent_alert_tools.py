from __future__ import annotations

import json
from pathlib import Path
import sys
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lumiq.agents.agno.members.technical_agent import build_technical_tools
from lumiq.platform.alerts.alert_system import AlertSystem
from lumiq.platform.db.core import DatabaseManager, alerts, sa
from lumiq.platform.db.repositories import DbAlertRulesStoreAdapter


def _tool_entrypoint(tools, name: str):
    for tool in tools:
        if getattr(tool, "name", None) == name:
            return getattr(tool, "entrypoint")
    raise AssertionError(f"Tool not found: {name}")


def test_technical_agent_alert_crud_tools_persist_to_db(tmp_path: Path):
    db_path = tmp_path / "technical_tools_alerts.db"
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
        alert_system = AlertSystem(
            api_key="k",
            secret_key="s",
            telegram_token="t",
            telegram_chat_id="1",
            alerts_store_override=alerts_store,
            portfolio_store_override=_PortfolioStore(),
        )

    tools = build_technical_tools(alert_system)
    create_drop = _tool_entrypoint(tools, "create_percent_drop_alert")
    list_alerts = _tool_entrypoint(tools, "list_alerts")
    remove_alert = _tool_entrypoint(tools, "remove_alert")

    created = json.loads(create_drop(symbol="NVDA", percent=2.0, chat_id=8101362735, cooldown_seconds=120))
    assert created["symbol"] == "NVDA"
    assert created["type"] == "percent_drop"
    assert float(created["threshold"]) == 2.0
    assert int(created["chat_id"]) == 8101362735

    listed = json.loads(list_alerts(chat_id=8101362735))
    assert listed["count"] == 1
    assert listed["rules"][0]["id"] == created["id"]

    removed = json.loads(remove_alert(rule_id=created["id"]))
    assert removed["removed"] is True

    listed_after = json.loads(list_alerts(chat_id=8101362735))
    assert listed_after["count"] == 0

    with manager.connect() as conn:
        count = conn.execute(sa.select(sa.func.count()).select_from(alerts)).scalar_one()
    assert int(count) == 0
