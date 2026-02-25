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
    from .strategy_orchestrator import StrategyOrchestrator
    from .agno_trading_agent import create_trading_agent
    from .agno_team_orchestrator import create_alerts_trading_team
    from .alerts.alert_system import AlertSystem
    from .alerts.streaming import AlertStreamManager
    from .portfolio_review import PortfolioReviewScheduler, PortfolioReviewService, WatchlistStore
except ImportError:
    from strategy_orchestrator import StrategyOrchestrator
    from agno_trading_agent import create_trading_agent
    from agno_team_orchestrator import create_alerts_trading_team
    from alerts.alert_system import AlertSystem
    from alerts.streaming import AlertStreamManager
    from portfolio_review import PortfolioReviewScheduler, PortfolioReviewService, WatchlistStore


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
        default_path = Path(__file__).resolve().parent / "strategies" / "live"
        self.orchestrator = StrategyOrchestrator(
            broker_config=broker_config,
            strategies_path=strategies_path or str(default_path),
        )
        self.alert_system: Optional[AlertSystem] = None
        self.stream_manager: Optional[AlertStreamManager] = None
        self.notifier = TelegramNotifier()
        self.watchlist_store = WatchlistStore()
        self.portfolio_review_service: Optional[PortfolioReviewService] = None
        self.portfolio_review_scheduler: Optional[PortfolioReviewScheduler] = None

        try:
            self.alert_system = AlertSystem()
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
            self.portfolio_review_scheduler = PortfolioReviewScheduler(
                review_service=self.portfolio_review_service,
                send_callback=self.notifier.send,
            )
        except Exception as exc:
            logger.warning("PortfolioReview disabled: %s", exc)

        self.agent = create_trading_agent(self.orchestrator)
        self.team = create_alerts_trading_team(self.orchestrator, self.alert_system)

    def start_background(self) -> None:
        if self.stream_manager is not None:
            self.stream_manager.start_in_thread()
        if self.portfolio_review_scheduler is not None:
            self.portfolio_review_scheduler.start_in_thread()

    def stop_background(self) -> None:
        if self.stream_manager is not None:
            self.stream_manager.stop()
        if self.portfolio_review_scheduler is not None:
            self.portfolio_review_scheduler.stop()
