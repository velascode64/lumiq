"""
Reusable chat/command handling for API and Telegram clients.
"""

from __future__ import annotations

import json
import logging
import re
import shlex
import shutil
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    from ...agents.agno.members.trading_agent_compat import run_agent_message
    from ...agents.agno.members.live_trading_agent import run_live_trading_message
    from ...agents.agno.team.orchestrator import run_team_message
    from ...platform.pnl.alpaca_pnl import get_pnl_report
    from ...platform.alerts.alert_factory import create_rsi_oversold, create_rsi_overbought
except ImportError:
    from agents.agno.members.trading_agent_compat import run_agent_message
    from agents.agno.members.live_trading_agent import run_live_trading_message
    from agents.agno.team.orchestrator import run_team_message
    from platform.pnl.alpaca_pnl import get_pnl_report
    from platform.alerts.alert_factory import create_rsi_oversold, create_rsi_overbought


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
        self._chat_trade_mode: Dict[int, str] = {}

    def _get_trade_mode(self, chat_id: int) -> str:
        return self._chat_trade_mode.get(int(chat_id), "paper")

    def _set_trade_mode(self, chat_id: int, mode: str) -> str:
        normalized = (mode or "paper").strip().lower()
        if normalized not in {"paper", "live"}:
            raise ValueError("mode must be paper or live")
        self._chat_trade_mode[int(chat_id)] = normalized
        return normalized

    def _is_trade_intent_text(self, text: str) -> bool:
        lower = (text or "").lower()
        hints = ("compra", "compre", "comprar", "buy", "vende", "vender", "sell", "cerrar", "close", "cancelar", "cancel")
        return any(h in lower for h in hints)

    def _apply_trade_mode_policy(self, chat_id: int, text: str) -> str:
        if not self._is_trade_intent_text(text):
            return text
        mode = self._get_trade_mode(chat_id)
        return (
            f"Execution mode policy for this chat: {mode.upper()} only unless changed via /trade_mode. "
            "Do not ask 'paper or live'. Use the configured mode directly. "
            "If order type is omitted, default to MARKET. "
            "If side + symbol + amount/qty are explicit, execute without asking for confirmation.\n"
            f"User request: {text}"
        )

    def examples_text(self, agent: Optional[str] = None) -> str:
        key = (agent or "all").strip().lower()
        aliases = {
            "technical": "technicals",
            "tecnico": "technicals",
            "tecnicos": "technicals",
            "technicals": "technicals",
            "ta": "technicals",
            "alert": "alerts",
            "alerts": "alerts",
            "alertas": "alerts",
            "trading": "trading",
            "trade": "trading",
            "estrategias": "trading",
            "strategy": "trading",
            "all": "all",
            "todos": "all",
        }
        key = aliases.get(key, key if key in {"technicals", "alerts", "trading"} else "all")

        sections: List[str] = []
        if key in {"all", "technicals"}:
            sections.append(
                "\n".join(
                    [
                        "Ejemplos - Agente de Technicals",
                        "- ¿Cuántas veces ETH tocó 3000 este año?",
                        "- ¿Cuántas veces AAPL cerró por encima de 180 en 6 meses?",
                        "- ¿ETH está en sobrecompra o sobreventa en 1D?",
                        "- ¿Cuántas veces RSI de BTC pasó de 70 y qué pasó después?",
                        "- ¿Cuántas caídas mayores a 3% tuvo ETH este año?",
                        "- ¿Ese nivel (2900) actuó como soporte o se rompió?",
                        "- ¿Hubo rebote o breakdown después de tocar 500 en SPY?",
                        "- Explícame simple qué dicen RSI, MACD y Bollinger de NVDA hoy.",
                    ]
                )
            )

        if key in {"all", "alerts"}:
            sections.append(
                "\n".join(
                    [
                        "Ejemplos - Agente de Alertas",
                        "- Créame una alerta de caída de 2% para ETH",
                        "- Avísame cuando BTC llegue a 70000",
                        "- Crea alerta RSI oversold para NVDA",
                        "- Crea alerta RSI overbought para TSLA",
                        "- Crea alerta de cruce MACD alcista para AAPL",
                        "- Crea alerta Bollinger middle cross para SPY",
                        "- Lista mis alertas activas",
                        "- Desactiva la alerta <rule_id>",
                    ]
                )
            )

        if key in {"all", "trading"}:
            sections.append(
                "\n".join(
                    [
                        "Ejemplos - Agente de Trading / Core",
                        "- ¿Qué estrategias están corriendo?",
                        "- Dame el estado de ETHMomentumLive",
                        "- ¿Cómo va el PnL de esta semana?",
                        "- ¿Cuál es el estado de mi cuenta Alpaca y posiciones abiertas?",
                        "- Ajusta el parámetro risk_per_trade de ETHMomentumLive a 0.01",
                        "",
                        "Comandos útiles:",
                        "- /strategies",
                        "- /running",
                        "- /status [strategy]",
                        "- /pnl [mode=paper|live]",
                        "- /run <strategy> mode=paper",
                        "- /stop <strategy>",
                    ]
                )
            )

        header = "Usa /examples technicals | /examples alerts | /examples trading para filtrar.\n"
        return header + "\n\n".join(sections)

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
            "/examples [technicals|alerts|trading]\n"
            "/report <pre_open|midday|close|weekly>\n"
            "/news [watchlist|group <name>]\n"
            "/trade_mode [paper|live]\n"
            "/live_trading_options\n"
            "/watchlist [list|groups|add|fav] ...\n"
        )

    def _describe_live_trading_options(self) -> str:
        team = getattr(self.runtime, "team", None)
        if team is None:
            return "Agno Team is not enabled."
        target_id = "livetradingagent"

        members = list(getattr(team, "members", None) or [])
        if not members:
            return "Team has no members loaded."

        selected = None
        for member in members:
            name = str(getattr(member, "name", "") or "")
            if name.lower() == target_id:
                selected = member
                break
            if target_id in {name.lower(), getattr(member, "agent_id", "")}:
                selected = member
                break

        if selected is None:
            available = ", ".join(str(getattr(m, "name", "?")) for m in members)
            return f"LiveTradingAgent not found in team. Available: {available}"

        name = str(getattr(selected, "name", selected.__class__.__name__))
        member_id = name.lower()
        tools = list(getattr(selected, "tools", None) or [])
        tool_names = []
        for t in tools:
            tool_names.append(
                str(
                    getattr(t, "name", None)
                    or getattr(t, "__name__", None)
                    or t.__class__.__name__
                )
            )
        gateway = getattr(selected, "_live_broker_gateway", None)
        lines = [
            "Live Trading Options (Lumibot Broker Tools)",
            f"- Agent: {name}",
            f"- Team member ID: {member_id}",
            f"- Broker gateway attached: {'YES' if gateway is not None else 'NO'}",
            f"- Local agent tools ({len(tool_names)}): {', '.join(tool_names) if tool_names else 'none'}",
            "- Supported intents: buy, sell, close position, cancel order(s), account/positions/orders queries",
            "- Defaults: conversational mode uses /trade_mode setting; order type defaults to MARKET if omitted",
            "- Fast path: explicit simple market orders (e.g. buy $1000 ETH/USD) bypass LLM tool selection for lower latency",
        ]
        if gateway is None:
            lines.append("- Status: live broker gateway is not attached, so manual broker execution will not run.")
        else:
            lines.append("- Status: broker tools are attached. If an order still does not execute, inspect parsing/tool invocation and broker API errors.")
        return "\n".join(lines)

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
        alias_map = {
            "NVIDIA": "NVDA",
            "CLOUDFLARE": "NET",
            "CLOUCLDFLARE": "NET",
            "ZSCALER": "ZS",
            "INFOSYS": "INFY",
            "ALPHABET": "GOOGL",
            "GOOGLE": "GOOGL",
            "AMAZON": "AMZN",
            "APPLE": "AAPL",
            "TESLA": "TSLA",
            "META": "META",
            "NETFLIX": "NFLX",
            "UBER": "UBER",
            "OKTA": "OKTA",
        }
        stopwords = {
            "RSI", "OVERBOUGHT", "OVERSOLD", "SOBRECOMPRADA", "SOBRECOMPRADO",
            "SOBREVENDIDA", "SOBREVENDIDO", "PARA", "QUIERO", "CREA", "ALERTA",
            "EL", "LA", "LOS", "LAS", "Y", "AND", "DE", "DEL", "EN", "UN", "UNA",
            "NUEVO", "NUEVA", "STOCKS", "STOCK", "ACCIONES", "ACCION",
        }
        symbols: List[str] = []
        for token in re.findall(r"\b[A-Za-z]{2,6}[/-][A-Za-z]{2,6}\b", text):
            symbols.append(token.upper().replace("-", "/"))
        for token in re.findall(r"\b[A-Za-z]{2,16}\b", text):
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

    def _maybe_handle_watchlist_natural_language(self, text: str) -> Optional[str]:
        store = getattr(self.runtime, "watchlist_store", None)
        if store is None:
            return None
        lower = text.lower()
        delete_like = any(t in lower for t in {"borra", "elimina", "quita"})
        if delete_like:
            m_group = re.search(r"(?:borra|elimina|quita)\s+(?:grupo\s+)?([A-Za-z0-9_-]+)", text, flags=re.IGNORECASE)
            if m_group:
                target = m_group.group(1).strip()
                if "favorito" in lower and "listado" in lower:
                    try:
                        result = store.remove_ticker(target, from_favorites=True)
                        if result.get("removed_from_favorites"):
                            return f"Quité {result['ticker']} del listado de favoritos."
                        return f"{result['ticker']} no estaba en favoritos."
                    except Exception as exc:
                        return f"No se pudo borrar de favoritos: {exc}"
                try:
                    cfg = store.load()
                    if target.lower() in (cfg.groups or {}):
                        result = store.remove_group(target)
                        return f"Grupo '{result['group']}' eliminado ({result['tickers_removed_count']} tickers)."
                except Exception:
                    pass
                try:
                    result = store.remove_ticker(target, from_favorites=True)
                    if result.get("removed_from_groups") or result.get("removed_from_favorites"):
                        return (
                            f"Ticker {result['ticker']} eliminado de grupos={result.get('removed_from_groups') or []}"
                            + (" y favoritos" if result.get("removed_from_favorites") else "")
                        )
                    return f"No encontré {target} en watchlist/favoritos."
                except Exception as exc:
                    return f"No se pudo borrar: {exc}"
        if not any(token in lower for token in {"watchlist", "favorito", "favoritos", "grupo", "grupos"}):
            return None
        list_like = any(token in lower for token in {
            "que watchlist", "qué watchlist", "watchlist tenemos",
            "listado", "lista", "listar", "muestra", "muéstra", "muestr",
            "favoritos", "favorirtos",
        })
        modify_like = any(token in lower for token in {"crea", "crear", "agrega", "añade", "anade"})
        if list_like and not modify_like:
            # "que watchlist tenemos", "listado de favoritos", etc.
            return store.summary_text()
        if (
            any(token in lower for token in {"que grupos", "qué grupos", "grupos de watchlist", "watchlist tienes", "watchlist tienes"})
            or (("grupo" in lower or "grupos" in lower) and any(t in lower for t in {"tienes", "hay", "lista", "listar", "muestr"}))
        ):
            return store.summary_text()
        is_create_group = ("grupo" in lower) and any(t in lower for t in {"crea", "crear", "agrega", "añade", "anade"})
        is_add_fav = any(t in lower for t in {"favoritos", "favorito"}) and any(t in lower for t in {"agrega", "añade", "anade", "crea", "crear"})
        if not is_create_group and not is_add_fav:
            return None

        group_name: Optional[str] = None
        m = re.search(r"(?:llam[ae]\w*|nombre(?:ado)?(?:\s+de)?)\s+([A-Za-z0-9_-]+)", text, flags=re.IGNORECASE)
        if m:
            group_name = m.group(1).strip().lower()
        if is_create_group and not group_name:
            m2 = re.search(r"grupo(?:\s+de\s+favoritos)?\s+(?:que\s+se\s+llame\s+)?([A-Za-z0-9_-]+)", text, flags=re.IGNORECASE)
            if m2:
                candidate = m2.group(1).strip().lower()
                if candidate not in {"con", "las", "los", "siguientes", "stocks", "acciones"}:
                    group_name = candidate

        symbols = self._extract_symbols(text)
        noise = {
            "CREA", "CREAR", "GRUPO", "FAVORITO", "FAVORITOS", "STOCK", "STOCKS", "ACCION", "ACCIONES",
            "SIGUIENTES", "CON", "QUE", "SE", "LLAME", "LAS", "LOS", "DE", "Y", "EL", "LA", "WATCHLIST",
        }
        symbols = [s for s in symbols if s.upper() not in noise and len(s) >= 2]
        if group_name:
            symbols = [s for s in symbols if s.upper() != group_name.upper()]
        # De-duplicate preserving order
        seen = set()
        symbols = [s for s in symbols if not (s in seen or seen.add(s))]
        if not symbols:
            return None

        if is_create_group:
            if not group_name:
                group_name = "favorites"
            added = []
            for s in symbols:
                try:
                    store.add_ticker(s, groups=[group_name], favorite=False)
                    added.append(s)
                except Exception:
                    continue
            if not added:
                return "No pude agregar tickers al grupo."
            return f"Grupo '{group_name}' actualizado con {len(added)} tickers: " + ", ".join(added)

        if is_add_fav:
            added = []
            for s in symbols:
                try:
                    store.add_favorite(s)
                    added.append(s)
                except Exception:
                    continue
            if added:
                return "Favoritos actualizados: " + ", ".join(added)
        return None

    def _maybe_handle_report_natural_language(self, chat_id: int, text: str) -> Optional[str]:
        scheduler = getattr(self.runtime, "portfolio_review_scheduler", None)
        if scheduler is None:
            return None
        lower = text.lower()
        if "reporte" not in lower and "analisis" not in lower and "análisis" not in lower:
            return None
        if not any(t in lower for t in {"dia", "día", "diario", "hoy", "weekly", "seman", "pre apertura", "apertura", "cierre", "medio"}):
            return None

        kind = "close"
        if "weekly" in lower or "seman" in lower:
            kind = "weekly"
        elif "pre apertura" in lower or "preapertura" in lower:
            kind = "pre_open"
        elif "medio" in lower or "mediod" in lower:
            kind = "midday"
        elif "cierre" in lower or "hoy" in lower or "día" in lower or "dia" in lower or "diario" in lower:
            kind = "close"

        group_name = None
        m = re.search(r"grupo\s+([A-Za-z0-9_-]+)", text, flags=re.IGNORECASE)
        if m:
            group_name = m.group(1).strip().lower()
        if not group_name:
            store = getattr(self.runtime, "watchlist_store", None)
            if store is not None and hasattr(store, "load"):
                try:
                    cfg = store.load()
                    for g in (cfg.groups or {}).keys():
                        if re.search(rf"\\b{re.escape(g)}\\b", lower):
                            group_name = g
                            break
                except Exception:
                    pass
        if group_name:
            try:
                started = scheduler.trigger_async_with_group(kind, chat_id=chat_id, source="manual", group_name=group_name)
            except Exception as exc:
                return f"No se pudo iniciar reporte del grupo {group_name}: {exc}"
            if started:
                return f"Generando reporte {kind} del grupo {group_name}... te lo envío por Telegram cuando esté listo."
            return f"Ya hay un reporte {kind} del grupo {group_name} en ejecución para este chat."

        try:
            started = scheduler.trigger_async(kind, chat_id=chat_id, source="manual")
        except Exception as exc:
            return f"No se pudo iniciar reporte {kind}: {exc}"
        if started:
            return f"Generando reporte {kind}... te lo envío por Telegram cuando esté listo."
        return f"Ya hay un reporte {kind} en ejecución para este chat."

    def handle_command(self, chat_id: int, user_id: int, command: str, args: List[str]) -> ChatResponse:
        orchestrator = self.runtime.orchestrator
        if command in {"start", "help"}:
            return ChatResponse(self.help_text(), parse_mode=None)

        if command == "list" and args and args[0].lower() == "alerts":
            return ChatResponse(self.get_alerts_summary(chat_id), parse_mode=None)

        if command == "examples":
            topic = args[0] if args else None
            return ChatResponse(self.examples_text(topic), parse_mode=None)

        if command == "report":
            if not args:
                return ChatResponse("Uso: /report <pre_open|midday|close|weekly>", parse_mode=None)
            scheduler = getattr(self.runtime, "portfolio_review_scheduler", None)
            if scheduler is None:
                return ChatResponse("Portfolio review scheduler no disponible.", parse_mode=None)
            kind = args[0].lower()
            try:
                started = scheduler.trigger_async(kind, chat_id=chat_id, source="manual")
            except Exception as exc:
                return ChatResponse(f"Error iniciando reporte: {exc}", parse_mode=None)
            if started:
                return ChatResponse(f"Generando reporte {kind}... te lo envío por Telegram cuando esté listo.", parse_mode=None)
            return ChatResponse(f"Ya hay un reporte {kind} en ejecución para este chat.", parse_mode=None)

        if command == "news":
            scheduler = getattr(self.runtime, "news_scheduler", None)
            if scheduler is None:
                return ChatResponse("News scheduler no disponible.", parse_mode=None)
            group_name = None
            if args and args[0].lower() == "group":
                if len(args) < 2:
                    return ChatResponse("Uso: /news [watchlist|group <name>]", parse_mode=None)
                group_name = args[1]
            elif args and args[0].lower() not in {"watchlist", "today", "hoy"}:
                group_name = args[0]
            started = scheduler.trigger_async(chat_id=chat_id, source="manual", group_name=group_name)
            if started:
                scope = f" del grupo {group_name}" if group_name else ""
                return ChatResponse(f"Generando digest de noticias{scope}... te lo envío por Telegram cuando esté listo.", parse_mode=None)
            return ChatResponse("Ya hay un digest de noticias en ejecución.", parse_mode=None)

        if command == "trade_mode":
            if not args:
                return ChatResponse(f"Current conversational trade mode: {self._get_trade_mode(chat_id)}", parse_mode=None)
            try:
                mode = self._set_trade_mode(chat_id, args[0])
            except Exception as exc:
                return ChatResponse(f"Error: {exc}", parse_mode=None)
            return ChatResponse(f"Conversational trade mode set to {mode}.", parse_mode=None)

        if command in {"live_trading_options", "agent_tools", "tools"}:
            return ChatResponse(self._describe_live_trading_options(), parse_mode=None)

        if command == "watchlist":
            store = getattr(self.runtime, "watchlist_store", None)
            if store is None:
                return ChatResponse("Watchlist store no disponible.", parse_mode=None)
            action = (args[0].lower() if args else "list")
            if action in {"list", "groups"}:
                return ChatResponse(store.summary_text(), parse_mode=None)
            if action in {"add", "fav", "favorite", "remove", "rm", "delete", "remove-group", "rm-group", "delete-group"}:
                if len(args) < 2:
                    return ChatResponse("Uso: /watchlist add <ticker> [grupo1,grupo2] | /watchlist fav <ticker> | /watchlist remove <ticker> [grupo|favorites] | /watchlist remove-group <grupo>", parse_mode=None)
                ticker = args[1]
                try:
                    if action in {"fav", "favorite"}:
                        result = store.add_favorite(ticker)
                    elif action in {"remove-group", "rm-group", "delete-group"}:
                        result = store.remove_group(ticker)
                        return ChatResponse(f"Watchlist actualizado: {json.dumps(result, ensure_ascii=True)}", parse_mode=None)
                    elif action in {"remove", "rm", "delete"}:
                        group_name = args[2] if len(args) >= 3 and args[2].lower() not in {"favorites", "favoritos"} else None
                        from_favorites = len(args) >= 3 and args[2].lower() in {"favorites", "favoritos"}
                        result = store.remove_ticker(ticker, group_name=group_name, from_favorites=from_favorites)
                    else:
                        groups = []
                        favorite = False
                        if len(args) >= 3:
                            groups = [g.strip() for g in args[2].split(",") if g.strip()]
                        if len(args) >= 4:
                            favorite = args[3].strip().lower() in {"1", "true", "yes", "fav", "favorite"}
                        result = store.add_ticker(ticker, groups=groups, favorite=favorite)
                    return ChatResponse(f"Watchlist actualizado: {json.dumps(result, ensure_ascii=True)}", parse_mode=None)
                except Exception as exc:
                    return ChatResponse(f"No se pudo actualizar watchlist: {exc}", parse_mode=None)
            return ChatResponse("Uso: /watchlist [list|groups|add|fav|remove|remove-group] ...", parse_mode=None)

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
        watchlist_response = self._maybe_handle_watchlist_natural_language(text)
        if watchlist_response is not None:
            return ChatResponse(watchlist_response, parse_mode=None)

        report_response = self._maybe_handle_report_natural_language(chat_id, text)
        if report_response is not None:
            return ChatResponse(report_response, parse_mode=None)

        if self.runtime.alert_system is not None:
            self.runtime.alert_system.set_active_chat_id(chat_id)
            rsi_response = self._maybe_handle_rsi_natural_language(text, chat_id)
            if rsi_response is not None:
                return ChatResponse(rsi_response, parse_mode=None)

        live_trading_agent = getattr(self.runtime, "live_trading_agent", None)
        if live_trading_agent is not None and self._is_trade_intent_text(text):
            session_id = f"telegram-{chat_id}"
            response = run_live_trading_message(
                live_trading_agent,
                text,
                user_id=str(user_id),
                session_id=session_id,
                trade_execution_mode=self._get_trade_mode(chat_id),
            )
            return ChatResponse(response, parse_mode=None)

        if self.runtime.team is not None:
            session_id = f"telegram-{chat_id}"
            response = run_team_message(
                self.runtime.team,
                self._apply_trade_mode_policy(chat_id, text),
                user_id=str(user_id),
                session_id=session_id,
            )
            return ChatResponse(response, parse_mode=None)

        if self.runtime.agent is not None:
            session_id = f"telegram-{chat_id}"
            response = run_agent_message(
                self.runtime.agent,
                text,
                user_id=str(user_id),
                session_id=session_id,
                trade_execution_mode=self._get_trade_mode(chat_id),
            )
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
