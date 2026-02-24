"""
Agno conversational agent setup for controlling Lumibot strategies.
"""

from __future__ import annotations

import asyncio
import json
import os
import inspect
import shutil
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.tools import tool
from agno.tools.mcp import MCPTools
from lumibot.brokers import Alpaca

try:
    from .alpaca_pnl import get_realized_pnl_summary
except ImportError:
    from alpaca_pnl import get_realized_pnl_summary

try:
    from .strategy_orchestrator import StrategyOrchestrator
except ImportError:
    from strategy_orchestrator import StrategyOrchestrator


def _json_dump(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=True, default=str, indent=2)
    except Exception:
        return str(data)


def _parse_value(raw_value: Any) -> Any:
    if not isinstance(raw_value, str):
        return raw_value
    text = raw_value.strip()
    if not text:
        return text
    try:
        return json.loads(text)
    except Exception:
        return text


def _resolve_alpaca_mcp_command() -> Optional[str]:
    """
    Resolve Alpaca MCP server command from env or known local paths.
    """
    def ensure_serve(command: str) -> str:
        cmd = command.strip()
        if not cmd:
            return cmd
        if "alpaca-mcp-server" in cmd and " serve" not in f" {cmd} ":
            return f"{cmd} serve"
        return cmd

    from_env = os.getenv("AGNO_ALPACA_MCP_COMMAND", "").strip()
    if from_env:
        return ensure_serve(from_env)

    # Preferred: run from current active environment PATH.
    if shutil.which("alpaca-mcp-server"):
        return "alpaca-mcp-server serve"

    # Secondary: uvx runner (no hardcoded absolute path).
    if shutil.which("uvx"):
        return "uvx alpaca-mcp-server serve"

    # Legacy fallback kept for compatibility in local workspace installs.
    core_dir = Path(__file__).resolve().parent
    for path in (
        core_dir / "alpaca-mcp-server" / ".venv" / "bin" / "alpaca-mcp-server",
        core_dir / "mcps" / "alpaca-mcp-server" / ".venv" / "bin" / "alpaca-mcp-server",
    ):
        if path.exists():
            return f"{path} serve"
    return None


def _build_mcp_env() -> Dict[str, str]:
    """
    Build env for Alpaca MCP server.

    The MCP expects:
    - ALPACA_API_KEY
    - ALPACA_SECRET_KEY
    """
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    secret_key = os.getenv("ALPACA_SECRET_KEY", "").strip()
    if not secret_key:
        secret_key = os.getenv("ALPACA_API_SECRET", "").strip()

    env = dict(os.environ)
    if api_key:
        env["ALPACA_API_KEY"] = api_key
    if secret_key:
        env["ALPACA_SECRET_KEY"] = secret_key
    return env


def build_trading_tools(orchestrator: StrategyOrchestrator, allow_strategy_control: bool = False) -> List[Any]:
    """Create Agno tools bound to the provided orchestrator."""

    @tool
    def list_available_strategies() -> str:
        """List all strategies that can be started."""
        available = orchestrator.list_available_strategies()
        if not available:
            return "No available strategies found."
        return "Available strategies:\n- " + "\n- ".join(available)

    @tool
    def list_running_strategies() -> str:
        """List strategies currently running."""
        running = orchestrator.list_running_strategies()
        if not running:
            return "No strategies are running right now."
        return "Running strategies:\n- " + "\n- ".join(running)

    @tool
    def start_strategy(
        strategy_name: str,
        mode: str = "paper",
        parameters: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Start one strategy by name.

        Use paper mode by default. Mode can be 'paper' or 'live'.
        """
        try:
            result = orchestrator.start_strategy(
                strategy_name=strategy_name,
                parameters=parameters,
                mode=mode,
            )
            return _json_dump(result)
        except Exception as exc:
            return f"Failed to start strategy: {exc}"

    @tool
    def stop_strategy(strategy_name: str) -> str:
        """Stop one running strategy by name."""
        try:
            result = orchestrator.stop_strategy(strategy_name)
            return _json_dump(result)
        except Exception as exc:
            return f"Failed to stop strategy: {exc}"

    @tool
    def stop_all_strategies() -> str:
        """Stop all currently running strategies."""
        try:
            result = orchestrator.stop_all()
            return _json_dump(result)
        except Exception as exc:
            return f"Failed to stop all strategies: {exc}"

    @tool
    def get_strategy_status(strategy_name: str) -> str:
        """Get detailed status for one strategy by name."""
        try:
            status = orchestrator.get_strategy_status(strategy_name)
            if status is None:
                return f"Strategy '{strategy_name}' is not running and has no recent state."
            return _json_dump(status)
        except Exception as exc:
            return f"Failed to get strategy status: {exc}"

    @tool
    def get_system_status() -> str:
        """Get status for all running strategies."""
        try:
            status = orchestrator.get_all_status()
            if not status:
                return "No active strategies."
            return _json_dump(status)
        except Exception as exc:
            return f"Failed to get system status: {exc}"

    @tool
    def get_alpaca_account_status() -> str:
        """
        Get account-level Alpaca status (portfolio, cash, buying power, open positions),
        independent from active Lumibot strategies.
        """
        try:
            broker_cfg = dict(orchestrator.broker_config)
            broker_cfg.setdefault("IS_PAPER", True)
            broker = Alpaca(broker_cfg)

            account = broker.api.get_account()
            positions = broker.api.get_all_positions()

            payload = {
                "account_id": getattr(account, "id", None),
                "status": getattr(account, "status", None),
                "currency": getattr(account, "currency", None),
                "portfolio_value": float(getattr(account, "portfolio_value", 0) or 0),
                "cash": float(getattr(account, "cash", 0) or 0),
                "buying_power": float(getattr(account, "buying_power", 0) or 0),
                "equity": float(getattr(account, "equity", 0) or 0),
                "positions_count": len(positions),
                "positions": [
                    {
                        "symbol": getattr(pos, "symbol", None),
                        "qty": float(getattr(pos, "qty", 0) or 0),
                        "side": "long" if float(getattr(pos, "qty", 0) or 0) >= 0 else "short",
                        "avg_entry_price": float(getattr(pos, "avg_entry_price", 0) or 0),
                        "market_value": float(getattr(pos, "market_value", 0) or 0),
                        "unrealized_pl": float(getattr(pos, "unrealized_pl", 0) or 0),
                    }
                    for pos in positions
                ],
            }
            return _json_dump(payload)
        except Exception as exc:
            return f"Failed to get Alpaca account status: {exc}"

    @tool
    def get_strategy_pnl(
        period: str = "weekly",
        strategy_name: Optional[str] = None,
        mode: str = "paper",
    ) -> str:
        """
        Get realized PnL based on Alpaca fill activities.

        Period supports: daily, weekly, monthly.
        If strategy_name is provided, attempts to filter by client_order_id.
        """
        try:
            broker_cfg = dict(orchestrator.broker_config)
            broker_cfg.setdefault("IS_PAPER", True)
            if mode:
                broker_cfg["IS_PAPER"] = mode.strip().lower() != "live"

            summary = get_realized_pnl_summary(
                broker_config=broker_cfg,
                period=period,
                strategy_name=strategy_name,
            )
            return _json_dump(summary)
        except Exception as exc:
            return f"Failed to compute strategy PnL: {exc}"

    @tool
    def update_strategy_parameter(
        strategy_name: str,
        parameter_name: str,
        new_value: Any,
    ) -> str:
        """Update a single parameter on a running strategy."""
        try:
            parsed_value = _parse_value(new_value)
            result = orchestrator.update_parameters(
                strategy_name=strategy_name,
                params={parameter_name: parsed_value},
            )
            return _json_dump(result)
        except Exception as exc:
            return f"Failed to update parameter: {exc}"

    @tool
    def update_strategy_parameters(
        strategy_name: str,
        parameters: Dict[str, Any],
    ) -> str:
        """Update multiple parameters on a running strategy."""
        try:
            normalized = {key: _parse_value(value) for key, value in parameters.items()}
            result = orchestrator.update_parameters(
                strategy_name=strategy_name,
                params=normalized,
            )
            return _json_dump(result)
        except Exception as exc:
            return f"Failed to update parameters: {exc}"

    tools: List[Any] = [
        list_available_strategies,
        list_running_strategies,
        get_strategy_status,
        get_system_status,
        get_alpaca_account_status,
        get_strategy_pnl,
        update_strategy_parameter,
        update_strategy_parameters,
    ]
    if allow_strategy_control:
        tools.extend(
            [
                start_strategy,
                stop_strategy,
                stop_all_strategies,
            ]
        )
    return tools


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
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("AGNO_PROVIDER=anthropic set but ANTHROPIC_API_KEY is missing")
        return Claude(id=model_id or "claude-3-5-sonnet-20241022", api_key=api_key)

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("AGNO_PROVIDER=openai set but OPENAI_API_KEY is missing")
        return OpenAIChat(id=model_id or "gpt-4o-mini", api_key=api_key)

    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        return Claude(id=model_id or "claude-3-5-sonnet-20241022", api_key=anthropic_key)

    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        return OpenAIChat(id=model_id or "gpt-4o-mini", api_key=openai_key)

    return None


def create_trading_agent(orchestrator: StrategyOrchestrator) -> Optional[Agent]:
    """
    Create a conversational Agno agent.

    Returns None when no LLM API key is configured.
    """
    model = _resolve_model()
    if model is None:
        return None

    instructions = [
        "You are a trading copilot for Lumibot strategies controlled from Telegram.",
        "Never start or stop strategies from chat. Strategy lifecycle is controlled only via Telegram commands (/run, /stop).",
        "You may list strategy status and update parameters of already-running strategies.",
        "You can query account-level Alpaca status even when there are no running strategies.",
        "If the user asks about profits, losses, PnL, or performance for a period, call get_strategy_pnl.",
        "If the user asks about 'my account', 'portfolio', or 'open positions', call get_alpaca_account_status first.",
        "When Alpaca MCP tools are available, you must use them for trade intents such as buy, sell, close, cancel, or modify orders.",
        "Never answer a trade intent with only text; execute the relevant tool call and then summarize the result.",
        "If the user trade intent is ambiguous, ask one short clarification and then execute a tool.",
        "Respond in concise Spanish unless the user asks for another language.",
        "Default to paper trading unless user explicitly asks for live trading.",
        "When a strategy name is unclear, ask one brief clarification question.",
        "After each action, summarize what changed and include current run state.",
    ]

    desired_kwargs = {
        "name": "LumibotTradingAssistant",
        "model": model,
        "tools": build_trading_tools(orchestrator, allow_strategy_control=False),
        "role": "Autonomous trading optimizer for Alpaca + Lumibot",
        "goal": "Achieve a net profit target of +$1000 from a $10000 budget by actively managing parameters and executing valid tools.",
        "success_criteria": "Report measurable progress toward +$1000, preserve account operability, and use tool actions instead of text-only plans.",
        "instructions": instructions,
        "show_tool_calls": False,
        "add_history_to_messages": True,
        "num_history_runs": 10,
        "markdown": False,
    }

    # Keep compatibility across agno versions by passing only supported kwargs.
    accepted = set(inspect.signature(Agent.__init__).parameters.keys())
    filtered_kwargs = {key: value for key, value in desired_kwargs.items() if key in accepted}

    agent = Agent(**filtered_kwargs)

    # Attach optional MCP configuration to the agent instance.
    # This keeps constructor compatibility across Agno versions.
    mcp_command = _resolve_alpaca_mcp_command()
    setattr(agent, "_alpaca_mcp_command", mcp_command)
    setattr(agent, "_alpaca_mcp_env", _build_mcp_env())
    setattr(agent, "_orchestrator", orchestrator)

    return agent


def run_agent_message(agent: Agent, message: str, user_id: str, session_id: str) -> str:
    """Run one message through the agent and return plain text output."""
    logger = logging.getLogger(__name__)
    mcp_command = getattr(agent, "_alpaca_mcp_command", None)
    trade_intent_hints = ("compra", "compre", "comprar", "buy", "vende", "vender", "sell", "cerrar", "close", "cancelar", "cancel")
    lower_message = message.lower()
    is_trade_intent = any(hint in lower_message for hint in trade_intent_hints)
    pnl_intent_hints = ("pnl", "ganancia", "ganancias", "perdida", "pérdida", "perdidas", "pérdidas", "profit", "rendimiento", "performance")
    is_pnl_intent = any(hint in lower_message for hint in pnl_intent_hints)

    def _pnl_period_hint(text: str) -> str:
        if any(token in text for token in ("hoy", "today", "diario", "daily")):
            return "daily"
        if any(token in text for token in ("semana", "weekly", "week")):
            return "weekly"
        if any(token in text for token in ("mes", "mensual", "monthly", "month")):
            return "monthly"
        return "daily"

    def _pnl_mode_hint(text: str) -> str:
        if "live" in text or "real" in text:
            return "live"
        return "paper"

    def _detect_strategy_name(text: str) -> Optional[str]:
        orchestrator = getattr(agent, "_orchestrator", None)
        if orchestrator is None:
            return None
        try:
            available = orchestrator.list_available_strategies()
        except Exception:
            return None
        for name in available:
            if name.lower() in text:
                return name
        return None

    def _direct_pnl_response() -> Optional[str]:
        orchestrator = getattr(agent, "_orchestrator", None)
        if orchestrator is None:
            return None
        period = _pnl_period_hint(lower_message)
        mode = _pnl_mode_hint(lower_message)
        strategy_name = _detect_strategy_name(lower_message)
        try:
            logger.info(
                "PNL request: period=%s mode=%s strategy=%s",
                period,
                mode,
                strategy_name,
            )
            broker_cfg = dict(orchestrator.broker_config)
            broker_cfg.setdefault("IS_PAPER", True)
            broker_cfg["IS_PAPER"] = mode != "live"
            summary = get_realized_pnl_summary(
                broker_config=broker_cfg,
                period=period,
                strategy_name=strategy_name,
            )
            return _json_dump(summary)
        except Exception as exc:
            logger.exception("Failed to compute PnL: %s", exc)
            return f"No se pudo calcular el PnL: {exc}"

    if is_pnl_intent:
        direct = _direct_pnl_response()
        if direct is not None:
            return direct

    if mcp_command:
        async def _run_with_mcp() -> Any:
            mcp_tools = MCPTools(
                command=mcp_command,
                env=getattr(agent, "_alpaca_mcp_env", None),
                transport="stdio",
            )
            async with mcp_tools:
                original_tools = list(agent.tools or [])
                try:
                    agent.tools = original_tools + [mcp_tools]
                    # Force tool rebuild with MCP functions included.
                    if hasattr(agent, "_rebuild_tools"):
                        agent._rebuild_tools = True  # type: ignore[attr-defined]
                    final_message = message
                    if is_trade_intent:
                        final_message = (
                            "EJECUTA herramientas para esta intención de trading; no respondas solo texto.\n"
                            f"Solicitud del usuario: {message}"
                        )
                    elif is_pnl_intent:
                        period = _pnl_period_hint(lower_message)
                        mode = _pnl_mode_hint(lower_message)
                        final_message = (
                            "EJECUTA la herramienta get_strategy_pnl; no respondas solo texto.\n"
                            f"Usa period='{period}' y mode='{mode}'. "
                            "Si el usuario menciona una estrategia, pasa strategy_name. "
                            f"Solicitud del usuario: {message}"
                        )
                    return await agent.arun(final_message, user_id=user_id, session_id=session_id)
                finally:
                    agent.tools = original_tools
                    if hasattr(agent, "_rebuild_tools"):
                        agent._rebuild_tools = True  # type: ignore[attr-defined]

        response = asyncio.run(_run_with_mcp())
    else:
        final_message = message
        if is_pnl_intent:
            period = _pnl_period_hint(lower_message)
            mode = _pnl_mode_hint(lower_message)
            final_message = (
                "EJECUTA la herramienta get_strategy_pnl; no respondas solo texto.\n"
                f"Usa period='{period}' y mode='{mode}'. "
                "Si el usuario menciona una estrategia, pasa strategy_name. "
                f"Solicitud del usuario: {message}"
            )
        response = agent.run(final_message, user_id=user_id, session_id=session_id)

    content = getattr(response, "content", None)
    if content is None:
        return "No se pudo generar una respuesta."
    if isinstance(content, str):
        return content
    return _json_dump(content)
