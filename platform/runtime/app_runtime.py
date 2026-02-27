"""
Shared runtime bootstrap for the Lumiq core server.

Keeps orchestrator/alerts/team instances in one place so both API endpoints and
background services share the same in-memory state.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import requests

try:
    from ...lumibot.core.orchestration.strategy_orchestrator import StrategyOrchestrator
    from ...agents.agno.members.trading_agent_compat import create_trading_agent
    from ...agents.agno.members.live_trading_agent import create_live_trading_agent
    from ...agents.agno.team.orchestrator import create_alerts_trading_team
    from ..alerts.alert_system import AlertSystem
    from ..alerts.streaming import AlertStreamManager
    from ..portfolio.review import PortfolioReviewScheduler, PortfolioReviewService, WatchlistStore
    from ..news.news_monitor import WatchlistNewsMonitorService, WatchlistNewsScheduler
    from ...agents.agno.members.news_agent import create_news_agent, run_news_agent_message
    from ..db import (
        create_database_manager_from_env,
        create_agno_postgres_db_from_env,
        DbWatchlistRepository,
        DbAlertRulesStoreAdapter,
        DbCoordinationRepository,
        DbMemoryRepository,
        DbChatContextRepository,
    )
except ImportError:
    from lumibot.core.orchestration.strategy_orchestrator import StrategyOrchestrator
    from agents.agno.members.trading_agent_compat import create_trading_agent
    from agents.agno.members.live_trading_agent import create_live_trading_agent
    from agents.agno.team.orchestrator import create_alerts_trading_team
    from platform.alerts.alert_system import AlertSystem
    from platform.alerts.streaming import AlertStreamManager
    from platform.portfolio.review import PortfolioReviewScheduler, PortfolioReviewService, WatchlistStore
    from platform.news.news_monitor import WatchlistNewsMonitorService, WatchlistNewsScheduler
    from agents.agno.members.news_agent import create_news_agent, run_news_agent_message
    try:
        from platform.db import (
            create_database_manager_from_env,
            create_agno_postgres_db_from_env,
            DbWatchlistRepository,
            DbAlertRulesStoreAdapter,
            DbCoordinationRepository,
            DbMemoryRepository,
            DbChatContextRepository,
        )
    except ImportError:
        create_database_manager_from_env = None  # type: ignore
        DbWatchlistRepository = None  # type: ignore
        DbAlertRulesStoreAdapter = None  # type: ignore
        DbCoordinationRepository = None  # type: ignore
        DbMemoryRepository = None  # type: ignore
        DbChatContextRepository = None  # type: ignore


logger = logging.getLogger(__name__)


def bool_from_env(var_name: str, default: bool = True) -> bool:
    value = os.getenv(var_name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def require_env(var_name: str) -> str:
    value = os.getenv(var_name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {var_name}")
    return value


def build_broker_config() -> Dict[str, Any]:
    api_key = require_env("ALPACA_API_KEY")
    api_secret = os.getenv("ALPACA_API_SECRET", "").strip() or require_env("ALPACA_SECRET_KEY")
    is_paper = bool_from_env("ALPACA_IS_PAPER", default=True)

    broker_config: Dict[str, Any] = {
        "API_KEY": api_key,
        "API_SECRET": api_secret,
        "IS_PAPER": is_paper,
        "PAPER": is_paper,
    }
    if os.getenv("ALPACA_BASE_URL"):
        broker_config["BASE_URL"] = os.getenv("ALPACA_BASE_URL")
    return broker_config


class TelegramNotifier:
    """Thin sender used by alert streams in API mode."""

    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.base_url = f"https://api.telegram.org/bot{self.token}" if self.token else ""

    def send(self, chat_id: int, text: str) -> None:
        if not self.token:
            logger.warning("TELEGRAM_BOT_TOKEN not configured, skipping alert notification")
            return

        chunks = [text[i : i + 3900] for i in range(0, len(text), 3900)] or ["(empty)"]
        for chunk in chunks:
            payload = {"chat_id": chat_id, "text": chunk}
            response = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=20)
            response.raise_for_status()
            data = response.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram API error: {data}")


class CoreRuntime:
    """Container for long-lived core services."""

    def __init__(self, strategies_path: Optional[str] = None):
        broker_config = build_broker_config()
        self.db = create_database_manager_from_env() if create_database_manager_from_env is not None else None
        self.agno_team_db = create_agno_postgres_db_from_env() if create_agno_postgres_db_from_env is not None else None
        self.coordination_repo = DbCoordinationRepository(self.db) if (self.db and DbCoordinationRepository is not None) else None
        self.memory_repo = DbMemoryRepository(self.db) if (self.db and DbMemoryRepository is not None) else None
        self.chat_context_repo = DbChatContextRepository(self.db) if (self.db and DbChatContextRepository is not None) else None
        self.alert_rules_store_adapter = DbAlertRulesStoreAdapter(self.db) if (self.db and DbAlertRulesStoreAdapter is not None) else None
        watchlist_repo = DbWatchlistRepository(self.db) if (self.db and DbWatchlistRepository is not None) else None
        default_path = Path(__file__).resolve().parents[2] / "lumibot" / "strategies" / "live"
        self.orchestrator = StrategyOrchestrator(
            broker_config=broker_config,
            strategies_path=strategies_path or str(default_path),
        )
        self.alert_system: Optional[AlertSystem] = None
        self.stream_manager: Optional[AlertStreamManager] = None
        self.notifier = TelegramNotifier()
        self.watchlist_store = WatchlistStore(repo=watchlist_repo)
        self.portfolio_review_service: Optional[PortfolioReviewService] = None
        self.portfolio_review_scheduler: Optional[PortfolioReviewScheduler] = None
        self.news_monitor_service: Optional[WatchlistNewsMonitorService] = None
        self.news_scheduler: Optional[WatchlistNewsScheduler] = None
        self.news_agent = None

        try:
            self.alert_system = AlertSystem(
                alerts_store_override=self.alert_rules_store_adapter,
            )
        except Exception as exc:
            logger.warning("AlertSystem disabled: %s", exc)

        if self.alert_system is not None:
            self.stream_manager = AlertStreamManager(
                self.alert_system,
                send_callback=self.notifier.send,
            )
            self.alert_system.set_stream_manager(self.stream_manager)

        try:
            data_service = getattr(self.alert_system, "data_service", None) if self.alert_system is not None else None
            self.portfolio_review_service = PortfolioReviewService(
                broker_config=broker_config,
                watchlist_store=self.watchlist_store,
                data_service=data_service,
            )
            def _persist_portfolio_report(report_kind: str, text: str, source: str, group_name: Optional[str], chat_id: Optional[int]) -> None:
                if self.coordination_repo is None:
                    return
                scope_type = "group" if group_name else "portfolio"
                scope_value = group_name
                title = f"portfolio_{report_kind}"
                self.coordination_repo.create_report(
                    report_type=report_kind,
                    scope_type=scope_type,
                    scope_value=scope_value,
                    chat_id=chat_id,
                    title=title,
                    summary=text[:8000],
                    payload={"source": source, "group_name": group_name},
                    created_by=f"{source or 'scheduler'}:portfolio",
                )
            self.portfolio_review_scheduler = PortfolioReviewScheduler(
                review_service=self.portfolio_review_service,
                send_callback=self.notifier.send,
                persist_callback=_persist_portfolio_report,
            )
        except Exception as exc:
            logger.warning("PortfolioReview disabled: %s", exc)

        try:
            self.news_monitor_service = WatchlistNewsMonitorService(watchlist_store=self.watchlist_store)
            self.news_agent = create_news_agent(self.news_monitor_service)
            def _news_analyze_callback(group_name: Optional[str]) -> str:
                if self.news_agent is None:
                    return self.news_monitor_service.generate_preopen_digest_text(group_name=group_name)
                scope = f" del grupo {group_name}" if group_name else " de mi watchlist"
                msg = (
                    "Genera el digest de noticias pre-apertura para Telegram.\n"
                    "Usa tools reales para leer noticias y clasificalas por relevancia.\n"
                    f"Analiza noticias{scope} de las ultimas 18 horas.\n"
                    "Formato: Resumen, Alta prioridad, Impacto en posiciones, Impacto en watchlist sin posicion, Ruido, Tickers a revisar primero, Sugerencias."
                )
                return run_news_agent_message(self.news_agent, msg, user_id="cron-news", session_id=f"news-preopen-{group_name or 'all'}")
            def _persist_news_digest(text: str, source: str, group_name: Optional[str], chat_id: Optional[int]) -> None:
                if self.coordination_repo is None:
                    return
                self.coordination_repo.create_report(
                    report_type="news_preopen",
                    scope_type="group" if group_name else "watchlist",
                    scope_value=group_name,
                    chat_id=chat_id,
                    title="watchlist_news_digest",
                    summary=text[:8000],
                    payload={"source": source, "group_name": group_name},
                    created_by=f"{source or 'scheduler'}:news",
                )
            self.news_scheduler = WatchlistNewsScheduler(
                service=self.news_monitor_service,
                send_callback=self.notifier.send,
                analyze_callback=_news_analyze_callback,
                persist_callback=_persist_news_digest,
            )
        except Exception as exc:
            logger.warning("WatchlistNewsMonitor disabled: %s", exc)
        self.live_trading_agent = create_live_trading_agent(self.orchestrator.broker_config)
        self.agent = create_trading_agent(self.orchestrator)
        self.team = create_alerts_trading_team(
            self.orchestrator,
            self.alert_system,
            self.news_monitor_service,
            memory_repo=self.memory_repo,
            coordination_repo=self.coordination_repo,
            agno_db=self.agno_team_db,
        )

    def start_background(self) -> None:
        if self.stream_manager is not None:
            self.stream_manager.start_in_thread()
        if self.portfolio_review_scheduler is not None:
            self.portfolio_review_scheduler.start_in_thread()
        if self.news_scheduler is not None:
            self.news_scheduler.start_in_thread()

    def stop_background(self) -> None:
        if self.stream_manager is not None:
            self.stream_manager.stop()
        if self.portfolio_review_scheduler is not None:
            self.portfolio_review_scheduler.stop()
        if self.news_scheduler is not None:
            self.news_scheduler.stop()
