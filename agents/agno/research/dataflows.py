from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from agno.tools import tool


def _ensure_tradingagents_on_path() -> None:
    root = Path(__file__).resolve().parents[4] / "trading-agents" / "TradingAgents"
    if root.exists() and str(root) not in sys.path:
        sys.path.append(str(root))


_ensure_tradingagents_on_path()

from tradingagents.default_config import DEFAULT_CONFIG  # type: ignore  # noqa: E402
from tradingagents.dataflows.config import set_config  # type: ignore  # noqa: E402
from tradingagents.dataflows.interface import route_to_vendor  # type: ignore  # noqa: E402


def configure_tradingagents_dataflows() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[3]
    cache_dir = root / "reports" / "research_data_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    config = dict(DEFAULT_CONFIG)
    config["project_dir"] = str(root)
    config["results_dir"] = str(root / "reports" / "research_results")
    config["data_cache_dir"] = str(cache_dir)
    set_config(config)
    return config


@tool
def get_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    """Retrieve stock price data (OHLCV) for a ticker symbol."""
    return route_to_vendor("get_stock_data", symbol, start_date, end_date)


@tool
def get_indicators(symbol: str, indicator: str, curr_date: str, look_back_days: int = 30) -> str:
    """Retrieve technical indicators for a ticker symbol."""
    return route_to_vendor("get_indicators", symbol, indicator, curr_date, look_back_days)


@tool
def get_fundamentals(ticker: str, curr_date: str) -> str:
    """Retrieve comprehensive fundamental data for a ticker."""
    return route_to_vendor("get_fundamentals", ticker, curr_date)


@tool
def get_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
    """Retrieve balance sheet data for a ticker."""
    return route_to_vendor("get_balance_sheet", ticker, freq, curr_date)


@tool
def get_cashflow(ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
    """Retrieve cash flow statement data for a ticker."""
    return route_to_vendor("get_cashflow", ticker, freq, curr_date)


@tool
def get_income_statement(ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
    """Retrieve income statement data for a ticker."""
    return route_to_vendor("get_income_statement", ticker, freq, curr_date)


@tool
def get_news(ticker: str, start_date: str, end_date: str) -> str:
    """Retrieve news data for a ticker symbol."""
    return route_to_vendor("get_news", ticker, start_date, end_date)


@tool
def get_global_news(curr_date: str, look_back_days: int = 7, limit: int = 5) -> str:
    """Retrieve global market news."""
    return route_to_vendor("get_global_news", curr_date, look_back_days, limit)


@tool
def get_insider_transactions(ticker: str) -> str:
    """Retrieve insider transaction information about a company."""
    return route_to_vendor("get_insider_transactions", ticker)
