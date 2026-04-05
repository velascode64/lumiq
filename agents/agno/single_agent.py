"""
Single-agent Agno setup for unified conversational trading.

This module intentionally aggregates tools across domains (technicals, news,
live broker execution, and strategy ops) into one agent for natural chat flows.
"""

from __future__ import annotations

import functools
import inspect
import logging
import os
import time
from typing import Optional

from agno.agent import Agent

try:
    from .members.alert_agent import build_alert_tools
    from .members.context_tools import build_context_tools
    from .members.strategy_ops_agent import _resolve_model, build_trading_tools
    from .members.live_trading_agent import LiveBrokerGateway, _build_live_trading_tools
    from .members.technical_agent import build_technical_tools
    from .members.news_agent import build_news_tools
    from .members.shared_memory_tools import build_shared_memory_tools
except ImportError:
    from agents.agno.members.alert_agent import build_alert_tools
    from agents.agno.members.context_tools import build_context_tools
    from agents.agno.members.strategy_ops_agent import _resolve_model, build_trading_tools
    from agents.agno.members.live_trading_agent import LiveBrokerGateway, _build_live_trading_tools
    from agents.agno.members.technical_agent import build_technical_tools
    from agents.agno.members.news_agent import build_news_tools
    from agents.agno.members.shared_memory_tools import build_shared_memory_tools


logger = logging.getLogger(__name__)


def _short(value: object, max_len: int = 600) -> str:
    text = "" if value is None else str(value)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _instrument_tool_calls(tools: list) -> list:
    """Attach runtime logging to Agno tool entrypoints."""
    instrumented = []
    for tool_obj in tools:
        tool_name = getattr(tool_obj, "name", None) or getattr(tool_obj, "__name__", None) or str(tool_obj)
        entrypoint = getattr(tool_obj, "entrypoint", None)
        if entrypoint is None or getattr(tool_obj, "_lumiq_logged", False):
            instrumented.append(tool_obj)
            continue

        @functools.wraps(entrypoint)
        def _logged_entrypoint(*args, __entrypoint=entrypoint, __tool_name=tool_name, **kwargs):
            start = time.monotonic()
            logger.info(
                "Agno tool call start | tool=%s | args=%s | kwargs=%s",
                __tool_name,
                _short(args),
                _short(kwargs),
            )
            try:
                result = __entrypoint(*args, **kwargs)
                elapsed_ms = (time.monotonic() - start) * 1000.0
                logger.info(
                    "Agno tool call done | tool=%s | elapsed_ms=%.1f | result=%s",
                    __tool_name,
                    elapsed_ms,
                    _short(result),
                )
                return result
            except Exception as exc:
                elapsed_ms = (time.monotonic() - start) * 1000.0
                logger.exception(
                    "Agno tool call failed | tool=%s | elapsed_ms=%.1f | error=%s",
                    __tool_name,
                    elapsed_ms,
                    exc,
                )
                raise

        tool_obj.entrypoint = _logged_entrypoint
        tool_obj._lumiq_logged = True
        instrumented.append(tool_obj)
    return instrumented


def create_single_trading_agent(
    orchestrator,
    alert_system=None,
    news_service=None,
    watchlist_store=None,
    memory_repo=None,
    coordination_repo=None,
    agno_db=None,
) -> Optional[Agent]:
    """
    Build one unified agent with all trading-related tools.
    """
    model = _resolve_model()
    if model is None:
        return None

    tools = []
    if alert_system is not None:
        tools.extend(build_alert_tools(alert_system))
        tools.extend(build_technical_tools(alert_system))
    if news_service is not None:
        tools.extend(build_news_tools(news_service))
    gateway = None
    if orchestrator is not None:
        tools.extend(build_trading_tools(orchestrator, allow_strategy_control=False))
        broker_config = getattr(orchestrator, "broker_config", None)
        if broker_config:
            gateway = LiveBrokerGateway(broker_config)
            tools.extend(_build_live_trading_tools(gateway))
    tools.extend(
        build_context_tools(
            orchestrator=orchestrator,
            alert_system=alert_system,
            watchlist_store=watchlist_store,
            live_gateway=gateway,
        )
    )
    shared_tools = build_shared_memory_tools(
        memory_repo=memory_repo,
        coordination_repo=coordination_repo,
        default_team_name="TradingSingleAgent",
    )
    if shared_tools:
        tools.extend(shared_tools)

    # Deduplicate by function name to keep tool registry stable.
    deduped_tools = []
    seen = set()
    for tool_fn in tools:
        name = getattr(tool_fn, "name", None) or getattr(tool_fn, "__name__", None) or str(tool_fn)
        if name in seen:
            continue
        seen.add(name)
        deduped_tools.append(tool_fn)
    deduped_tools = _instrument_tool_calls(deduped_tools)

    instructions = [
        "You are Lumiq Trading Copilot, the single in-app agent for trading, watchlists, alerts, technicals, news, strategy ops, and broker execution.",
        "Always respond in English, concise and actionable.",
        "Use tools for facts. Never invent watchlists, alerts, prices, indicators, portfolio values, positions, orders, strategies, or news.",
        "Do not ask the user for their chat id, account id, or hidden runtime state. The tools already operate on the current scope.",
        "Never claim that a watchlist, alert, position, order, strategy, or account value exists unless a tool returned it.",
        "Never claim that an alert/order/strategy change succeeded unless a write tool actually returned success.",
        "If a request is missing a required execution parameter, ask one short clarification question and stop.",
        "Conversation style: direct, practical, and concrete. Prefer short answers with bullet points only when they add value.",
        "Tool usage policy:",
        "For questions about the user's watchlist, followed tickers, favorites, or watchlist groups, call get_watchlist_context first. Use get_followed_tickers when the user only wants the ticker list.",
        "For questions about the user's alerts or alert rules, call get_alerts_context first.",
        "For questions about market opportunities, dip setups, market summary, latest price, or advanced alert types, use the alert-analysis tools after reading the current context.",
        "For questions about current portfolio/account state, holdings, open orders, or execution state, call get_user_execution_context first.",
        "For direct questions about invested value, portfolio value, cash, equity, or buying power, call get_user_portfolio_value first.",
        "For questions about running strategies or strategy state, call get_user_strategy_context first.",
        "For technical analysis questions, call technical tools first and cite key numeric evidence.",
        "For news/catalyst questions, call news tools first and prioritize relevance and urgency.",
        "For explicit broker execution intents (buy, sell, close, cancel, market order, limit order), call live broker tools only after the user clearly specifies the asset and execution details.",
        "Do not rely on prior conversational guesses when a direct context tool exists. Re-read the real state with tools.",
    ]

    desired_kwargs = {
        "name": "TradingSingleAgent",
        "model": model,
        "tools": deduped_tools,
        "role": "Unified trading assistant with cross-domain tool access",
        "goal": "Handle natural trading conversations while executing accurate tool calls across technicals, news, strategy ops, and broker actions.",
        "success_criteria": "Return correct, tool-grounded answers with low latency and safe execution behavior.",
        "instructions": instructions,
        "show_tool_calls": False,
        "add_history_to_messages": True,
        "num_history_runs": 8,
        "markdown": False,
    }
    if agno_db is not None:
        desired_kwargs["db"] = agno_db
        enable_memory = str(os.getenv("LUMIQ_AGNO_SINGLE_AGENT_MEMORY", "false")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if enable_memory:
            desired_kwargs["update_memory_on_run"] = True
            desired_kwargs["add_memories_to_context"] = True
            desired_kwargs["enable_agentic_memory"] = False
        enable_history = str(os.getenv("LUMIQ_AGNO_SINGLE_AGENT_HISTORY", "false")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if enable_history:
            desired_kwargs["read_chat_history"] = True
            desired_kwargs["add_history_to_context"] = True
    accepted = set(inspect.signature(Agent.__init__).parameters.keys())
    filtered_kwargs = {key: value for key, value in desired_kwargs.items() if key in accepted}
    return Agent(**filtered_kwargs)


def run_single_agent_message(agent: Agent, message: str, user_id: str, session_id: str) -> str:
    """
    Run one message through the unified agent and return plain text output.
    """
    logger.info(
        "Agno SingleAgent input | agent=%s | session_id=%s | user_id=%s | message=%s",
        getattr(agent, "name", None) or agent.__class__.__name__,
        session_id,
        user_id,
        message,
    )
    response = agent.run(message, user_id=user_id, session_id=session_id)
    logger.info(
        "Agno SingleAgent output | agent=%s | session_id=%s | agent_name=%s",
        getattr(agent, "name", None) or agent.__class__.__name__,
        session_id,
        getattr(response, "agent_name", None),
    )
    content = getattr(response, "content", None)
    if content is None:
        return "Could not generate a response."
    if isinstance(content, str):
        return content
    return str(content)
