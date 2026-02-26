"""
Agno Team orchestration for trading + alerts.

Routes user messages to the appropriate agent (trading or alerts).
"""

from __future__ import annotations

import logging
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


def create_alerts_trading_team(orchestrator, alert_system, news_service=None) -> Optional[Team]:
    """
    Create a Team with alert + trading agents in route mode.
    Returns None when no LLM API key is configured.
    """
    try:
        from .agno_trading_agent import create_trading_agent
    except ImportError:
        from agno_trading_agent import create_trading_agent

    try:
        from alerts.agents.alert_agent import create_alert_agent
    except ImportError:
        from .alerts.agents.alert_agent import create_alert_agent

    try:
        from alerts.agents.technical_agent import create_technical_agent
    except ImportError:
        from .alerts.agents.technical_agent import create_technical_agent
    try:
        from .agno_news_agent import create_news_agent
    except ImportError:
        from agno_news_agent import create_news_agent

    model = _resolve_model()
    if model is None:
        return None

    trading_agent = create_trading_agent(orchestrator)
    alert_agent = None
    technical_agent = None
    news_agent = None
    if alert_system is not None:
        alert_agent = create_alert_agent(alert_system)
        technical_agent = create_technical_agent(alert_system)
    if news_service is not None:
        news_agent = create_news_agent(news_service)

    members = [m for m in (alert_agent, technical_agent, news_agent, trading_agent) if m is not None]
    if not members:
        return None

    instructions = [
        "Eres un orquestador que decide si un mensaje es de ALERTAS, TECHNICALS, NOTICIAS o TRADING.",
        "Si el usuario pide crear o modificar alertas (drop %, target price, reglas), usa el agente de alertas.",
        "Si el usuario pregunta por precios actuales (BTC/ETH/SPY/etc.), usa el agente de alertas.",
        "Si el usuario pregunta technicals (RSI, MACD, Bollinger, sobrecompra/sobreventa, soporte/resistencia, rebote, breakdown, cuantas veces toco un precio, caidas historicas), usa el agente de technicals.",
        "Si el usuario pide interpretacion de un nivel de precio o comportamiento historico despues de tocar un nivel, usa el agente de technicals.",
        "Si el usuario pregunta por noticias, catalysts, headlines, impacto de noticias en posiciones/watchlist, resumen pre-market o pre-open, usa el agente de noticias.",
        "Si el usuario pide info de estrategias, estado o PnL, usa el agente de trading.",
        "Responde en español de forma concisa.",
    ]

    desired_kwargs = {
        "members": members,
        "mode": "route",
        "model": model,
        "name": "TradingAlertTeam",
        "instructions": instructions,
        "markdown": False,
        "show_tool_calls": False,
        "add_history_to_messages": True,
        "num_history_runs": 6,
    }
    accepted = set(inspect.signature(Team.__init__).parameters.keys())
    filtered_kwargs = {key: value for key, value in desired_kwargs.items() if key in accepted}
    team = Team(**filtered_kwargs)
    return team


def run_team_message(team: Team, message: str, user_id: str, session_id: str) -> str:
    """Run one message through the Team and return plain text output."""
    try:
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
        content = getattr(response, "content", None)
        if content is None:
            return "No se pudo generar una respuesta."
        if isinstance(content, str):
            return content
        return str(content)
    except Exception as exc:
        logger.exception("Team run failed: %s", exc)
        return f"Error en el orquestador: {exc}"
