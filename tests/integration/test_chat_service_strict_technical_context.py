from __future__ import annotations

import pytest

from lumiq.app.services.chat_service import ChatService
from lumiq.platform.db.core import DatabaseManager
from lumiq.platform.db.repositories import DbChatContextRepository


class _EmptyBars:
    empty = True


class _DataServiceStub:
    _valid = {
        "NVDA",
        "AAPL",
        "QQQ",
        "SPY",
        "GOOG",
        "GOOGL",
        "META",
        "ETH/USD",
        "BTC/USD",
    }

    def get_latest_price(self, symbol: str):
        ticker = (symbol or "").strip().upper()
        return 100.0 if ticker in self._valid else None

    def get_stock_bars(self, symbol: str, days: int = 5):
        return _EmptyBars()


class _AlertSystemStub:
    def __init__(self):
        self.data_service = _DataServiceStub()
        self.active_chat_id = None

    def set_active_chat_id(self, chat_id: int) -> None:
        self.active_chat_id = int(chat_id)


class _TeamMustNotRun:
    def run(self, *_args, **_kwargs):
        raise AssertionError("Team should not be called for missing-symbol technical clarification.")


class _RuntimeStub:
    def __init__(self, chat_context_repo):
        self.chat_context_repo = chat_context_repo
        self.coordination_repo = None
        self.memory_repo = None
        self.alert_system = _AlertSystemStub()
        self.watchlist_store = None
        self.portfolio_review_scheduler = None
        self.news_scheduler = None
        self.orchestrator = None
        self.live_trading_agent = None
        self.team = _TeamMustNotRun()
        self.agent = None


def _build_chat_repo(tmp_path):
    db_path = tmp_path / "chat_context.db"
    manager = DatabaseManager(db_url=f"sqlite+pysqlite:///{db_path}", auto_create=True, echo=False)
    return DbChatContextRepository(manager)


@pytest.mark.integration
def test_symbol_extraction_filters_narrative_words(tmp_path):
    chat_repo = _build_chat_repo(tmp_path)
    service = ChatService(_RuntimeStub(chat_repo))
    symbols = service._extract_symbols(
        "revisa cuantas veces ha caido NVDA despues de earnings y soporte"
    )
    assert symbols == ["NVDA"]


@pytest.mark.integration
def test_technical_message_without_symbol_returns_deterministic_clarification(tmp_path):
    chat_repo = _build_chat_repo(tmp_path)
    service = ChatService(_RuntimeStub(chat_repo))

    response = service.handle_chat(
        chat_id=8101362735,
        user_id=8101362735,
        text="revisa RSI y soporte para ver si hay rebote",
    )

    assert response.text == "Which symbol should I analyze? (e.g., NVDA, ETH/USD)."
    state = chat_repo.get_chat_state(8101362735) or {}
    assert state.get("active_symbol") in (None, "")


@pytest.mark.integration
def test_invalid_symbol_does_not_pollute_active_symbol(tmp_path):
    chat_repo = _build_chat_repo(tmp_path)
    service = ChatService(_RuntimeStub(chat_repo))

    service._persist_chat_state(
        chat_id=8101362735,
        user_id=8101362735,
        text="analiza NVDA con RSI",
    )
    before = chat_repo.get_chat_state(8101362735) or {}
    assert before.get("active_symbol") == "NVDA"

    service._persist_chat_state(
        chat_id=8101362735,
        user_id=8101362735,
        text="revisa cuantas veces ha caido EVISA despues de earnings",
    )
    after = chat_repo.get_chat_state(8101362735) or {}
    assert after.get("active_symbol") == "NVDA"


@pytest.mark.integration
def test_technical_context_prefix_does_not_carry_stale_symbol_without_current_symbol(tmp_path):
    chat_repo = _build_chat_repo(tmp_path)
    service = ChatService(_RuntimeStub(chat_repo))

    service._persist_chat_state(
        chat_id=8101362735,
        user_id=8101362735,
        text="analiza NVDA con RSI",
    )
    prefix = service._context_prefix(8101362735, "revisa RSI y soporte de hoy")
    assert "active_symbol:" not in prefix
