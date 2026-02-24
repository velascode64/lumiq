"""
Agno-based Alert Agent for intelligent alert filtering.

This agent uses LLM to analyze and prioritize trading opportunities,
filtering noise and generating actionable summaries.
"""

import os
import json
import logging
import inspect
from datetime import datetime
from typing import Any, Dict, List, Optional

from agno.agent import Agent
from agno.tools import tool

from ..alert_factory import (
    create_bollinger_middle_cross,
    create_macd_bullish_cross,
    create_rsi_overbought,
    create_rsi_oversold,
)

logger = logging.getLogger(__name__)


def _json_dump(data: Any) -> str:
    """Safely serialize data to JSON."""
    try:
        return json.dumps(data, ensure_ascii=True, default=str, indent=2)
    except Exception:
        return str(data)


def _resolve_model():
    """
    Resolve Agno model from environment.

    Priority:
    1) AGNO_PROVIDER=anthropic/openai
    2) ANTHROPIC_API_KEY
    3) OPENAI_API_KEY
    """
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

    # Auto-detect based on available keys
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        from agno.models.anthropic import Claude
        return Claude(id=model_id or "claude-3-5-sonnet-20241022", api_key=anthropic_key)

    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        from agno.models.openai import OpenAIChat
        return OpenAIChat(id=model_id or "gpt-4o-mini", api_key=openai_key)

    return None


def build_alert_tools(alert_system) -> List[Any]:
    """
    Create Agno tools for the alert system.

    Args:
        alert_system: AlertSystem instance

    Returns:
        List of tool functions
    """

    @tool
    def analyze_symbol(symbol: str) -> str:
        """
        Analyze a single stock symbol.

        Returns technical indicators, trend analysis, and opportunity score.
        """
        try:
            result = alert_system.analyze_single(symbol)
            if result is None:
                return f"No data available for {symbol}"
            return _json_dump({
                "symbol": result.symbol,
                "score": result.score,
                "priority": result.priority.value,
                "reasons": result.reasons,
                "price": result.stock_data.current_price,
                "daily_change": f"{result.stock_data.daily_change_pct:.2f}%",
                "rsi": result.technical.rsi,
                "trend_30d": f"{result.trend.change_30d:.2f}%",
                "trend_90d": f"{result.trend.change_90d:.2f}%",
            })
        except Exception as e:
            return f"Error analyzing {symbol}: {e}"

    @tool
    def get_top_opportunities(count: int = 10) -> str:
        """
        Get the top N buying opportunities.

        Returns opportunities ranked by score, including HOT and WATCH priorities.
        """
        try:
            opportunities = alert_system.get_top_opportunities(count)
            results = []
            for opp in opportunities:
                results.append({
                    "symbol": opp.symbol,
                    "score": opp.score,
                    "priority": opp.priority.value,
                    "reasons": opp.reasons[:2],
                    "price": opp.stock_data.current_price,
                })
            return _json_dump(results)
        except Exception as e:
            return f"Error getting opportunities: {e}"

    @tool
    def get_market_summary() -> str:
        """
        Get a summary of the current market conditions.

        Includes counts of HOT/WATCH opportunities and overall market sentiment.
        """
        try:
            summary = alert_system.get_market_summary()
            return _json_dump(summary)
        except Exception as e:
            return f"Error getting market summary: {e}"

    @tool
    def get_dip_opportunities() -> str:
        """
        Get stocks that have significant dips and may be buying opportunities.

        Focuses on stocks with >10% dip that were previously in uptrends.
        """
        try:
            dips = alert_system.get_dip_opportunities()
            results = []
            for opp in dips:
                dip_info = opp.dip
                results.append({
                    "symbol": opp.symbol,
                    "dip_percentage": dip_info.dip_percentage if dip_info else 0,
                    "classification": dip_info.classification.value if dip_info else "none",
                    "rsi": opp.technical.rsi,
                    "score": opp.score,
                })
            return _json_dump(results)
        except Exception as e:
            return f"Error getting dip opportunities: {e}"

    @tool
    def generate_telegram_report(session: str = "analysis") -> str:
        """
        Generate a formatted report for Telegram.

        Args:
            session: Session name (apertura, medio_dia, cierre)

        Returns the formatted message ready to send.
        """
        try:
            summary = alert_system.create_summary(session)
            return summary.to_telegram_message()
        except Exception as e:
            return f"Error generating report: {e}"

    def _new_rule_id(symbol: str) -> str:
        return f"{symbol}-{int(datetime.now().timestamp())}"

    def _apply_rule_defaults(rule: Dict[str, Any], symbol: str) -> Dict[str, Any]:
        rule.setdefault("id", _new_rule_id(symbol))
        chat_id = alert_system.get_active_chat_id()
        if chat_id is not None and rule.get("chat_id") is None:
            rule["chat_id"] = int(chat_id)
        if rule.get("cooldown_seconds") is None:
            rule["cooldown_seconds"] = 300
        return rule

    @tool
    def list_alert_rules() -> str:
        """List persisted alert rules."""
        try:
            rules = alert_system.list_rules()
            return _json_dump(rules)
        except Exception as e:
            return f"Error listing rules: {e}"

    @tool
    def create_percent_drop_alert(symbol: str, drop_percent: float) -> str:
        """Create a percent drop alert (e.g., 0.25)."""
        try:
            symbol = symbol.upper()
            rule = {
                "id": _new_rule_id(symbol),
                "symbol": symbol,
                "type": "percent_drop",
                "threshold": float(drop_percent),
                "active": True,
            }
            chat_id = alert_system.get_active_chat_id()
            if chat_id is not None:
                rule["chat_id"] = int(chat_id)
            if rule.get("cooldown_seconds") is None:
                rule["cooldown_seconds"] = 300
            current = alert_system.data_service.get_latest_price(symbol)
            if current is not None:
                rule["reference_price"] = float(current)
            saved = alert_system.add_rule(rule)
            return _json_dump(saved)
        except Exception as e:
            return f"Error creating drop alert: {e}"

    @tool
    def create_percent_rise_alert(symbol: str, rise_percent: float) -> str:
        """Create a percent rise alert (e.g., 1.5)."""
        try:
            symbol = symbol.upper()
            rule = {
                "id": _new_rule_id(symbol),
                "symbol": symbol,
                "type": "percent_rise",
                "threshold": float(rise_percent),
                "active": True,
            }
            chat_id = alert_system.get_active_chat_id()
            if chat_id is not None:
                rule["chat_id"] = int(chat_id)
            if rule.get("cooldown_seconds") is None:
                rule["cooldown_seconds"] = 300
            current = alert_system.data_service.get_latest_price(symbol)
            if current is not None:
                rule["reference_price"] = float(current)
            saved = alert_system.add_rule(rule)
            return _json_dump(saved)
        except Exception as e:
            return f"Error creating rise alert: {e}"

    @tool
    def create_target_price_alert(symbol: str, target_price: float) -> str:
        """Create a target price alert."""
        try:
            symbol = symbol.upper()
            rule = {
                "id": _new_rule_id(symbol),
                "symbol": symbol,
                "type": "target_price",
                "target": float(target_price),
                "active": True,
            }
            chat_id = alert_system.get_active_chat_id()
            if chat_id is not None:
                rule["chat_id"] = int(chat_id)
            if rule.get("cooldown_seconds") is None:
                rule["cooldown_seconds"] = 300
            saved = alert_system.add_rule(rule)
            return _json_dump(saved)
        except Exception as e:
            return f"Error creating target alert: {e}"

    @tool
    def create_max_price_alert(symbol: str, lookback_days: int = 252) -> str:
        """Create an alert when price reaches the recent maximum (lookback window)."""
        try:
            symbol = symbol.upper()
            bars = alert_system.data_service.get_stock_bars(symbol, days=int(lookback_days))
            if bars is None or bars.empty:
                return _json_dump({"error": "no_bars", "symbol": symbol})
            max_price = float(bars["high"].max())
            rule = {
                "id": _new_rule_id(symbol),
                "symbol": symbol,
                "type": "max_price",
                "reference_price": max_price,
                "lookback_days": int(lookback_days),
                "active": True,
            }
            chat_id = alert_system.get_active_chat_id()
            if chat_id is not None:
                rule["chat_id"] = int(chat_id)
            if rule.get("cooldown_seconds") is None:
                rule["cooldown_seconds"] = 300
            saved = alert_system.add_rule(rule)
            return _json_dump(saved)
        except Exception as e:
            return f"Error creating max price alert: {e}"

    @tool
    def create_min_price_alert(symbol: str, lookback_days: int = 252) -> str:
        """Create an alert when price reaches the recent minimum (lookback window)."""
        try:
            symbol = symbol.upper()
            bars = alert_system.data_service.get_stock_bars(symbol, days=int(lookback_days))
            if bars is None or bars.empty:
                return _json_dump({"error": "no_bars", "symbol": symbol})
            min_price = float(bars["low"].min())
            rule = {
                "id": _new_rule_id(symbol),
                "symbol": symbol,
                "type": "min_price",
                "reference_price": min_price,
                "lookback_days": int(lookback_days),
                "active": True,
            }
            chat_id = alert_system.get_active_chat_id()
            if chat_id is not None:
                rule["chat_id"] = int(chat_id)
            if rule.get("cooldown_seconds") is None:
                rule["cooldown_seconds"] = 300
            saved = alert_system.add_rule(rule)
            return _json_dump(saved)
        except Exception as e:
            return f"Error creating min price alert: {e}"

    @tool
    def create_rsi_oversold_alert(
        symbol: str,
        period: int = 14,
        threshold: float = 30.0,
        lookback_days: Optional[int] = None,
    ) -> str:
        """Create an RSI oversold alert (default 30)."""
        try:
            symbol = symbol.upper()
            rule = create_rsi_oversold(symbol, period=period, threshold=threshold)
            rule = _apply_rule_defaults(rule, symbol)
            if lookback_days is not None:
                rule["lookback_days"] = int(lookback_days)
            saved = alert_system.add_rule(rule)
            return _json_dump(saved)
        except Exception as e:
            return f"Error creating RSI alert: {e}"

    @tool
    def create_rsi_overbought_alert(
        symbol: str,
        period: int = 14,
        threshold: float = 70.0,
        lookback_days: Optional[int] = None,
    ) -> str:
        """Create an RSI overbought alert (default 70)."""
        try:
            symbol = symbol.upper()
            rule = create_rsi_overbought(symbol, period=period, threshold=threshold)
            rule = _apply_rule_defaults(rule, symbol)
            if lookback_days is not None:
                rule["lookback_days"] = int(lookback_days)
            saved = alert_system.add_rule(rule)
            return _json_dump(saved)
        except Exception as e:
            return f"Error creating RSI overbought alert: {e}"

    @tool
    def create_macd_bullish_alert(
        symbol: str,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        lookback_days: Optional[int] = None,
    ) -> str:
        """Create a MACD bullish cross alert."""
        try:
            symbol = symbol.upper()
            rule = create_macd_bullish_cross(symbol, fast=fast, slow=slow, signal=signal)
            rule = _apply_rule_defaults(rule, symbol)
            if lookback_days is not None:
                rule["lookback_days"] = int(lookback_days)
            saved = alert_system.add_rule(rule)
            return _json_dump(saved)
        except Exception as e:
            return f"Error creating MACD alert: {e}"

    @tool
    def create_bollinger_middle_cross_alert(
        symbol: str,
        period: int = 20,
        stddev: float = 2.0,
        direction: str = "above",
        lookback_days: Optional[int] = None,
    ) -> str:
        """Create a Bollinger middle-band cross alert."""
        try:
            symbol = symbol.upper()
            rule = create_bollinger_middle_cross(
                symbol,
                period=period,
                stddev=stddev,
                direction=direction,
            )
            rule = _apply_rule_defaults(rule, symbol)
            if lookback_days is not None:
                rule["lookback_days"] = int(lookback_days)
            saved = alert_system.add_rule(rule)
            return _json_dump(saved)
        except Exception as e:
            return f"Error creating Bollinger alert: {e}"

    @tool
    def get_latest_price(symbol: str) -> str:
        """Get the latest price for a symbol (stocks or crypto)."""
        try:
            price = alert_system.data_service.get_latest_price(symbol)
            if price is None:
                return _json_dump({"symbol": symbol, "price": None, "error": "price_unavailable"})
            return _json_dump({"symbol": symbol, "price": float(price)})
        except Exception as e:
            return f"Error getting latest price: {e}"

    @tool
    def update_alert_rule(
        rule_id: str,
        active: Optional[bool] = None,
        threshold: Optional[float] = None,
        target_price: Optional[float] = None,
    ) -> str:
        """Update an existing alert rule by id."""
        try:
            updates: Dict[str, Any] = {}
            if active is not None:
                updates["active"] = bool(active)
            if threshold is not None:
                updates["threshold"] = float(threshold)
            if target_price is not None:
                updates["target"] = float(target_price)
            updated = alert_system.update_rule(rule_id, updates)
            return _json_dump(updated)
        except Exception as e:
            return f"Error updating rule: {e}"

    @tool
    def remove_alert_rule(rule_id: str) -> str:
        """Remove an alert rule by id."""
        try:
            ok = alert_system.remove_rule(rule_id)
            return _json_dump({"removed": bool(ok)})
        except Exception as e:
            return f"Error removing rule: {e}"

    @tool
    def evaluate_alert_rules() -> str:
        """Evaluate current rules against latest prices."""
        try:
            messages = alert_system.evaluate_rules()
            return _json_dump(messages)
        except Exception as e:
            return f"Error evaluating rules: {e}"

    return [
        analyze_symbol,
        get_top_opportunities,
        get_market_summary,
        get_dip_opportunities,
        generate_telegram_report,
        list_alert_rules,
        get_latest_price,
        create_percent_drop_alert,
        create_percent_rise_alert,
        create_target_price_alert,
        create_max_price_alert,
        create_min_price_alert,
        create_rsi_oversold_alert,
        create_rsi_overbought_alert,
        create_macd_bullish_alert,
        create_bollinger_middle_cross_alert,
        update_alert_rule,
        remove_alert_rule,
        evaluate_alert_rules,
    ]


def create_alert_agent(alert_system) -> Optional[Agent]:
    """
    Create an Agno agent for intelligent alert analysis.

    Args:
        alert_system: AlertSystem instance

    Returns:
        Agent instance or None if no LLM configured
    """
    model = _resolve_model()
    if model is None:
        logger.warning("No LLM API key configured - agent disabled")
        return None

    instructions = [
        "Eres un analista de alertas de stocks especializado en encontrar oportunidades de compra.",
        "Tu trabajo es filtrar el ruido y encontrar oportunidades reales de compra.",
        "Cuando el usuario pida crear una alerta (ej. caída % o precio objetivo), crea la regla usando las tools disponibles.",
        "Si el usuario pide alertas técnicas (RSI, MACD, Bollinger), usa las tools create_*_alert disponibles.",
        "Si el usuario dice 'oversold/sobrevendida' crea RSI oversold (30). Si dice 'overbought/sobrecomprada' crea RSI overbought (70).",
        "No rechaces alertas por tamaño de movimiento: si el usuario la pide, se crea tal cual.",
        "Si el usuario pregunta por precios actuales, SIEMPRE usa la tool get_latest_price y no inventes valores.",
        "",
        "PRIORIZA:",
        "- Caídas significativas (>10%) en stocks con tendencia alcista previa",
        "- RSI en sobreventa (<30) después de un pullback",
        "- Panic selling con volumen alto",
        "",
        "IGNORA:",
        "- Stocks sin volumen significativo",
        "- Patrones erráticos sin tendencia clara",
        "- Caídas fundamentales (downtrend de 90+ días)",
        "",
        "CLASIFICACIÓN:",
        "- HOT (score >70): Oportunidad fuerte, considerar compra inmediata",
        "- WATCH (score 40-70): Monitorear de cerca",
        "- IGNORE (score <40): No vale la pena seguir",
        "",
        "Responde en español de forma concisa. Cuando analices, incluye el score y las razones principales.",
    ]

    # Build kwargs compatible with current agno version
    desired_kwargs = {
        "name": "AlertAnalyst",
        "model": model,
        "tools": build_alert_tools(alert_system),
        "instructions": instructions,
        "show_tool_calls": False,
        "add_history_to_messages": True,
        "num_history_runs": 5,
        "markdown": False,
    }

    # Filter to only supported kwargs
    accepted = set(inspect.signature(Agent.__init__).parameters.keys())
    filtered_kwargs = {key: value for key, value in desired_kwargs.items() if key in accepted}

    agent = Agent(**filtered_kwargs)

    # Store reference to alert_system
    setattr(agent, "_alert_system", alert_system)

    return agent


def run_agent_analysis(agent: Agent, message: str) -> str:
    """
    Run analysis through the agent.

    Args:
        agent: Agno agent instance
        message: User message/query

    Returns:
        Agent response as string
    """
    try:
        response = agent.run(message)
        content = getattr(response, "content", None)

        if content is None:
            return "No se pudo generar una respuesta."

        if isinstance(content, str):
            return content

        return _json_dump(content)

    except Exception as e:
        logger.error(f"Agent analysis failed: {e}")
        return f"Error en el análisis: {e}"
