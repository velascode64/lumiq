"""Backward-compatible trading agent exports.

This module now maps the legacy trading agent API to the StrategyOpsAgent so existing
imports continue to work while manual broker execution is handled by LiveTradingAgent
inside the Agno Team.
"""

from __future__ import annotations

try:
    from .agno_strategy_ops_agent import (
        build_trading_tools,
        create_strategy_ops_agent,
        create_trading_agent,
        run_agent_message,
        run_strategy_ops_message,
    )
except ImportError:
    from agno_strategy_ops_agent import (
        build_trading_tools,
        create_strategy_ops_agent,
        create_trading_agent,
        run_agent_message,
        run_strategy_ops_message,
    )

__all__ = [
    "build_trading_tools",
    "create_strategy_ops_agent",
    "create_trading_agent",
    "run_strategy_ops_message",
    "run_agent_message",
]
