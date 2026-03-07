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
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    from ...agents.agno.members.trading_agent_compat import run_agent_message
    from ...agents.agno.members.live_trading_agent import run_live_trading_message
    from ...agents.agno.single_agent import run_single_agent_message
    from ...agents.agno.team.orchestrator import run_team_message
    from ...platform.pnl.alpaca_pnl import get_pnl_report
    from ...platform.alerts.alert_factory import create_rsi_oversold, create_rsi_overbought
except ImportError:
    from agents.agno.members.trading_agent_compat import run_agent_message
    from agents.agno.members.live_trading_agent import run_live_trading_message
    from agents.agno.single_agent import run_single_agent_message
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
        self._chat_ctx_repo = getattr(runtime, "chat_context_repo", None)
        self._coordination_repo = getattr(runtime, "coordination_repo", None)
        self._memory_repo = getattr(runtime, "memory_repo", None)

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

    @staticmethod
    def _enforce_english_policy(text: str) -> str:
        return (
            "Language policy: Always reply in English.\n"
            "Keep the response concise and actionable.\n"
            f"User request: {text}"
        )

    def _infer_domain(self, text: str) -> Optional[str]:
        lower = (text or "").lower()
        if any(k in lower for k in {"rsi", "macd", "bollinger", "soporte", "resistencia", "overbought", "oversold", "technicals"}):
            return "technicals"
        if any(k in lower for k in {"alerta", "alert", "avísame", "avisame"}):
            return "alerts"
        if any(k in lower for k in {"news", "noticia", "noticias", "headline", "catalyst"}):
            return "news"
        if any(k in lower for k in {"buy", "sell", "compra", "vende", "close", "cancel"}):
            return "live_trading"
        if any(k in lower for k in {"strategy", "estrategia", "backtest", "pnl", "running"}):
            return "strategy_ops"
        if any(k in lower for k in {"watchlist", "favorito", "grupo"}):
            return "watchlist"
        return None

    def _is_technical_intent(self, text: str) -> bool:
        lower = (text or "").lower()
        technical_terms = {
            "rsi",
            "macd",
            "bollinger",
            "soporte",
            "resistencia",
            "support",
            "resistance",
            "overbought",
            "oversold",
            "touch",
            "toco",
            "tocó",
            "bounce",
            "rebote",
            "breakdown",
            "breakout",
            "technicals",
            "analisis tecnico",
            "análisis técnico",
            "technical analysis",
            "price level",
            "cuantas veces",
            "cuántas veces",
        }
        return any(term in lower for term in technical_terms)

    def _extract_group_name(self, text: str) -> Optional[str]:
        m = re.search(r"grupo\s+([A-Za-z0-9_-]+)", text or "", flags=re.IGNORECASE)
        return m.group(1).strip().lower() if m else None

    def _context_prefix(self, chat_id: int, text: str) -> str:
        if self._chat_ctx_repo is None:
            return text
        try:
            # Keep context compact to reduce token and latency overhead.
            state = self._chat_ctx_repo.get_chat_state(int(chat_id))
        except Exception as exc:
            logger.debug("chat context summary unavailable: %s", exc)
            state = None
        if not state:
            return text
        requested_domain = self._infer_domain(text)
        symbol_from_state = state.get("active_symbol")
        if requested_domain == "technicals":
            # Strict technical context policy:
            # only propagate a validated symbol present in the current user message.
            current_symbols = self._extract_valid_symbols_for_analysis(text)
            symbol_from_state = current_symbols[0] if current_symbols else None
        elif symbol_from_state and not self._is_likely_ticker_format(str(symbol_from_state)):
            symbol_from_state = None
        lines = ["Persisted chat context (state):"]
        if state.get("active_domain"):
            lines.append(f"- active_domain: {state['active_domain']}")
        if symbol_from_state:
            lines.append(f"- active_symbol: {symbol_from_state}")
        if state.get("active_group"):
            lines.append(f"- active_group: {state['active_group']}")
        if state.get("timeframe"):
            lines.append(f"- timeframe: {state['timeframe']}")
        lines.append("")
        lines.append("Current user request:")
        lines.append(text)
        return "\n".join(lines)

    def _persist_turn(self, chat_id: int, user_id: int, role: str, content: str, meta: Optional[Dict[str, Any]] = None) -> None:
        if self._chat_ctx_repo is None:
            return
        try:
            self._chat_ctx_repo.append_turn(
                chat_id=int(chat_id),
                user_id=int(user_id) if role == "user" else None,
                role=role,
                content=content,
                meta=meta or {},
            )
        except Exception:
            logger.exception("Failed to persist chat turn")

    def _persist_chat_state(self, chat_id: int, user_id: int, text: str, response_text: Optional[str] = None) -> None:
        if self._chat_ctx_repo is None:
            return
        try:
            symbols = self._extract_valid_symbols_for_analysis(text)
            active_symbol = symbols[0] if symbols else None
            active_group = self._extract_group_name(text)
            timeframe = None
            lower = text.lower()
            if "4h" in lower:
                timeframe = "4H"
            elif "1d" in lower or "diario" in lower or "daily" in lower:
                timeframe = "1D"
            domain = self._infer_domain(text)
            self._chat_ctx_repo.upsert_chat_state(
                chat_id=int(chat_id),
                user_id=int(user_id),
                active_domain=domain,
                active_symbol=active_symbol,
                active_group=active_group,
                timeframe=timeframe,
                context_json={"last_user_text": text, "last_response_text": (response_text or "")[:500]},
            )
            # Minimal shared-memory fact persistence for strong signals (helps cross-agent continuity)
            if self._memory_repo is not None and active_symbol and domain in {"technicals", "news", "alerts"}:
                self._memory_repo.remember_fact(
                    category="chat_context",
                    key=f"last_topic:{domain}",
                    value=f"Recent user discussion about {active_symbol}",
                    source="chat_service",
                    team_name="TradingAlertTeam",
                    symbol=active_symbol,
                    confidence=0.6,
                )
        except Exception:
            logger.exception("Failed to persist chat state")

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
        mode_text = (
            "Conversational Agno mode: ON"
            if (getattr(self.runtime, "single_agent", None) or self.runtime.team or self.runtime.agent)
            else "Conversational Agno mode: OFF"
        )
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
            "/alerts [list|create-drop|create-rise|create-target|create-rsi-overbought|create-rsi-oversold|pause|resume|remove] ...\n"
            "/examples [technicals|alerts|trading]\n"
            "/report <pre_open|midday|close|weekly> [watchlist <grupo>|group <grupo>|ticker <simbolo>|<grupo|simbolo>]\n"
            "/news [watchlist|group <name>]\n"
            "/trade_mode [paper|live]\n"
            "/live_trading_options\n"
            "/watchlist [list|groups|add|create|fav|remove|remove-group] ...\n"
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
            "NVDA": "NVDA",
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
            "BITCOIN": "BTC/USD",
            "ETHEREUM": "ETH/USD",
            "BTC": "BTC/USD",
            "ETH": "ETH/USD",
        }
        stopwords = {
            "RSI", "OVERBOUGHT", "OVERSOLD", "SOBRECOMPRADA", "SOBRECOMPRADO",
            "SOBREVENDIDA", "SOBREVENDIDO", "PARA", "QUIERO", "CREA", "ALERTA",
            "EL", "LA", "LOS", "LAS", "Y", "AND", "DE", "DEL", "EN", "UN", "UNA",
            "NUEVO", "NUEVA", "STOCKS", "STOCK", "ACCIONES", "ACCION",
            "AGREGA", "AGREGAR", "TICKER", "TICKERS", "WATCHLIST",
            "GRUPO", "GRUPOS", "FAVORITO", "FAVORITOS", "QUE", "CUANTAS", "CUANTOS",
            "VECES", "CAIDO", "CAIDA", "REVISA", "ANALIZA", "ANALISIS", "TECNICO",
            "TECNICOS", "TECHNICAL", "TECHNICALS", "EARNINGS", "DESPUES", "AYER",
            "HOY", "PRECIO", "NIVEL", "SOPORTE", "RESISTENCIA", "FAANG", "FANG",
        }
        raw = text or ""
        symbols: List[str] = []

        def _push(candidate: str) -> None:
            sym = (candidate or "").strip().upper().replace("-", "/")
            if not sym or sym in stopwords:
                return
            if sym not in symbols:
                symbols.append(sym)

        # Explicit crypto/forex-like symbols.
        for token in re.findall(r"\b[A-Za-z]{2,10}[/-][A-Za-z]{2,10}\b", raw):
            _push(token)

        # $TICKER mentions.
        for token in re.findall(r"\$([A-Za-z]{1,5}(?:\.[A-Za-z])?)\b", raw):
            _push(token)

        # Uppercase ticker-like tokens from user text.
        for token in re.findall(r"\b[A-Z]{1,5}(?:\.[A-Z])?\b", raw):
            _push(alias_map.get(token, token))

        # Company-name aliases in any case.
        for token in re.findall(r"\b[A-Za-z][A-Za-z0-9.&-]{1,24}\b", raw):
            upper = token.upper()
            mapped = alias_map.get(upper)
            if mapped:
                _push(mapped)

        return symbols

    def _is_likely_ticker_format(self, symbol: str) -> bool:
        sym = (symbol or "").strip().upper()
        if not sym:
            return False
        if "/" in sym:
            return bool(re.fullmatch(r"[A-Z]{2,10}/[A-Z]{2,10}", sym))
        if "." in sym:
            return bool(re.fullmatch(r"[A-Z]{1,5}\.[A-Z]", sym))
        return bool(re.fullmatch(r"[A-Z]{1,5}", sym))

    def _validate_watchlist_symbols(self, symbols: List[str]) -> tuple[List[str], List[str]]:
        """
        Deterministic validation for watchlist symbols using Alpaca data service.
        - First gate by ticker-like format
        - Then validate via latest price or short bars availability
        """
        if not symbols:
            return [], []
        data_service = getattr(getattr(self.runtime, "alert_system", None), "data_service", None)
        valid: List[str] = []
        invalid: List[str] = []

        for sym in symbols:
            ticker = (sym or "").strip().upper().replace("-", "/")
            if not self._is_likely_ticker_format(ticker):
                invalid.append(ticker)
                continue
            if data_service is None:
                valid.append(ticker)
                continue
            try:
                price = data_service.get_latest_price(ticker)
                if price is not None:
                    valid.append(ticker)
                    continue
                bars = data_service.get_stock_bars(ticker, days=5)
                if bars is not None and not bars.empty:
                    valid.append(ticker)
                else:
                    invalid.append(ticker)
            except Exception:
                invalid.append(ticker)
        return valid, invalid

    def _extract_valid_symbols_for_analysis(self, text: str) -> List[str]:
        symbols = self._extract_symbols(text)
        valid, _ = self._validate_watchlist_symbols(symbols)
        return valid

    def _maybe_handle_rsi_natural_language(self, text: str, chat_id: int) -> Optional[str]:
        alert_system = self.runtime.alert_system
        if alert_system is None:
            return None
        lower = text.lower()
        if "rsi" not in lower:
            return None
        is_oversold = any(t in lower for t in {"oversold", "sobrevendida", "sobrevendido"})
        is_overbought = any(t in lower for t in {"overbought", "sobrecomprada", "sobrecomprado"})

        threshold_match = re.search(
            r"rsi(?:\s*(?:is|de|of))?\s*(?:>=|=>|>|mayor\s+a|above|over|at|reaches|reach|llega\s+a|toque|toca)?\s*(\d+(?:[.,]\d+)?)",
            lower,
            flags=re.IGNORECASE,
        )
        threshold_value: Optional[float] = None
        if threshold_match:
            threshold_value = float(threshold_match.group(1).replace(",", "."))

        if threshold_value is not None and not is_oversold and not is_overbought:
            if any(t in lower for t in {"<=", "=<", "<", "menor a", "below", "under", "falls to", "cae a", "baja a"}):
                is_oversold = True
            else:
                is_overbought = True

        if not is_oversold and not is_overbought:
            # No explicit technical RSI condition recognized; let the Team resolve it.
            return None

        symbols = self._extract_symbols(text)
        symbols, invalid_symbols = self._validate_watchlist_symbols(symbols)
        if not symbols:
            return None
        created: List[Dict[str, Any]] = []
        for index, symbol in enumerate(symbols):
            threshold = float(threshold_value) if threshold_value is not None else (30.0 if is_oversold and not is_overbought else 70.0)
            if is_oversold and not is_overbought:
                rule = create_rsi_oversold(symbol, threshold=threshold)
            else:
                rule = create_rsi_overbought(symbol, threshold=threshold)
            rule["id"] = f"{symbol}-{int(time.time())}-{index}"
            rule["chat_id"] = int(chat_id)
            created.append(alert_system.add_rule(rule))
        kind = "oversold" if is_oversold and not is_overbought else "overbought"
        suffix = ""
        if invalid_symbols:
            suffix = " | ignorados por inválidos: " + ", ".join(invalid_symbols[:10])
        return "RSI " + kind + " creado para: " + ", ".join(str(r.get("symbol")) for r in created) + suffix

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
        if re.search(r"\b(list|show|listado|lista|listar)\b.*\b(watchlist|favorit|grupo)\b", lower):
            list_like = True
        modify_like = any(token in lower for token in {"crea", "crear", "agrega", "añade", "anade"})
        if list_like and not modify_like:
            # "que watchlist tenemos", "listado de favoritos", etc.
            return store.summary_text()
        if (
            any(token in lower for token in {"que grupos", "qué grupos", "grupos de watchlist", "watchlist tienes", "watchlist tienes"})
            or (("grupo" in lower or "grupos" in lower) and any(t in lower for t in {"tienes", "hay", "lista", "listar", "muestr"}))
        ):
            return store.summary_text()
        has_add_verb = any(t in lower for t in {"crea", "crear", "agrega", "añade", "anade", "add"})
        is_create_group = ("grupo" in lower) and has_add_verb
        if not is_create_group and has_add_verb and "watchlist" in lower:
            # Support natural phrases like:
            # "agrega el watchlist FAANG los tickers (GOOG, QQQ, META)"
            is_create_group = True
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
        if is_create_group and not group_name:
            m3 = re.search(r"watchlist\s+([A-Za-z0-9_-]+)", text, flags=re.IGNORECASE)
            if m3:
                candidate = m3.group(1).strip().lower()
                if candidate not in {"con", "las", "los", "siguientes", "stocks", "acciones", "tickers"}:
                    group_name = candidate

        # If deterministic parsing cannot extract the destination group with high
        # confidence, do not mutate watchlists here. Let the team/LLM handle the
        # request instead of silently falling back to "favorites".
        if is_create_group and not group_name:
            return None

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
        symbols, invalid_symbols = self._validate_watchlist_symbols(symbols)
        if not symbols:
            if invalid_symbols:
                return "No encontré tickers válidos para agregar. Revisa estos valores: " + ", ".join(invalid_symbols[:10])
            return None

        if is_create_group:
            added = []
            for s in symbols:
                try:
                    store.add_ticker(s, groups=[group_name], favorite=False)
                    added.append(s)
                except Exception:
                    continue
            if not added:
                return "No pude agregar tickers al grupo."
            suffix = ""
            if invalid_symbols:
                suffix = " | ignorados por inválidos: " + ", ".join(invalid_symbols[:10])
            return f"Grupo '{group_name}' actualizado con {len(added)} tickers: " + ", ".join(added) + suffix

        if is_add_fav:
            added = []
            for s in symbols:
                try:
                    store.add_favorite(s)
                    added.append(s)
                except Exception:
                    continue
            if added:
                suffix = ""
                if invalid_symbols:
                    suffix = " | ignorados por inválidos: " + ", ".join(invalid_symbols[:10])
                return "Favoritos actualizados: " + ", ".join(added) + suffix
        return None

    def _maybe_handle_alert_natural_language(self, chat_id: int, text: str) -> Optional[str]:
        alert_system = self.runtime.alert_system
        if alert_system is None:
            return None
        lower = text.lower()
        if not any(k in lower for k in {"alerta", "alert", "alaerta", "avísame", "avisame"}):
            return None

        # list alerts
        if any(k in lower for k in {"listar", "lista", "list", "muestra", "muéstra", "show"}):
            return self.get_alerts_summary(chat_id)

        # remove alert by id
        if any(k in lower for k in {"elimina", "borra", "quita", "remove", "delete"}):
            m_id = re.search(r"(?:id|alerta)\s*[:#]?\s*([A-Za-z0-9_-]{8,})", text, flags=re.IGNORECASE)
            if not m_id:
                return None
            rid = m_id.group(1).strip()
            ok = alert_system.remove_rule(rid)
            return f"Alerta {rid} eliminada." if ok else f"No encontré la alerta {rid}."

        symbols = self._extract_symbols(text)
        symbols, invalid_symbols = self._validate_watchlist_symbols(symbols)
        if not symbols:
            return None
        symbol = symbols[0]

        # percent drop/rise
        m_pct = re.search(r"(\d+(?:[.,]\d+)?)\s*%", lower)
        if m_pct and any(k in lower for k in {"baje", "caiga", "drop", "down"}):
            pct = float(m_pct.group(1).replace(",", ".")) / 100.0
            rule = {
                "id": str(uuid.uuid4()),
                "symbol": symbol,
                "type": "percent_drop",
                "threshold": pct,
                "active": True,
                "chat_id": int(chat_id),
                "cooldown_seconds": 3600,
                "last_triggered_at": None,
            }
            created = alert_system.add_rule(rule)
            suffix = ""
            if invalid_symbols:
                suffix = " | ignorados por inválidos: " + ", ".join(invalid_symbols[:10])
            return f"Alerta creada: {created.get('symbol')} caída {float(pct)*100:.2f}% (id: {created.get('id')})." + suffix
        if m_pct and any(k in lower for k in {"suba", "sube", "rise", "up"}):
            pct = float(m_pct.group(1).replace(",", ".")) / 100.0
            rule = {
                "id": str(uuid.uuid4()),
                "symbol": symbol,
                "type": "percent_rise",
                "threshold": pct,
                "active": True,
                "chat_id": int(chat_id),
                "cooldown_seconds": 3600,
                "last_triggered_at": None,
            }
            created = alert_system.add_rule(rule)
            suffix = ""
            if invalid_symbols:
                suffix = " | ignorados por inválidos: " + ", ".join(invalid_symbols[:10])
            return f"Alerta creada: {created.get('symbol')} subida {float(pct)*100:.2f}% (id: {created.get('id')})." + suffix

        # target price
        m_price = re.search(r"(?:llegue|toque|cuando|at)\s*(?:a\s*)?\$?\s*(\d+(?:[.,]\d+)?)", lower)
        if m_price:
            target = float(m_price.group(1).replace(",", "."))
            rule = {
                "id": str(uuid.uuid4()),
                "symbol": symbol,
                "type": "target_price",
                "target": target,
                "active": True,
                "chat_id": int(chat_id),
                "cooldown_seconds": 3600,
                "last_triggered_at": None,
            }
            created = alert_system.add_rule(rule)
            suffix = ""
            if invalid_symbols:
                suffix = " | ignorados por inválidos: " + ", ".join(invalid_symbols[:10])
            return f"Alerta creada: {created.get('symbol')} target ${target:,.2f} (id: {created.get('id')})." + suffix

        return None

    def _maybe_handle_alert_option_reply(self, chat_id: int, text: str) -> Optional[str]:
        """
        Fast follow-up for technical recommendations that include:
        Option N: ...
        """
        if self._chat_ctx_repo is None:
            return None
        lower = (text or "").strip().lower()
        if not lower:
            return None

        choice: Optional[int] = None
        m_choice = re.match(r"^(?:option|opcion|opción)?\s*(\d+)\b", lower, flags=re.IGNORECASE)
        if m_choice:
            choice = int(m_choice.group(1))
        elif lower in {"yes", "si", "sí", "ok", "dale", "hazlo", "go"} or any(
            lower.startswith(prefix) for prefix in ("yes ", "si ", "sí ", "ok ", "dale ", "hazlo ", "go ")
        ):
            choice = 1
        else:
            return None

        try:
            turns = self._chat_ctx_repo.get_recent_turns(chat_id=int(chat_id), limit=6)
        except Exception:
            return None
        if not turns:
            return None

        last_assistant = None
        for t in reversed(turns):
            if str(t.get("role", "")).lower() == "assistant":
                last_assistant = str(t.get("content") or "")
                break
        if not last_assistant:
            return None
        if "Suggested Alerts" not in last_assistant and "Option 1:" not in last_assistant:
            return None

        options: Dict[int, str] = {}
        for m in re.finditer(r"Option\s+(\d+)\s*:\s*(.+)", last_assistant, flags=re.IGNORECASE):
            idx = int(m.group(1))
            cmd = m.group(2).strip()
            if cmd:
                options[idx] = cmd
        if not options:
            return None

        selected = options.get(choice) or options.get(1)
        if not selected:
            return None

        created = self._maybe_handle_rsi_natural_language(selected, chat_id)
        if created is None:
            created = self._maybe_handle_alert_natural_language(chat_id, selected)
        if created is not None:
            return created
        return selected

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
                return ChatResponse("Uso: /report <pre_open|midday|close|weekly> [watchlist <grupo>|group <grupo>|ticker <simbolo>|<grupo|simbolo>]", parse_mode=None)
            scheduler = getattr(self.runtime, "portfolio_review_scheduler", None)
            if scheduler is None:
                return ChatResponse("Portfolio review scheduler no disponible.", parse_mode=None)
            kind = args[0].lower()
            valid_kinds = {"pre_open", "midday", "close", "weekly"}
            if kind not in valid_kinds:
                return ChatResponse("Uso: /report <pre_open|midday|close|weekly> [watchlist <grupo>|group <grupo>|ticker <simbolo>|<grupo|simbolo>]", parse_mode=None)
            group_name: Optional[str] = None
            symbol: Optional[str] = None
            if len(args) >= 2:
                second = args[1].lower()
                if second in {"group", "watchlist"}:
                    if len(args) < 3:
                        return ChatResponse("Uso: /report <pre_open|midday|close|weekly> [watchlist <grupo>|group <grupo>|ticker <simbolo>|<grupo|simbolo>]", parse_mode=None)
                    group_name = args[2].strip().lower()
                elif second == "ticker":
                    if len(args) < 3:
                        return ChatResponse("Uso: /report <pre_open|midday|close|weekly> [watchlist <grupo>|group <grupo>|ticker <simbolo>|<grupo|simbolo>]", parse_mode=None)
                    symbol = args[2].strip().upper()
                else:
                    candidate = args[1].strip()
                    candidate_group = candidate.lower()
                    store = getattr(self.runtime, "watchlist_store", None)
                    cfg = None
                    if store is not None and hasattr(store, "load"):
                        try:
                            cfg = store.load()
                        except Exception:
                            cfg = None
                    if cfg is not None and candidate_group in (cfg.groups or {}):
                        group_name = candidate_group
                    else:
                        symbol = candidate.upper()
            try:
                if group_name:
                    started = scheduler.trigger_async_with_group(
                        kind,
                        chat_id=chat_id,
                        source="manual",
                        group_name=group_name,
                    )
                elif symbol:
                    started = scheduler.trigger_async_with_symbols(
                        kind,
                        symbols=[symbol],
                        chat_id=chat_id,
                        source="manual",
                    )
                else:
                    started = scheduler.trigger_async(kind, chat_id=chat_id, source="manual")
            except Exception as exc:
                return ChatResponse(f"Error iniciando reporte: {exc}", parse_mode=None)
            if started:
                scope = f" del grupo {group_name}" if group_name else ""
                if not scope and symbol:
                    scope = f" de ticker {symbol}"
                return ChatResponse(f"Generando reporte {kind}{scope}... te lo envío por Telegram cuando esté listo.", parse_mode=None)
            scope = f" del grupo {group_name}" if group_name else ""
            if not scope and symbol:
                scope = f" de ticker {symbol}"
            return ChatResponse(f"Ya hay un reporte {kind}{scope} en ejecución para este chat.", parse_mode=None)

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

        if command in {"alerts", "alert"}:
            alert_system = self.runtime.alert_system
            if alert_system is None:
                return ChatResponse("Alert system is not available.", parse_mode=None)

            action = (args[0].lower() if args else "list")
            if action == "list":
                return ChatResponse(self.get_alerts_summary(chat_id), parse_mode=None)

            if action in {"remove", "delete", "rm"}:
                if len(args) < 2:
                    return ChatResponse("Usage: /alerts remove <alert_id>", parse_mode=None)
                rule_id = args[1].strip()
                ok = alert_system.remove_rule(rule_id)
                return ChatResponse(
                    f"Alert {rule_id} removed." if ok else f"Alert {rule_id} not found.",
                    parse_mode=None,
                )

            if action in {"pause", "deactivate", "disable"}:
                if len(args) < 2:
                    return ChatResponse("Usage: /alerts pause <alert_id>", parse_mode=None)
                rule_id = args[1].strip()
                updated = alert_system.update_rule(rule_id, {"active": False})
                if updated is None:
                    return ChatResponse(f"Alert {rule_id} not found.", parse_mode=None)
                return ChatResponse(f"Alert {rule_id} paused.", parse_mode=None)

            if action in {"resume", "activate", "enable"}:
                if len(args) < 2:
                    return ChatResponse("Usage: /alerts resume <alert_id>", parse_mode=None)
                rule_id = args[1].strip()
                updated = alert_system.update_rule(rule_id, {"active": True})
                if updated is None:
                    return ChatResponse(f"Alert {rule_id} not found.", parse_mode=None)
                return ChatResponse(f"Alert {rule_id} resumed.", parse_mode=None)

            if action in {"create-drop", "create-rise", "create-target", "create-rsi-overbought", "create-rsi-oversold"}:
                needs_value = action in {"create-drop", "create-rise", "create-target"}
                if len(args) < 2 or (needs_value and len(args) < 3):
                    return ChatResponse(
                        "Usage: /alerts create-drop <symbol> <percent> | "
                        "/alerts create-rise <symbol> <percent> | "
                        "/alerts create-target <symbol> <price> | "
                        "/alerts create-rsi-overbought <symbol> [threshold=70] [period=14] | "
                        "/alerts create-rsi-oversold <symbol> [threshold=30] [period=14]",
                        parse_mode=None,
                    )
                symbol = args[1].strip().upper().replace("-", "/")
                valid_symbols, invalid_symbols = self._validate_watchlist_symbols([symbol])
                if not valid_symbols:
                    bad = invalid_symbols[0] if invalid_symbols else symbol
                    return ChatResponse(f"Invalid symbol: {bad}", parse_mode=None)
                symbol = valid_symbols[0]
                suffix = ""
                if invalid_symbols:
                    suffix = " | ignored invalid: " + ", ".join(invalid_symbols[:10])

                try:
                    if action == "create-drop":
                        pct = float(str(args[2]).replace(",", "."))
                        rule = {
                            "id": str(uuid.uuid4()),
                            "symbol": symbol,
                            "type": "percent_drop",
                            "threshold": pct / 100.0,
                            "active": True,
                            "chat_id": int(chat_id),
                            "cooldown_seconds": 3600,
                            "last_triggered_at": None,
                        }
                        created = alert_system.add_rule(rule)
                        return ChatResponse(
                            f"Alert created: {created.get('symbol')} drop {pct:.2f}% (id: {created.get('id')})." + suffix,
                            parse_mode=None,
                        )

                    if action == "create-rise":
                        pct = float(str(args[2]).replace(",", "."))
                        rule = {
                            "id": str(uuid.uuid4()),
                            "symbol": symbol,
                            "type": "percent_rise",
                            "threshold": pct / 100.0,
                            "active": True,
                            "chat_id": int(chat_id),
                            "cooldown_seconds": 3600,
                            "last_triggered_at": None,
                        }
                        created = alert_system.add_rule(rule)
                        return ChatResponse(
                            f"Alert created: {created.get('symbol')} rise {pct:.2f}% (id: {created.get('id')})." + suffix,
                            parse_mode=None,
                        )

                    if action == "create-target":
                        target = float(str(args[2]).replace(",", "."))
                        rule = {
                            "id": str(uuid.uuid4()),
                            "symbol": symbol,
                            "type": "target_price",
                            "target": target,
                            "active": True,
                            "chat_id": int(chat_id),
                            "cooldown_seconds": 3600,
                            "last_triggered_at": None,
                        }
                        created = alert_system.add_rule(rule)
                        return ChatResponse(
                            f"Alert created: {created.get('symbol')} target ${target:,.2f} (id: {created.get('id')})." + suffix,
                            parse_mode=None,
                        )

                    threshold = float(str(args[2]).replace(",", ".")) if len(args) >= 3 else (70.0 if action == "create-rsi-overbought" else 30.0)
                    period = 14
                    for token in args[3:]:
                        token_lower = token.lower()
                        if token_lower.startswith("period="):
                            try:
                                period = int(token_lower.split("=", 1)[1].strip())
                            except Exception:
                                pass
                        elif re.fullmatch(r"\d+", token_lower):
                            try:
                                period = int(token_lower)
                            except Exception:
                                pass
                    if action == "create-rsi-overbought":
                        rule = create_rsi_overbought(symbol, threshold=threshold, period=period)
                        label = f"RSI>{threshold:.2f}"
                    else:
                        rule = create_rsi_oversold(symbol, threshold=threshold, period=period)
                        label = f"RSI<{threshold:.2f}"
                    rule["id"] = str(uuid.uuid4())
                    rule["chat_id"] = int(chat_id)
                    created = alert_system.add_rule(rule)
                    return ChatResponse(
                        f"Alert created: {created.get('symbol')} {label} period={period} (id: {created.get('id')})." + suffix,
                        parse_mode=None,
                    )
                except ValueError as exc:
                    return ChatResponse(f"Invalid numeric value: {exc}", parse_mode=None)
                except Exception as exc:
                    return ChatResponse(f"Failed to create alert: {exc}", parse_mode=None)

            return ChatResponse(
                "Usage: /alerts [list|create-drop|create-rise|create-target|create-rsi-overbought|create-rsi-oversold|pause|resume|remove] ...",
                parse_mode=None,
            )

        if command == "watchlist":
            store = getattr(self.runtime, "watchlist_store", None)
            if store is None:
                return ChatResponse("Watchlist store no disponible.", parse_mode=None)
            action = (args[0].lower() if args else "list")
            if action in {"list", "groups"}:
                return ChatResponse(store.summary_text(), parse_mode=None)
            if action in {"add", "create", "fav", "favorite", "remove", "rm", "delete", "remove-group", "rm-group", "delete-group"}:
                if len(args) < 2:
                    return ChatResponse("Uso: /watchlist add <ticker> [grupo1,grupo2] | /watchlist create <ticker> [grupo1,grupo2] | /watchlist fav <ticker> | /watchlist remove <ticker> [grupo|favorites] | /watchlist remove-group <grupo>", parse_mode=None)
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
            return ChatResponse("Uso: /watchlist [list|groups|add|create|fav|remove|remove-group] ...", parse_mode=None)

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
                return ChatResponse(f"Could not compute PnL: {exc}")

        return ChatResponse("Unknown command. Use /help")

    def handle_chat(self, chat_id: int, user_id: int, text: str) -> ChatResponse:
        self._persist_turn(chat_id, user_id, "user", text)

        watchlist_response = self._maybe_handle_watchlist_natural_language(text)
        if watchlist_response is not None:
            self._persist_turn(chat_id, user_id, "assistant", watchlist_response)
            self._persist_chat_state(chat_id, user_id, text, watchlist_response)
            return ChatResponse(watchlist_response, parse_mode=None)

        alert_option_response = self._maybe_handle_alert_option_reply(chat_id, text)
        if alert_option_response is not None:
            self._persist_turn(chat_id, user_id, "assistant", alert_option_response)
            self._persist_chat_state(chat_id, user_id, text, alert_option_response)
            return ChatResponse(alert_option_response, parse_mode=None)

        alert_response = self._maybe_handle_alert_natural_language(chat_id, text)
        if alert_response is not None:
            self._persist_turn(chat_id, user_id, "assistant", alert_response)
            self._persist_chat_state(chat_id, user_id, text, alert_response)
            return ChatResponse(alert_response, parse_mode=None)

        report_response = self._maybe_handle_report_natural_language(chat_id, text)
        if report_response is not None:
            self._persist_turn(chat_id, user_id, "assistant", report_response)
            self._persist_chat_state(chat_id, user_id, text, report_response)
            return ChatResponse(report_response, parse_mode=None)

        if self.runtime.alert_system is not None:
            self.runtime.alert_system.set_active_chat_id(chat_id)
            rsi_response = self._maybe_handle_rsi_natural_language(text, chat_id)
            if rsi_response is not None:
                self._persist_turn(chat_id, user_id, "assistant", rsi_response)
                self._persist_chat_state(chat_id, user_id, text, rsi_response)
                return ChatResponse(rsi_response, parse_mode=None)

        # Strict technical context policy:
        # technical requests require a validated symbol in the current message.
        if self._is_technical_intent(text):
            valid_symbols = self._extract_valid_symbols_for_analysis(text)
            if not valid_symbols:
                clarification = "Which symbol should I analyze? (e.g., NVDA, ETH/USD)."
                self._persist_turn(chat_id, user_id, "assistant", clarification)
                self._persist_chat_state(chat_id, user_id, text, clarification)
                return ChatResponse(clarification, parse_mode=None)

        single_agent = getattr(self.runtime, "single_agent", None)
        if single_agent is not None:
            session_id = f"telegram-{chat_id}"
            response = run_single_agent_message(
                single_agent,
                self._enforce_english_policy(
                    self._context_prefix(chat_id, self._apply_trade_mode_policy(chat_id, text))
                ),
                user_id=str(user_id),
                session_id=session_id,
            )
            self._persist_turn(chat_id, user_id, "assistant", response)
            self._persist_chat_state(chat_id, user_id, text, response)
            return ChatResponse(response, parse_mode=None)

        live_trading_agent = getattr(self.runtime, "live_trading_agent", None)
        if live_trading_agent is not None and self._is_trade_intent_text(text):
            session_id = f"telegram-{chat_id}"
            response = run_live_trading_message(
                live_trading_agent,
                self._enforce_english_policy(text),
                user_id=str(user_id),
                session_id=session_id,
                trade_execution_mode=self._get_trade_mode(chat_id),
            )
            self._persist_turn(chat_id, user_id, "assistant", response)
            self._persist_chat_state(chat_id, user_id, text, response)
            return ChatResponse(response, parse_mode=None)

        if self.runtime.team is not None:
            session_id = f"telegram-{chat_id}"
            response = run_team_message(
                self.runtime.team,
                self._enforce_english_policy(
                    self._context_prefix(chat_id, self._apply_trade_mode_policy(chat_id, text))
                ),
                user_id=str(user_id),
                session_id=session_id,
            )
            self._persist_turn(chat_id, user_id, "assistant", response)
            self._persist_chat_state(chat_id, user_id, text, response)
            return ChatResponse(response, parse_mode=None)

        if self.runtime.agent is not None:
            session_id = f"telegram-{chat_id}"
            response = run_agent_message(
                self.runtime.agent,
                self._enforce_english_policy(self._context_prefix(chat_id, text)),
                user_id=str(user_id),
                session_id=session_id,
                trade_execution_mode=self._get_trade_mode(chat_id),
            )
            self._persist_turn(chat_id, user_id, "assistant", response)
            self._persist_chat_state(chat_id, user_id, text, response)
            return ChatResponse(response, parse_mode=None)

        fallback = "Conversational mode requires OPENAI_API_KEY or ANTHROPIC_API_KEY."
        self._persist_turn(chat_id, user_id, "assistant", fallback)
        self._persist_chat_state(chat_id, user_id, text, fallback)
        return ChatResponse(fallback, parse_mode=None)

    def handle_text(self, chat_id: int, user_id: int, text: str) -> ChatResponse:
        text = (text or "").strip()
        if not text:
            return ChatResponse("", parse_mode=None)
        if text.startswith("/"):
            tokens = text.split()
            command = tokens[0][1:].split("@", 1)[0].lower()
            return self.handle_command(chat_id, user_id, command, tokens[1:])
        return self.handle_chat(chat_id, user_id, text)
