"""
Agno News Analyst agent for watchlist/portfolio news relevance.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
from typing import Any, Dict, List, Optional

from agno.agent import Agent
from agno.tools import tool

logger = logging.getLogger(__name__)


def _json_dump(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=True, default=str, indent=2)
    except Exception:
        return str(data)


def _resolve_model():
    provider = os.getenv("AGNO_PROVIDER", "").strip().lower()
    model_id = os.getenv("AGNO_MODEL", "").strip()

    if provider == "anthropic":
        from agno.models.anthropic import Claude
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("AGNO_PROVIDER=anthropic set but ANTHROPIC_API_KEY is missing")
        return Claude(id=model_id or "claude-3-5-sonnet-20241022", api_key=api_key)

    if provider == "openai":
        from agno.models.openai import OpenAIChat
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("AGNO_PROVIDER=openai set but OPENAI_API_KEY is missing")
        return OpenAIChat(id=model_id or "gpt-4o-mini", api_key=api_key)

    if os.getenv("ANTHROPIC_API_KEY"):
        from agno.models.anthropic import Claude
        return Claude(id=model_id or "claude-3-5-sonnet-20241022", api_key=os.getenv("ANTHROPIC_API_KEY"))
    if os.getenv("OPENAI_API_KEY"):
        from agno.models.openai import OpenAIChat
        return OpenAIChat(id=model_id or "gpt-4o-mini", api_key=os.getenv("OPENAI_API_KEY"))
    return None


def build_news_tools(news_service) -> List[Any]:
    @tool
    def get_watchlist_news_payload(
        group_name: Optional[str] = None,
        lookback_hours: int = 18,
        limit: int = 80,
        min_impact_score: int = 0,
    ) -> str:
        """
        Fetch Alpaca news for watchlist/group and return structured JSON.

        Use this first before summarizing or classifying relevance.
        """
        try:
            payload = news_service.export_news_payload(
                group_name=group_name,
                lookback_hours=int(lookback_hours),
                limit=int(limit),
                min_impact_score=int(min_impact_score),
            )
            return _json_dump(payload)
        except Exception as exc:
            return f"Error fetching watchlist news payload: {exc}"

    @tool
    def get_watchlist_news_digest_preview(group_name: Optional[str] = None) -> str:
        """Get deterministic digest preview (fallback baseline)."""
        try:
            return news_service.generate_preopen_digest_text(group_name=group_name)
        except Exception as exc:
            return f"Error generating news digest preview: {exc}"

    return [get_watchlist_news_payload, get_watchlist_news_digest_preview]


def create_news_agent(news_service) -> Optional[Agent]:
    if news_service is None:
        return None
    model = _resolve_model()
    if model is None:
        logger.warning("No LLM API key configured - news agent disabled")
        return None

    instructions = [
        "Eres un analista de noticias para trading manual enfocado en watchlist/portfolio.",
        "Tu objetivo es reducir ruido y priorizar noticias relevantes para la apertura y el dia.",
        "SIEMPRE usa get_watchlist_news_payload antes de concluir. No inventes titulares.",
        "Clasifica cada noticia relevante por: relevancia (alta/media/baja), sesgo (positivo/negativo/mixto), urgencia (pre-open/hoy/seguimiento).",
        "Enfatiza impacto potencial sobre posiciones actuales y favoritos/watchlist.",
        "Distingue ruido vs catalizador real (earnings, guidance, downgrade/upgrade, legal, M&A, SEC, etc.).",
        "Incluye links (url) de las noticias en Alta prioridad y en cualquier ticker que recomiendes revisar primero.",
        "Responde en espanol y de forma puntual para Telegram.",
        "Formato requerido: Resumen, Alta prioridad (con links), Impacto en posiciones, Impacto en watchlist sin posicion, Ruido, Tickers a revisar primero (con links si aplica), Sugerencias (tecnico/alerta/esperar), Conclusión.",
        "La seccion Conclusión debe cerrar con 3-5 lineas: que importa hoy, que puede esperar, y que revisar primero.",
        "No des consejo financiero absoluto; da prioridad y seguimiento sugerido.",
    ]
    desired_kwargs = {
        "name": "NewsAnalyst",
        "model": model,
        "tools": build_news_tools(news_service),
        "role": "Analista de noticias financieras para priorizar relevancia en watchlist/portfolio",
        "goal": "Entregar un resumen accionable y priorizado de noticias diarias para reducir carga mental del usuario",
        "success_criteria": "Usar tools reales de noticias y producir una clasificacion clara de relevancia/impacto con seguimiento sugerido",
        "instructions": instructions,
        "show_tool_calls": False,
        "add_history_to_messages": True,
        "num_history_runs": 6,
        "markdown": False,
    }
    accepted = set(inspect.signature(Agent.__init__).parameters.keys())
    filtered = {k: v for k, v in desired_kwargs.items() if k in accepted}
    agent = Agent(**filtered)
    setattr(agent, "_news_service", news_service)
    return agent


def run_news_agent_message(agent: Agent, message: str, user_id: str = "news-cron", session_id: str = "news-cron") -> str:
    try:
        logger.info(
            "Agno News Agent input | agent=%s | session_id=%s | user_id=%s | message=%s",
            getattr(agent, "name", None) or agent.__class__.__name__,
            session_id,
            user_id,
            message,
        )
        response = agent.run(message, user_id=user_id, session_id=session_id)
        logger.info(
            "Agno News Agent output | session_id=%s | agent_name=%s",
            session_id,
            getattr(response, "agent_name", None),
        )
        content = getattr(response, "content", None)
        if content is None:
            return "No se pudo generar el analisis de noticias."
        return content if isinstance(content, str) else str(content)
    except Exception as exc:
        logger.exception("News agent run failed: %s", exc)
        raise
