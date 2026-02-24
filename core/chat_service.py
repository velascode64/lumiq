"""
Reusable chat/command handling for API and Telegram clients.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    from .agno_trading_agent import run_agent_message
    from .agno_team_orchestrator import run_team_message
    from .alpaca_pnl import get_pnl_report
    from .alerts.alert_factory import create_rsi_oversold, create_rsi_overbought
except ImportError:
    from agno_trading_agent import run_agent_message
    from agno_team_orchestrator import run_team_message
    from alpaca_pnl import get_pnl_report
    from alerts.alert_factory import create_rsi_oversold, create_rsi_overbought


logger = logging.getLogger(__name__)


def _parse_value(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        lower = text.lower()
        if lower == "true":
            return True
        if lower == "false":
            return False
        return text


def _parse_key_value_args(tokens: List[str]) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    for token in tokens:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        key = key.strip()
        if not key:
            continue
        params[key] = _parse_value(value.strip())
    return params


def _parse_pnl_args(args: List[str]) -> Dict[str, Any]:
    period = "daily"
    mode = "paper"
    for arg in args:
        lower = arg.lower()
        if lower in {"daily", "weekly", "monthly"}:
            period = lower
        elif lower in {"paper", "live"}:
            mode = lower
        elif lower.startswith("mode="):
            value = lower.split("=", 1)[1].strip()
            if value in {"paper", "live"}:
                mode = value
    return {"period": period, "mode": mode}


def _format_status(status: Dict[str, Any]) -> str:
    positions = status.get("positions") or []
    lines = [
        f"Strategy: {status.get('strategy')}",
        f"Status: {status.get('status')}",
        f"Mode: {status.get('mode')}",
        f"Thread alive: {status.get('thread_alive')}",
        f"Portfolio: {status.get('portfolio_value')}",
        f"Cash: {status.get('cash')}",
        f"Positions: {len(positions)}",
        f"Started: {status.get('started_at')}",
    ]
    if status.get("ended_at"):
        lines.append(f"Ended: {status.get('ended_at')}")
    if status.get("last_error"):
        lines.append(f"Last error: {status.get('last_error')}")
    return "\n".join(lines)


def _format_pnl_summary(summary: Dict[str, Any]) -> str:
    def _fmt_money(value: Any) -> str:
        if value is None:
            return "N/D"
        try:
            return f"${float(value):,.2f}"
        except Exception:
            return str(value)

    daily = summary.get("daily_pnl")
    weekly = summary.get("weekly_pnl")
    alltime = summary.get("alltime_pnl")
    lines = [
        "P&L Report",
        f"Equity: {_fmt_money(summary.get('account_equity'))}",
        f"Cash: {_fmt_money(summary.get('start_portfolio_value'))}",
        f"Hoy: {_fmt_money(daily)}",
        f"Semana: {_fmt_money(weekly)}",
        f"All-Time: {_fmt_money(alltime)}",
    ]
    return "\n".join(lines)


@dataclass
class ChatResponse:
    text: str
    parse_mode: Optional[str] = None


class ChatService:
    def __init__(self, runtime):
        self.runtime = runtime

    def help_text(self) -> str:
        mode_text = "Conversational Agno mode: ON" if (self.runtime.team or self.runtime.agent) else "Conversational Agno mode: OFF"
        return (
            "Lumiq trading bot is ready.\n\n"
            f"{mode_text}\n\n"
            "Commands:\n"
            "/strategies\n"
            "/running\n"
            "/run <strategy> [mode=paper|live] [key=value ...]\n"
            "/status [strategy]\n"
            "/set <strategy> <param> <value>\n"
            "/stop [strategy|all]\n"
            "/kill <strategy>\n"
            "/pnl [mode=paper|live]\n"
            "/list alerts\n"
        )

    def get_alerts_summary(self, chat_id: Optional[int] = None) -> str:
        alert_system = self.runtime.alert_system
        if alert_system is None:
            return "Alert system is not available."
        rules = alert_system.list_rules()
        if chat_id is not None:
            rules = [r for r in rules if int(r.get("chat_id") or 0) == int(chat_id)]
        active = [r for r in rules if r.get("active", True)]
        if not active:
            return "No hay alertas activas."
        lines = ["Alertas activas:"]
        for rule in active:
            lines.append(f"- {rule.get('symbol')} | {rule.get('type')} | {rule.get('id')}")
        return "\n".join(lines)

    def _extract_symbols(self, text: str) -> List[str]:
        alias_map = {"NVIDIA": "NVDA"}
        stopwords = {
            "RSI", "OVERBOUGHT", "OVERSOLD", "SOBRECOMPRADA", "SOBRECOMPRADO",
            "SOBREVENDIDA", "SOBREVENDIDO", "PARA", "QUIERO", "CREA", "ALERTA",
            "EL", "LA", "LOS", "LAS", "Y", "AND", "DE", "DEL", "EN", "UN", "UNA",
        }
        symbols: List[str] = []
        for token in re.findall(r"\b[A-Za-z]{2,6}[/-][A-Za-z]{2,6}\b", text):
            symbols.append(token.upper().replace("-", "/"))
        for token in re.findall(r"\b[A-Za-z]{2,10}\b", text):
            upper = token.upper()
            if upper in stopwords:
                continue
            mapped = alias_map.get(upper, upper)
            if mapped not in symbols and mapped.isalpha():
                symbols.append(mapped)
        return symbols

    def _maybe_handle_rsi_natural_language(self, text: str, chat_id: int) -> Optional[str]:
        alert_system = self.runtime.alert_system
        if alert_system is None:
            return None
        lower = text.lower()
        is_oversold = any(t in lower for t in {"oversold", "sobrevendida", "sobrevendido"})
        is_overbought = any(t in lower for t in {"overbought", "sobrecomprada", "sobrecomprado"})
        if not is_oversold and not is_overbought:
            return None
        symbols = self._extract_symbols(text)
        if not symbols:
            return "Dime el simbolo (ej: PLTR, NVDA) para crear la alerta RSI."
        created: List[Dict[str, Any]] = []
        for index, symbol in enumerate(symbols):
            rule = create_rsi_oversold(symbol) if is_oversold and not is_overbought else create_rsi_overbought(symbol)
            rule["id"] = f"{symbol}-{int(time.time())}-{index}"
            rule["chat_id"] = int(chat_id)
            created.append(alert_system.add_rule(rule))
        kind = "oversold" if is_oversold and not is_overbought else "overbought"
        return "RSI " + kind + " creado para: " + ", ".join(str(r.get("symbol")) for r in created)

    def handle_command(self, chat_id: int, user_id: int, command: str, args: List[str]) -> ChatResponse:
        orchestrator = self.runtime.orchestrator
        if command in {"start", "help"}:
            return ChatResponse(self.help_text(), parse_mode=None)

        if command == "list" and args and args[0].lower() == "alerts":
            return ChatResponse(self.get_alerts_summary(chat_id), parse_mode=None)

        if command == "strategies":
            available = orchestrator.list_available_strategies()
            return ChatResponse("Available strategies:\n- " + "\n- ".join(available) if available else "No strategies discovered.")

        if command == "running":
            running = orchestrator.list_running_strategies()
            return ChatResponse("Running strategies:\n- " + "\n- ".join(running) if running else "No active strategies.")

        if command == "run":
            if not args:
                return ChatResponse("Usage:\n/run <strategy> [mode=paper|live] [key=value ...]")
            strategy_name = args[0]
            extra = _parse_key_value_args(args[1:])
            mode = str(extra.pop("mode", "paper"))
            result = orchestrator.start_strategy(strategy_name=strategy_name, parameters=extra or None, mode=mode)
            return ChatResponse(json.dumps(result, ensure_ascii=True, indent=2))

        if command == "stop":
            arg = args[0] if args else ""
            if arg.lower().strip() == "all":
                return ChatResponse(json.dumps(orchestrator.stop_all(), ensure_ascii=True, indent=2))
            if arg:
                return ChatResponse(json.dumps(orchestrator.stop_strategy(arg), ensure_ascii=True, indent=2))
            running = orchestrator.list_running_strategies()
            if not running:
                return ChatResponse("No active strategies.")
            if len(running) == 1:
                return ChatResponse(json.dumps(orchestrator.stop_strategy(running[0]), ensure_ascii=True, indent=2))
            return ChatResponse("Multiple strategies are running. Use /stop <strategy> or /stop all.")

        if command == "kill":
            if not args:
                return ChatResponse("Usage:\n/kill <strategy>")
            result = orchestrator.kill_strategy(args[0])
            return ChatResponse(json.dumps(result, ensure_ascii=True, indent=2))

        if command == "status":
            if args:
                status = orchestrator.get_strategy_status(args[0])
                return ChatResponse(_format_status(status) if status else "Strategy status not found.")
            all_status = orchestrator.get_all_status()
            if not all_status:
                return ChatResponse("No active strategies.")
            return ChatResponse("\n\n".join(_format_status(s) for s in all_status.values() if s))

        if command == "set":
            if len(args) < 3:
                return ChatResponse("Usage:\n/set <strategy> <param> <value>")
            strategy_name = args[0]
            param_name = args[1]
            value = _parse_value(" ".join(args[2:]))
            result = orchestrator.update_parameters(strategy_name, {param_name: value})
            return ChatResponse(json.dumps(result, ensure_ascii=True, indent=2))

        if command == "pnl":
            parsed = _parse_pnl_args(args)
            mode = parsed["mode"]
            try:
                broker_cfg = dict(orchestrator.broker_config)
                broker_cfg.setdefault("IS_PAPER", True)
                broker_cfg["IS_PAPER"] = mode != "live"
                report = get_pnl_report(broker_config=broker_cfg)
                summary = {
                    "account_equity": report.equity,
                    "start_portfolio_value": report.base_value or report.cash,
                    "daily_pnl": report.pnl_today,
                    "weekly_pnl": report.pnl_week,
                    "alltime_pnl": report.pnl_alltime,
                }
                return ChatResponse(_format_pnl_summary(summary), parse_mode=None)
            except Exception as exc:
                logger.exception("PNL command failed: %s", exc)
                return ChatResponse(f"No se pudo calcular el PnL: {exc}")

        return ChatResponse("Unknown command. Use /help")

    def handle_chat(self, chat_id: int, user_id: int, text: str) -> ChatResponse:
        if self.runtime.alert_system is not None:
            self.runtime.alert_system.set_active_chat_id(chat_id)
            rsi_response = self._maybe_handle_rsi_natural_language(text, chat_id)
            if rsi_response is not None:
                return ChatResponse(rsi_response, parse_mode=None)

        if self.runtime.team is not None:
            session_id = f"telegram-{chat_id}"
            response = run_team_message(self.runtime.team, text, user_id=str(user_id), session_id=session_id)
            return ChatResponse(response, parse_mode=None)

        if self.runtime.agent is not None:
            session_id = f"telegram-{chat_id}"
            response = run_agent_message(self.runtime.agent, text, user_id=str(user_id), session_id=session_id)
            return ChatResponse(response, parse_mode=None)

        return ChatResponse("Conversational mode requires OPENAI_API_KEY or ANTHROPIC_API_KEY.", parse_mode=None)

    def handle_text(self, chat_id: int, user_id: int, text: str) -> ChatResponse:
        text = (text or "").strip()
        if not text:
            return ChatResponse("", parse_mode=None)
        if text.startswith("/"):
            tokens = text.split()
            command = tokens[0][1:].split("@", 1)[0].lower()
            return self.handle_command(chat_id, user_id, command, tokens[1:])
        return self.handle_chat(chat_id, user_id, text)
