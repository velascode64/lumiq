#!/usr/bin/env python3
"""
CLI report for realized PnL based on Alpaca fill activities.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, Optional

from alpaca_pnl import get_realized_pnl_summary


def _build_broker_config(mode: str) -> Dict[str, Any]:
    api_key = os.getenv("ALPACA_API_KEY") or os.getenv("ALPACA_KEY_ID")
    api_secret = os.getenv("ALPACA_API_SECRET") or os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not api_secret:
        raise RuntimeError("Missing ALPACA_API_KEY/ALPACA_API_SECRET in environment")

    config: Dict[str, Any] = {
        "API_KEY": api_key,
        "API_SECRET": api_secret,
        "IS_PAPER": mode.lower() != "live",
    }

    base_url = os.getenv("ALPACA_BASE_URL") or os.getenv("ALPACA_API_BASE_URL")
    if base_url:
        config["BASE_URL"] = base_url

    return config


def main() -> int:
    parser = argparse.ArgumentParser(description="Alpaca realized PnL report")
    parser.add_argument("--period", default="weekly", choices=["daily", "weekly", "monthly"])
    parser.add_argument("--strategy", default=None, help="Strategy name to filter by client_order_id")
    parser.add_argument("--mode", default="paper", choices=["paper", "live"])
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args()

    broker_config = _build_broker_config(args.mode)
    summary = get_realized_pnl_summary(
        broker_config=broker_config,
        period=args.period,
        strategy_name=args.strategy,
    )

    if args.pretty:
        print(json.dumps(summary, indent=2))
    else:
        print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
