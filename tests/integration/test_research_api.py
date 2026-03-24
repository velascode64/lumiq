from __future__ import annotations

from fastapi.testclient import TestClient

from lumiq.app import main as app_main


class _FakeResearchWorkflow:
    def run(self, ticker: str, start_date: str, end_date: str):
        return {
            "company_of_interest": ticker,
            "start_date": start_date,
            "end_date": end_date,
            "final_trade_decision": "BUY",
        }


class _FakeOrchestratorCore:
    @staticmethod
    def list_strategies():
        return {}


class _FakeOrchestrator:
    def __init__(self):
        self.core = _FakeOrchestratorCore()

    @staticmethod
    def list_running_strategies():
        return []

    @staticmethod
    def start_strategy(*args, **kwargs):
        return {}

    @staticmethod
    def stop_strategy(*args, **kwargs):
        return {}

    @staticmethod
    def kill_strategy(*args, **kwargs):
        return {}

    @staticmethod
    def stop_all():
        return {}

    @staticmethod
    def get_all_status():
        return {}

    @staticmethod
    def get_strategy_status(_strategy_name: str):
        return {}

    @staticmethod
    def update_parameters(*args, **kwargs):
        return {}


class _FakeRuntime:
    def __init__(self, strategies_path=None):
        self.orchestrator = _FakeOrchestrator()
        self.alert_system = None
        self.team = object()
        self.research_workflow = _FakeResearchWorkflow()

    @staticmethod
    def start_background():
        return None

    @staticmethod
    def stop_background():
        return None


class _FakeReply:
    def __init__(self, text: str = "ok", parse_mode: str | None = None):
        self.text = text
        self.parse_mode = parse_mode


class _FakeChatService:
    def __init__(self, runtime):
        self.runtime = runtime

    @staticmethod
    def handle_text(chat_id: int, user_id: int, text: str):
        return _FakeReply(text=f"{chat_id}:{user_id}:{text}")


def test_research_endpoint_happy_path(monkeypatch):
    monkeypatch.setattr(app_main, "CoreRuntime", _FakeRuntime)
    monkeypatch.setattr(app_main, "ChatService", _FakeChatService)

    client = TestClient(app_main.create_app())
    response = client.post(
        "/api/research",
        json={
            "ticker": "NVDA",
            "start_date": "2026-03-01",
            "end_date": "2026-03-23",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["company_of_interest"] == "NVDA"
    assert payload["result"]["final_trade_decision"] == "BUY"


def test_research_endpoint_rejects_invalid_date_range(monkeypatch):
    monkeypatch.setattr(app_main, "CoreRuntime", _FakeRuntime)
    monkeypatch.setattr(app_main, "ChatService", _FakeChatService)

    client = TestClient(app_main.create_app())
    response = client.post(
        "/api/research",
        json={
            "ticker": "NVDA",
            "start_date": "2026-03-23",
            "end_date": "2026-03-01",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "end_date must be >= start_date"
