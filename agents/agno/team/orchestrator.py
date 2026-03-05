"""
Agno Team orchestration for alerts, technical analysis, live trading, and strategy operations.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

from agno.team import Team
import inspect

try:
    from agno.models.anthropic import Claude
except Exception:  # pragma: no cover
    Claude = None

try:
    from agno.models.openai import OpenAIChat
except Exception:  # pragma: no cover
    OpenAIChat = None


logger = logging.getLogger(__name__)


def _collect_member_names(response_obj) -> list[str]:
    """
    Extract delegated member names from a TeamRunResponse/RunResponse tree.
    """
    names: list[str] = []
    member_responses = getattr(response_obj, "member_responses", None) or []
    for member in member_responses:
        agent_name = getattr(member, "agent_name", None)
        team_name = getattr(member, "team_name", None)
        if agent_name:
            names.append(str(agent_name))
        elif team_name:
            names.append(f"team:{team_name}")
        nested = _collect_member_names(member)
        if nested:
            names.extend(nested)
    return names


def _iter_member_responses(response_obj):
    member_responses = getattr(response_obj, "member_responses", None) or []
    for member in member_responses:
        yield member
        yield from _iter_member_responses(member)


def _short(value: object, max_len: int = 400) -> str:
    text = "" if value is None else str(value)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _resolve_model():
    """
    Resolve Agno model from environment.
    Priority:
    1) AGNO_PROVIDER=anthropic/openai
    2) ANTHROPIC_API_KEY
    3) OPENAI_API_KEY
    """
    import os

    provider = os.getenv("AGNO_PROVIDER", "").strip().lower()
    model_id = os.getenv("AGNO_MODEL", "").strip()

    if provider == "anthropic" and Claude is not None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("AGNO_PROVIDER=anthropic set but ANTHROPIC_API_KEY is missing")
        return Claude(id=model_id or "claude-3-5-sonnet-20241022", api_key=api_key)

    if provider == "openai" and OpenAIChat is not None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("AGNO_PROVIDER=openai set but OPENAI_API_KEY is missing")
        return OpenAIChat(id=model_id or "gpt-4o-mini", api_key=api_key)

    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key and Claude is not None:
        return Claude(id=model_id or "claude-3-5-sonnet-20241022", api_key=anthropic_key)

    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key and OpenAIChat is not None:
        return OpenAIChat(id=model_id or "gpt-4o-mini", api_key=openai_key)

    return None


def create_alerts_trading_team(
    orchestrator,
    alert_system,
    news_service=None,
    memory_repo=None,
    coordination_repo=None,
    agno_db=None,
) -> Optional[Team]:
    """
    Create a Team with alert + trading agents in route mode.
    Returns None when no LLM API key is configured.
    """
    try:
        from ..members.strategy_ops_agent import create_strategy_ops_agent
        from ..members.live_trading_agent import create_live_trading_agent
    except ImportError:
        from agents.agno.members.strategy_ops_agent import create_strategy_ops_agent
        from agents.agno.members.live_trading_agent import create_live_trading_agent

    try:
        from ..members.technical_agent import create_technical_agent
    except ImportError:
        from agents.agno.members.technical_agent import create_technical_agent
    try:
        from ..members.news_agent import create_news_agent
    except ImportError:
        from agents.agno.members.news_agent import create_news_agent
    try:
        from ..members.shared_memory_tools import build_shared_memory_tools
    except ImportError:
        from agents.agno.members.shared_memory_tools import build_shared_memory_tools

    model = _resolve_model()
    if model is None:
        return None

    strategy_ops_agent = create_strategy_ops_agent(orchestrator)
    live_trading_agent = create_live_trading_agent(getattr(orchestrator, "broker_config", None))
    technical_agent = None
    news_agent = None
    if alert_system is not None:
        technical_agent = create_technical_agent(alert_system)
    if news_service is not None:
        news_agent = create_news_agent(news_service)

    members = [m for m in (technical_agent, news_agent, live_trading_agent, strategy_ops_agent) if m is not None]
    if not members:
        return None

    shared_tools = build_shared_memory_tools(
        memory_repo=memory_repo,
        coordination_repo=coordination_repo,
        default_team_name="TradingAlertTeam",
    )
    if shared_tools:
        for member in members:
            try:
                original = list(getattr(member, "tools", None) or [])
                member.tools = original + shared_tools
                if hasattr(member, "_rebuild_tools"):
                    member._rebuild_tools = True  # type: ignore[attr-defined]
            except Exception:
                logger.exception("Failed to attach shared memory tools to member %s", getattr(member, "name", "?"))

    instructions = [
        "You are an orchestrator that routes each message to the correct domain: ALERTS, TECHNICALS, NEWS, LIVE_TRADING, or STRATEGY_OPS.",
        "When delegating, use the exact member IDs shown by the team (lowercase), not display names.",
        "Member IDs in this team may include: technicalanalyst, newsanalyst, livetradingagent, lumibotstrategyopsassistant.",
        "If the user asks to create/modify/remove/list alerts (drop %, rise %, target price, rules), route to member ID technicalanalyst.",
        "If the user asks for current prices together with technical interpretation, route to member ID technicalanalyst.",
        "If the user asks about technicals (RSI, MACD, Bollinger, overbought/oversold, support/resistance, bounce, breakdown, how many times price touched a level, historical drops), use the technicals agent.",
        "If the user asks for interpretation of a price level or historical behavior after touching a level, use the technicals agent.",
        "If the user asks about news, catalysts, headlines, news impact on positions/watchlist, pre-market/pre-open summaries, route to member ID newsanalyst.",
        "If the user asks for a direct manual broker action (buy, sell, close position, cancel/modify order, market/limit order), route to member ID livetradingagent.",
        "If the user asks for strategy info, strategy status, strategy parameters, strategy PnL, running strategies, or account state in the context of Lumibot operations, route to member ID lumibotstrategyopsassistant.",
        "Shared memory tools are available. Persist reusable findings (facts/procedures/experiments) when they may help future turns or other agents.",
        "Respond in the same language as the user's latest message (Spanish or English), concisely.",
    ]

    desired_kwargs = {
        "members": members,
        "mode": "route",
        "model": model,
        "name": "TradingAlertTeam",
        "instructions": instructions,
        "markdown": False,
        "show_tool_calls": False,
        "read_chat_history": True,
        "add_history_to_context": True,
        "share_member_interactions": True,
        "store_member_responses": True,
        "enable_session_summaries": True,
        "add_session_summary_to_context": True,
        "num_history_runs": 6,
    }
    if agno_db is not None:
        desired_kwargs["db"] = agno_db
        # Official Agno memory/session persistence (optional but enabled by default).
        enable_team_memory = os.getenv("LUMIQ_AGNO_TEAM_MEMORY", "true").strip().lower() in {"1", "true", "yes", "on"}
        if enable_team_memory:
            desired_kwargs["update_memory_on_run"] = True
            desired_kwargs["add_memories_to_context"] = True
            desired_kwargs["enable_agentic_memory"] = False  # keep conservative; can turn on later explicitly
    accepted = set(inspect.signature(Team.__init__).parameters.keys())
    filtered_kwargs = {key: value for key, value in desired_kwargs.items() if key in accepted}
    try:
        team = Team(**filtered_kwargs)
        return team
    except Exception as exc:
        logger.exception("Failed to create Team with Agno DB/memory options; retrying without db features: %s", exc)
        for k in (
            "db",
            "update_memory_on_run",
            "add_memories_to_context",
            "enable_agentic_memory",
            "enable_session_summaries",
            "add_session_summary_to_context",
            "read_chat_history",
            "add_history_to_context",
            "share_member_interactions",
            "store_member_responses",
        ):
            filtered_kwargs.pop(k, None)
        return Team(**filtered_kwargs)


def run_team_message(team: Team, message: str, user_id: str, session_id: str) -> str:
    """Run one message through the Team and return plain text output."""
    try:
        start = time.monotonic()
        logger.info(
            "Agno Team input | team=%s | session_id=%s | user_id=%s | message=%s",
            getattr(team, "name", None) or team.__class__.__name__,
            session_id,
            user_id,
            message,
        )
        response = team.run(message, user_id=user_id, session_id=session_id)
        routed_members = _collect_member_names(response)
        logger.info(
            "Agno Team routed | team=%s | session_id=%s | members=%s",
            getattr(team, "name", None) or team.__class__.__name__,
            session_id,
            routed_members or ["unknown"],
        )
        for member in _iter_member_responses(response):
            member_name = getattr(member, "agent_name", None) or getattr(member, "team_name", None) or "unknown"
            member_content = _short(getattr(member, "content", None))
            logger.info(
                "Agno Team member output | team=%s | session_id=%s | member=%s | content=%s",
                getattr(team, "name", None) or team.__class__.__name__,
                session_id,
                member_name,
                member_content,
            )
        elapsed = time.monotonic() - start
        logger.info(
            "Agno Team completed | team=%s | session_id=%s | elapsed=%.2fs",
            getattr(team, "name", None) or team.__class__.__name__,
            session_id,
            elapsed,
        )
        content = getattr(response, "content", None)
        if content is None:
            return "No se pudo generar una respuesta."
        if isinstance(content, str):
            return content
        return str(content)
    except Exception as exc:
        logger.exception("Team run failed: %s", exc)
        return f"Error en el orquestador: {exc}"
