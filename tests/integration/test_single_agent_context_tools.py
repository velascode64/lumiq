from __future__ import annotations

import json

from lumiq.agents.agno.members.context_tools import build_context_tools
from lumiq.platform.portfolio.review import WatchlistConfig


class _WatchlistStoreStub:
    def load(self):
        return WatchlistConfig(
            groups={"oil": ["XLE", "APA", "USO"], "ai": ["NVDA"]},
            favorites=["NVDA", "ETH/USD"],
            benchmarks={"stocks": ["SPY"]},
        ).normalize()


class _AlertSystemStub:
    def __init__(self):
        self._active_chat_id = 8101362735

    def get_active_chat_id(self):
        return self._active_chat_id

    def list_rules(self):
        return [
            {"id": "a1", "symbol": "ETH/USD", "type": "percent_drop", "chat_id": 8101362735, "active": True},
            {"id": "a2", "symbol": "NVDA", "type": "target_price", "chat_id": 8101362735, "active": False},
            {"id": "a3", "symbol": "TSLA", "type": "percent_rise", "chat_id": 123, "active": True},
        ]


class _GatewayStub:
    def get_account_status(self, mode="paper"):
        return {
            "mode": mode,
            "portfolio_value": 1000.0,
            "cash": 250.0,
            "equity": 1000.0,
            "buying_power": 500.0,
            "positions_count": 2,
        }

    def list_positions(self, mode="paper"):
        return [{"symbol": "NVDA", "qty": 1.0}]

    def list_open_orders(self, mode="paper"):
        return [{"id": "ord-1", "symbol": "ETH/USD"}]

    def get_market_clock(self, mode="paper"):
        return {"is_open": True}


class _OrchestratorStub:
    def list_running_strategies(self):
        return ["momentum"]

    def get_all_status(self):
        return {"momentum": {"status": "running"}}

    def get_strategy_status(self, strategy_name):
        return {"strategy_name": strategy_name, "status": "running"}


def test_context_tools_expose_watchlist_alerts_execution_and_strategy_context():
    tools = build_context_tools(
        orchestrator=_OrchestratorStub(),
        alert_system=_AlertSystemStub(),
        watchlist_store=_WatchlistStoreStub(),
        live_gateway=_GatewayStub(),
    )
    names = [tool.name for tool in tools]

    assert "get_watchlist_context" in names
    assert "get_followed_tickers" in names
    assert "get_alerts_context" in names
    assert "get_user_execution_context" in names
    assert "get_user_portfolio_value" in names
    assert "get_user_strategy_context" in names


def test_get_watchlist_context_returns_real_groups_and_followed_tickers():
    tools = {
        tool.name: tool
        for tool in build_context_tools(watchlist_store=_WatchlistStoreStub())
    }

    payload = json.loads(tools["get_watchlist_context"].entrypoint())

    assert payload["followed_tickers_count"] == 4
    assert payload["groups"][0]["name"] == "ai"
    assert any(group["name"] == "oil" for group in payload["groups"])


def test_get_alerts_context_filters_current_chat_scope_and_symbol():
    tools = {
        tool.name: tool
        for tool in build_context_tools(alert_system=_AlertSystemStub())
    }

    payload = json.loads(tools["get_alerts_context"].entrypoint(symbol="ETH/USD"))

    assert payload["chat_id"] == 8101362735
    assert payload["count"] == 1
    assert payload["rules"][0]["id"] == "a1"
