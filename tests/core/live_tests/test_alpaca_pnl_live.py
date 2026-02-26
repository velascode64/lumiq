from __future__ import annotations

import os

import pytest

from alpaca_pnl import get_realized_pnl_summary


def _require_env() -> tuple[str, str]:
    api_key = os.getenv("ALPACA_API_KEY")
    api_secret = os.getenv("ALPACA_API_SECRET") or os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not api_secret:
        pytest.skip("Missing ALPACA_API_KEY/ALPACA_API_SECRET for live Alpaca test")
    return api_key, api_secret


@pytest.mark.live
def test_pnl_daily_portfolio_history_paper():
    api_key, api_secret = _require_env()
    broker_config = {
        "API_KEY": api_key,
        "API_SECRET": api_secret,
        "IS_PAPER": True,
    }
    base_url = os.getenv("ALPACA_BASE_URL")
    if base_url:
        broker_config["BASE_URL"] = base_url

    summary = get_realized_pnl_summary(
        broker_config=broker_config,
        period="daily",
        strategy_name=None,
    )

    assert summary["period"] == "daily"
    assert "total_realized_pnl" in summary
    assert "pnl_source" in summary
