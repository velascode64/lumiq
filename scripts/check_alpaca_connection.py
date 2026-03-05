#!/usr/bin/env python3
"""
Simple Alpaca connectivity check (REST only, no websocket stream).

Use this script to validate keys/environment before running Lumiq/Lumibot.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta

from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetPortfolioHistoryRequest


def _mask(value: str) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-2:]}"


def _load_env_file(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Alpaca REST connectivity")
    parser.add_argument("--env-file", default=".env", help="Optional env file to load first (default: .env)")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper", help="Trading mode")
    args = parser.parse_args()

    _load_env_file(args.env_file)

    api_key = (os.getenv("ALPACA_API_KEY") or "").strip()
    api_secret = ((os.getenv("ALPACA_API_SECRET") or os.getenv("ALPACA_SECRET_KEY") or "")).strip()

    if not api_key or not api_secret:
        print("ERROR: Missing ALPACA_API_KEY / ALPACA_API_SECRET")
        return 2

    is_paper = args.mode == "paper"
    print("Alpaca connection check")
    print(f"- mode: {'paper' if is_paper else 'live'}")
    print(f"- key: {_mask(api_key)}")
    print(f"- secret: {_mask(api_secret)}")

    try:
        client = TradingClient(api_key=api_key, secret_key=api_secret, paper=is_paper)

        account = client.get_account()
        print("OK: get_account")
        print(f"  status={account.status} trading_blocked={account.trading_blocked}")
        print(f"  cash={account.cash} equity={account.equity} buying_power={account.buying_power}")

        clock = client.get_clock()
        print("OK: get_clock")
        print(f"  is_open={clock.is_open} next_open={clock.next_open} next_close={clock.next_close}")

        end_date = date.today()
        start_date = end_date - timedelta(days=1)
        req = GetPortfolioHistoryRequest(
            timeframe="1D",
            date_start=start_date,
            date_end=end_date,
        )
        history = client.get_portfolio_history(req)
        points = len(getattr(history, "equity", []) or [])
        print("OK: get_portfolio_history")
        print(f"  points={points}")

        print("\nSUCCESS: Alpaca REST is reachable and credentials are valid.")
        return 0

    except APIError as exc:
        print(f"ALPACA API ERROR: {exc}")
        return 1
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
