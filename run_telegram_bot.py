#!/usr/bin/env python3
"""
Root entrypoint to run the conversational Telegram trading bot (direct bot mode).

This preserves the previous direct Telegram bot behavior while using the reorganized
adapter/orchestration import paths from the repo root.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


def _load_env() -> None:
    if load_dotenv is None:
        return
    root_dir = Path(__file__).resolve().parent
    candidates = [root_dir / ".env", root_dir.parent / ".env"]
    for env_path in candidates:
        if env_path.exists():
            load_dotenv(env_path)


def _require_env(var_name: str) -> str:
    value = os.getenv(var_name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {var_name}")
    return value


def _bool_from_env(var_name: str, default: bool = True) -> bool:
    value = os.getenv(var_name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Lumibot conversational Telegram bot")
    parser.add_argument(
        "--strategies-path",
        default=str(Path(__file__).resolve().parent / "lumibot" / "strategies" / "live"),
        help="Directory containing strategy python files",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    _load_env()
    script_dir = Path(__file__).resolve().parent
    repo_parent = script_dir.parent
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != script_dir]
    if str(repo_parent) not in sys.path:
        sys.path.insert(0, str(repo_parent))

    try:
        from lumiq.lumibot.core.orchestration.strategy_orchestrator import StrategyOrchestrator
    except ImportError:  # pragma: no cover
        from lumibot.core.orchestration.strategy_orchestrator import StrategyOrchestrator

    try:
        from lumiq.app.adapters.telegram.inbound import TradingTelegramBot
    except ImportError:  # pragma: no cover
        from app.adapters.telegram.inbound import TradingTelegramBot

    telegram_token = _require_env("TELEGRAM_BOT_TOKEN")
    api_key = _require_env("ALPACA_API_KEY")
    api_secret = _require_env("ALPACA_API_SECRET")
    is_paper = _bool_from_env("ALPACA_IS_PAPER", default=True)

    broker_config = {
        "API_KEY": api_key,
        "API_SECRET": api_secret,
        "IS_PAPER": is_paper,
        "PAPER": is_paper,
    }
    if os.getenv("ALPACA_BASE_URL"):
        broker_config["BASE_URL"] = os.getenv("ALPACA_BASE_URL")

    orchestrator = StrategyOrchestrator(broker_config=broker_config, strategies_path=args.strategies_path)
    available = orchestrator.list_available_strategies()

    print("Trading bot bootstrap complete")
    print(f"Discovered strategies: {len(available)}")
    for strategy in available:
        print(f" - {strategy}")
    print("Starting Telegram polling...")

    bot = TradingTelegramBot(token=telegram_token, orchestrator=orchestrator)
    bot.run()


if __name__ == "__main__":
    main()
