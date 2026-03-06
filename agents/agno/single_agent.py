"""
Single-agent Agno setup for unified conversational trading.

This module intentionally aggregates tools across domains (technicals, news,
live broker execution, and strategy ops) into one agent for natural chat flows.
"""

from __future__ import annotations

import inspect
import logging
import os
from typing import Optional

from agno.agent import Agent

try:
    from .members.strategy_ops_agent import _resolve_model, build_trading_tools
    from .members.live_trading_agent import LiveBrokerGateway, _build_live_trading_tools
    from .members.technical_agent import build_technical_tools
    from .members.news_agent import build_news_tools
    from .members.shared_memory_tools import build_shared_memory_tools
except ImportError:
    from agents.agno.members.strategy_ops_agent import _resolve_model, build_trading_tools
    from agents.agno.members.live_trading_agent import LiveBrokerGateway, _build_live_trading_tools
    from agents.agno.members.technical_agent import build_technical_tools
    from agents.agno.members.news_agent import build_news_tools
    from agents.agno.members.shared_memory_tools import build_shared_memory_tools


logger = logging.getLogger(__name__)


def create_single_trading_agent(
    orchestrator,
    alert_system=None,
    news_service=None,
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
        tools.extend(build_technical_tools(alert_system))
    if news_service is not None:
        tools.extend(build_news_tools(news_service))
    if orchestrator is not None:
        tools.extend(build_trading_tools(orchestrator, allow_strategy_control=False))
        broker_config = getattr(orchestrator, "broker_config", None)
        if broker_config:
            gateway = LiveBrokerGateway(broker_config)
            tools.extend(_build_live_trading_tools(gateway))
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
        name = getattr(tool_fn, "__name__", None) or str(tool_fn)
        if name in seen:
            continue
        seen.add(name)
        deduped_tools.append(tool_fn)

    instructions = [
        "You are a unified trading copilot for stocks and crypto.",
        "Always respond in English, concise and actionable.",
        "Use tools for facts. Never invent prices, indicators, account values, positions, orders, or news.",
        "For technical analysis requests, call technical tools first and cite key numeric evidence.",
        "For news/catalyst requests, call news tools and prioritize relevance/urgency.",
        "For account, portfolio, strategy status, or P&L requests, call strategy ops tools.",
        "For explicit execution intents (buy/sell/close/cancel), call live broker tools.",
        "If a request is not executable due to missing parameters, ask one short clarification question.",
        "Do not produce fake execution confirmations without a real tool call.",
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
        enable_memory = str(os.getenv("LUMIQ_AGNO_SINGLE_AGENT_MEMORY", "true")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if enable_memory:
            desired_kwargs["update_memory_on_run"] = True
            desired_kwargs["add_memories_to_context"] = True
            desired_kwargs["enable_agentic_memory"] = False
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
