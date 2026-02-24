#!/usr/bin/env python3
"""
Run the Telegram frontend client that talks to the Lumiq Core API.
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


def _load_env() -> None:
    if load_dotenv is None:
        return
    here = Path(__file__).resolve().parent
    for env_path in (here / ".env", here.parent / "core" / ".env", here.parent / ".env"):
        if env_path.exists():
            load_dotenv(env_path)


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Telegram client for Lumiq Core API")
    parser.add_argument("--api-base-url", default=os.getenv("LUMIQ_CORE_API_URL", "http://127.0.0.1:8000"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    _load_env()

    try:
        from .http_telegram_bot import ApiTelegramBot
    except ImportError:
        from http_telegram_bot import ApiTelegramBot

    token = _require_env("TELEGRAM_BOT_TOKEN")
    logging.getLogger(__name__).info("Starting Telegram frontend client -> %s", args.api_base_url)
    bot = ApiTelegramBot(telegram_token=token, core_api_base_url=args.api_base_url)
    bot.run()


if __name__ == "__main__":
    main()
