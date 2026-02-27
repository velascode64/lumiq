from __future__ import annotations

import pytest

from lumiq.agents.agno.team import orchestrator as team_orchestrator
from lumiq.agents.agno.members import (
    live_trading_agent as live_trading_member,
    news_agent as news_member,
    shared_memory_tools as shared_tools_member,
    strategy_ops_agent as strategy_ops_member,
    technical_agent as technical_member,
)


class _DummyAgent:
    def __init__(self, name: str):
        self.name = name
        self.tools = []


class _DummyTeam:
    def __init__(self, members=None, name: str = "TradingAlertTeam", **kwargs):
        self.members = kwargs.get("members") or []
        if members is not None:
            self.members = members
        self.name = name


@pytest.mark.integration
def test_team_configuration_excludes_alert_analyst(monkeypatch):
    monkeypatch.setattr(team_orchestrator, "_resolve_model", lambda: object())
    monkeypatch.setattr(team_orchestrator, "Team", _DummyTeam)

    monkeypatch.setattr(strategy_ops_member, "create_strategy_ops_agent", lambda _orchestrator: _DummyAgent("LumibotStrategyOpsAssistant"))
    monkeypatch.setattr(live_trading_member, "create_live_trading_agent", lambda _broker_config: _DummyAgent("LiveTradingAgent"))
    monkeypatch.setattr(technical_member, "create_technical_agent", lambda _alert_system: _DummyAgent("TechnicalAnalyst"))
    monkeypatch.setattr(news_member, "create_news_agent", lambda _news_service: _DummyAgent("NewsAnalyst"))
    monkeypatch.setattr(shared_tools_member, "build_shared_memory_tools", lambda **_kwargs: [])

    team = team_orchestrator.create_alerts_trading_team(
        orchestrator=object(),
        alert_system=object(),
        news_service=object(),
        memory_repo=None,
        coordination_repo=None,
        agno_db=None,
    )

    assert team is not None
    member_ids = {m.name.lower() for m in (team.members or [])}
    assert "alertanalyst" not in member_ids
    assert {"technicalanalyst", "newsanalyst", "livetradingagent", "lumibotstrategyopsassistant"} <= member_ids
