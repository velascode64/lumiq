"""
Telegram bot for conversational Lumibot strategy control.

This implementation uses Telegram's HTTP API directly, avoiding runtime issues with
python-telegram-bot in some Python versions.
"""

from __future__ import annotations

import json
import logging
import time
import re
from typing import Any, Dict, List, Optional

import requests

try:
    from .agno_trading_agent import create_trading_agent, run_agent_message
    from .agno_team_orchestrator import create_alerts_trading_team, run_team_message
    from .strategy_orchestrator import StrategyOrchestrator
    from .alpaca_pnl import get_pnl_report, get_realized_pnl_summary
    from .alerts.streaming import AlertStreamManager
    from .alerts.alert_factory import create_rsi_oversold, create_rsi_overbought
    from .portfolio_review import PortfolioReviewScheduler, PortfolioReviewService, WatchlistStore
    from .news_monitor import WatchlistNewsMonitorService, WatchlistNewsScheduler
    from .agno_news_agent import create_news_agent, run_news_agent_message
except ImportError:
    from agno_trading_agent import create_trading_agent, run_agent_message
    from agno_team_orchestrator import create_alerts_trading_team, run_team_message
    from strategy_orchestrator import StrategyOrchestrator
    from alpaca_pnl import get_pnl_report, get_realized_pnl_summary
    from alerts.streaming import AlertStreamManager
    from alerts.alert_factory import create_rsi_oversold, create_rsi_overbought
    from portfolio_review import PortfolioReviewScheduler, PortfolioReviewService, WatchlistStore
    from news_monitor import WatchlistNewsMonitorService, WatchlistNewsScheduler
    from agno_news_agent import create_news_agent, run_news_agent_message

try:
    from alerts.alert_system import AlertSystem
except ImportError:
    from .alerts.alert_system import AlertSystem


logger = logging.getLogger(__name__)


def _examples_text(agent: Optional[str] = None) -> str:
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
        "strategy": "trading",
        "estrategias": "trading",
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

    return "Usa /examples technicals | /examples alerts | /examples trading para filtrar.\n\n" + "\n\n".join(sections)


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
            continue
        if lower in {"paper", "live"}:
            mode = lower
            continue
        if lower.startswith("mode="):
            value = lower.split("=", 1)[1].strip()
            if value in {"paper", "live"}:
                mode = value
            continue
    return {
        "period": period,
        "mode": mode,
    }


def _format_pnl_summary(summary: Dict[str, Any]) -> str:
    """Format P&L summary with HTML for Telegram."""

    def _pnl_emoji(value: Any) -> str:
        if value is None:
            return "⚪"
        try:
            v = float(value)
            if v > 0:
                return "🟢"
            elif v < 0:
                return "🔴"
            return "⚪"
        except Exception:
            return "⚪"

    def _fmt_money(value: Any, show_sign: bool = False, bold: bool = False) -> str:
        if value is None:
            return "N/D"
        try:
            v = float(value)
            if show_sign and v >= 0:
                text = f"+${v:,.2f}"
            else:
                text = f"${v:,.2f}"
            return f"<b>{text}</b>" if bold else text
        except Exception:
            return str(value)

    def _fmt_pct(value: Any) -> str:
        if value is None:
            return ""
        try:
            v = float(value)
            sign = "+" if v >= 0 else ""
            return f"<i>({sign}{v:.2f}%)</i>"
        except Exception:
            return ""

    def _fmt_qty(value: Any) -> str:
        if value is None:
            return "0"
        try:
            v = float(value)
            if v == int(v):
                return str(int(v))
            return f"{v:.4f}"
        except Exception:
            return str(value)

    # Extract P&L values
    daily_pnl = summary.get("daily_pnl")
    weekly_pnl = summary.get("weekly_pnl")
    alltime_pnl = summary.get("alltime_pnl")

    if daily_pnl is None:
        daily_pnl = summary.get("total_realized_pnl") if summary.get("period") == "daily" else None

    lines = [
        "<b>📊 P&amp;L Report</b>",
        "",
        f"💰 <b>Equity:</b> {_fmt_money(summary.get('account_equity'), bold=True)}",
        f"💵 <b>Cash:</b> {_fmt_money(summary.get('start_portfolio_value'))}",
        "",
        "<b>📈 P&amp;L Summary</b>",
        f"  {_pnl_emoji(daily_pnl)} Hoy: {_fmt_money(daily_pnl, show_sign=True, bold=True)} {_fmt_pct(summary.get('total_pnl_pct') if summary.get('period') == 'daily' else None)}",
        f"  {_pnl_emoji(weekly_pnl)} Semana: {_fmt_money(weekly_pnl, show_sign=True, bold=True)}",
        f"  {_pnl_emoji(alltime_pnl)} All-Time: {_fmt_money(alltime_pnl, show_sign=True, bold=True)}",
    ]

    positions = summary.get("positions") or []
    lines.append("")
    lines.append("<b>📂 Posiciones Abiertas</b>")

    if not positions:
        lines.append("  <i>Sin posiciones abiertas</i>")
    else:
        total_unrealized = 0.0
        total_intraday = 0.0
        for pos in positions:
            symbol = pos.get("symbol", "???")
            qty = pos.get("qty", 0)
            unreal = float(pos.get("unrealized_pl") or 0.0)
            unreal_pct = pos.get("unrealized_plpc")
            intraday = float(pos.get("unrealized_intraday_pl") or 0.0)

            total_unrealized += unreal
            total_intraday += intraday

            emoji = _pnl_emoji(unreal)
            pct_str = _fmt_pct(unreal_pct)
            lines.append(
                f"  {emoji} <code>{symbol}</code> x{_fmt_qty(qty)}: {_fmt_money(unreal, True, bold=True)} {pct_str}"
            )

        lines.append("")
        lines.append(f"  📍 <b>Total:</b> {_fmt_money(total_unrealized, True)} | Hoy: {_fmt_money(total_intraday, True)}")

    # Closed trades section
    closed_trades = summary.get("closed_trades") or []
    realized_today = summary.get("total_realized_pnl_today", 0.0)
    trades_count = summary.get("trades_count_today", 0)

    lines.append("")
    lines.append("<b>🔄 Operaciones Cerradas Hoy</b>")

    if not closed_trades:
        lines.append("  <i>Sin operaciones cerradas</i>")
    else:
        for trade in closed_trades:
            symbol = trade.get("symbol", "???")
            pnl = trade.get("realized_pnl", 0.0)
            order_count = trade.get("order_count", 0)

            emoji = _pnl_emoji(pnl)
            lines.append(
                f"  {emoji} <code>{symbol}</code>: {_fmt_money(pnl, True, bold=True)} <i>({order_count} ops)</i>"
            )

        lines.append("")
        realized_emoji = _pnl_emoji(realized_today)
        lines.append(f"  {realized_emoji} <b>Total:</b> {_fmt_money(realized_today, True, bold=True)} | {trades_count} ordenes")

    return "\n".join(lines)


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


class TradingTelegramBot:
    """Telegram polling bot with command mode + Agno conversational mode."""

    def __init__(self, token: str, orchestrator: StrategyOrchestrator):
        self.token = token
        self.orchestrator = orchestrator
        self.watchlist_store = WatchlistStore()
        self.portfolio_review_service = None
        self.portfolio_review_scheduler = None
        self.news_monitor_service = None
        self.news_scheduler = None
        self.news_agent = None
        self.alert_system = None
        self.stream_manager = None
        try:
            self.alert_system = AlertSystem()
        except Exception as exc:
            logger.warning("AlertSystem disabled: %s", exc)
        if self.alert_system is not None:
            self.stream_manager = AlertStreamManager(
                self.alert_system,
                send_callback=lambda chat_id, msg: self._send_message(chat_id, msg, parse_mode=None),
            )
            self.alert_system.set_stream_manager(self.stream_manager)

        try:
            data_service = getattr(self.alert_system, "data_service", None) if self.alert_system is not None else None
            self.portfolio_review_service = PortfolioReviewService(
                broker_config=self.orchestrator.broker_config,
                watchlist_store=self.watchlist_store,
                data_service=data_service,
            )
            self.portfolio_review_scheduler = PortfolioReviewScheduler(
                review_service=self.portfolio_review_service,
                send_callback=lambda chat_id, msg: self._send_message(chat_id, msg, parse_mode=None),
            )
        except Exception as exc:
            logger.warning("PortfolioReview disabled: %s", exc)
        try:
            self.news_monitor_service = WatchlistNewsMonitorService(watchlist_store=self.watchlist_store)
            self.news_agent = create_news_agent(self.news_monitor_service)
            def _news_analyze_callback(group_name: Optional[str]) -> str:
                if self.news_agent is None:
                    return self.news_monitor_service.generate_preopen_digest_text(group_name=group_name)
                scope = f" del grupo {group_name}" if group_name else " de mi watchlist"
                msg = (
                    "Genera el digest de noticias pre-apertura para Telegram.\n"
                    "Usa tools reales para leer noticias y clasificalas por relevancia.\n"
                    f"Analiza noticias{scope} de las ultimas 18 horas.\n"
                    "Formato: Resumen, Alta prioridad, Impacto en posiciones, Impacto en watchlist sin posicion, Ruido, Tickers a revisar primero, Sugerencias."
                )
                return run_news_agent_message(self.news_agent, msg, user_id="cron-news", session_id=f"news-preopen-{group_name or 'all'}")
            self.news_scheduler = WatchlistNewsScheduler(
                service=self.news_monitor_service,
                send_callback=lambda chat_id, msg: self._send_message(chat_id, msg, parse_mode=None),
                analyze_callback=_news_analyze_callback,
            )
        except Exception as exc:
            logger.warning("WatchlistNewsMonitor disabled: %s", exc)

        self.agent = create_trading_agent(orchestrator)
        self.team = create_alerts_trading_team(orchestrator, self.alert_system, self.news_monitor_service)
        self.base_url = f"https://api.telegram.org/bot{token}"
        if self.team is not None:
            logger.info("Agno Team enabled (alerts + trading)")
        elif self.agent is not None:
            mcp_command = getattr(self.agent, "_alpaca_mcp_command", None)
            if mcp_command:
                logger.info("Agno MCP enabled: %s", mcp_command)
            else:
                logger.info("Agno MCP not found, running without MCP tools")

    def _api_post(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/{method}",
            json=payload,
            timeout=40,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error on {method}: {data}")
        return data

    def _api_get_updates(self, offset: Optional[int]) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {
            "timeout": 30,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset
        data = self._api_post("getUpdates", payload)
        return data.get("result", [])

    def _send_message(self, chat_id: int, text: str, parse_mode: Optional[str] = "HTML") -> None:
        # Telegram message limit is 4096 characters.
        chunk_size = 3900
        chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)] or ["(empty)"]
        for chunk in chunks:
            payload: Dict[str, Any] = {
                "chat_id": chat_id,
                "text": chunk,
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode
            try:
                self._api_post("sendMessage", payload)
            except Exception:
                # Fallback: retry without parse_mode (avoids Telegram HTML parsing errors)
                if "parse_mode" in payload:
                    payload.pop("parse_mode", None)
                    self._api_post("sendMessage", payload)
                else:
                    raise

    def _help_text(self) -> str:
        mode_text = "Conversational Agno mode: ON" if self.agent else "Conversational Agno mode: OFF"
        return (
            "Lumibot trading bot is ready.\n\n"
            f"{mode_text}\n\n"
            "Commands:\n"
            "/strategies - list available strategies\n"
            "/running - list active strategies\n"
            "/run <strategy> [mode=paper|live] [key=value ...]\n"
            "/status [strategy]\n"
            "/set <strategy> <param> <value>\n"
            "/stop [strategy|all]\n\n"
            "/pnl [mode=paper|live] - P&L report (daily, weekly, all-time)\n\n"
            "/list alerts - list active alert rules\n\n"
            "/examples [technicals|alerts|trading] - example questions by agent\n\n"
            "/report <pre_open|midday|close|weekly> - async report to Telegram\n"
            "/news [watchlist|group <name>] - pre-open news digest (manual fallback)\n"
            "/watchlist [list|groups|add|fav] ...\n\n"
            "You can also send natural language messages to control trading."
        )

    def get_alerts_summary(self, chat_id: Optional[int] = None) -> str:
        if self.alert_system is None:
            return "Alert system is not available."

        rules = self.alert_system.list_rules()
        if not rules:
            return "No hay alertas configuradas."

        if chat_id is not None:
            rules = [r for r in rules if int(r.get("chat_id") or 0) == int(chat_id)]
            if not rules:
                return "No hay alertas para este chat."

        lines = ["<b>📌 Alertas activas</b>"]
        appended = 0
        for rule in rules:
            if not rule.get("active", True):
                continue
            symbol = rule.get("symbol", "???")
            rule_id = rule.get("id", "n/a")
            rtype = rule.get("type", "unknown")
            if rtype == "target_price":
                target = rule.get("target")
                detail = f"target ${float(target):.2f}" if target is not None else "target ?"
            elif rtype == "percent_drop":
                threshold = rule.get("threshold")
                detail = f"drop {float(threshold):.2f}%" if threshold is not None else "drop ?"
            elif rtype == "percent_rise":
                threshold = rule.get("threshold")
                detail = f"rise {float(threshold):.2f}%" if threshold is not None else "rise ?"
            elif rtype == "max_price":
                detail = "max price"
            elif rtype == "min_price":
                detail = "min price"
            elif rtype == "rsi_oversold":
                threshold = rule.get("threshold", 30)
                period = rule.get("period", 14)
                detail = f"RSI<{threshold} (p={period})"
            elif rtype == "rsi_overbought":
                threshold = rule.get("threshold", 70)
                period = rule.get("period", 14)
                detail = f"RSI>{threshold} (p={period})"
            elif rtype == "macd_bullish_cross":
                fast = rule.get("fast", 12)
                slow = rule.get("slow", 26)
                signal = rule.get("signal", 9)
                detail = f"MACD bullish (f={fast}, s={slow}, sig={signal})"
            elif rtype == "bollinger_middle_cross":
                period = rule.get("period", 20)
                direction = rule.get("direction", "above")
                detail = f"Bollinger mid {direction} (p={period})"
            else:
                detail = rtype
            lines.append(f"• <code>{symbol}</code> {detail} | <i>{rule_id}</i>")
            appended += 1

        if appended == 0:
            return "No hay alertas activas."

        return "\n".join(lines)

    def _handle_command(self, chat_id: int, user_id: int, command: str, args: List[str]) -> str:
        if command in {"start", "help"}:
            return self._help_text()

        if command == "list" and args and args[0].lower() == "alerts":
            return self.get_alerts_summary(chat_id=chat_id)

        if command == "examples":
            topic = args[0] if args else None
            return _examples_text(topic)

        if command == "report":
            if not args:
                return "Uso: /report <pre_open|midday|close|weekly>"
            if self.portfolio_review_scheduler is None:
                return "Portfolio review scheduler no disponible."
            kind = args[0].lower()
            try:
                started = self.portfolio_review_scheduler.trigger_async(kind, chat_id=chat_id, source="manual")
            except Exception as exc:
                return f"Error iniciando reporte: {exc}"
            if started:
                return f"Generando reporte {kind}... te lo envio cuando este listo."
            return f"Ya hay un reporte {kind} ejecutandose para este chat."

        if command == "news":
            if self.news_scheduler is None:
                return "News scheduler no disponible."
            group_name = None
            if args and args[0].lower() == "group":
                if len(args) < 2:
                    return "Uso: /news [watchlist|group <name>]"
                group_name = args[1]
            elif args and args[0].lower() not in {"watchlist", "today", "hoy"}:
                group_name = args[0]
            started = self.news_scheduler.trigger_async(chat_id=chat_id, source="manual", group_name=group_name)
            if started:
                scope = f" del grupo {group_name}" if group_name else ""
                return f"Generando digest de noticias{scope}... te lo envio cuando este listo."
            return "Ya hay un digest de noticias ejecutandose."

        if command == "watchlist":
            action = (args[0].lower() if args else "list")
            if action in {"list", "groups"}:
                return self.watchlist_store.summary_text()
            if action in {"add", "fav", "favorite", "remove", "rm", "delete", "remove-group", "rm-group", "delete-group"}:
                if len(args) < 2:
                    return "Uso: /watchlist add <ticker> [grupo1,grupo2] [favorite=true] | /watchlist fav <ticker> | /watchlist remove <ticker> [grupo|favorites] | /watchlist remove-group <grupo>"
                ticker = args[1]
                try:
                    if action in {"fav", "favorite"}:
                        result = self.watchlist_store.add_favorite(ticker)
                    elif action in {"remove-group", "rm-group", "delete-group"}:
                        result = self.watchlist_store.remove_group(ticker)
                    elif action in {"remove", "rm", "delete"}:
                        group_name = args[2] if len(args) >= 3 and args[2].lower() not in {"favorites", "favoritos"} else None
                        from_favorites = len(args) >= 3 and args[2].lower() in {"favorites", "favoritos"}
                        result = self.watchlist_store.remove_ticker(ticker, group_name=group_name, from_favorites=from_favorites)
                    else:
                        groups = [g.strip() for g in (args[2].split(",") if len(args) >= 3 else []) if g.strip()]
                        favorite = len(args) >= 4 and args[3].strip().lower() in {"1", "true", "yes", "fav", "favorite"}
                        result = self.watchlist_store.add_ticker(ticker, groups=groups, favorite=favorite)
                    return "Watchlist actualizado: " + json.dumps(result, ensure_ascii=True)
                except Exception as exc:
                    return f"No se pudo actualizar watchlist: {exc}"
            return "Uso: /watchlist [list|groups|add|fav|remove|remove-group] ..."

        if command == "strategies":
            available = self.orchestrator.list_available_strategies()
            if not available:
                return "No strategies discovered in core/strategies/live."
            return "Available strategies:\n- " + "\n- ".join(available)

        if command == "running":
            running = self.orchestrator.list_running_strategies()
            if not running:
                return "No active strategies."
            return "Running strategies:\n- " + "\n- ".join(running)

        if command == "run":
            if not args:
                return "Usage:\n/run <strategy> [mode=paper|live] [key=value ...]"
            strategy_name = args[0]
            extra = _parse_key_value_args(args[1:])
            mode = str(extra.pop("mode", "paper"))
            result = self.orchestrator.start_strategy(
                strategy_name=strategy_name,
                parameters=extra or None,
                mode=mode,
            )
            return json.dumps(result, ensure_ascii=True, indent=2)

        if command == "stop":
            arg = args[0] if args else ""
            if arg.lower().strip() == "all":
                result = self.orchestrator.stop_all()
                return json.dumps(result, ensure_ascii=True, indent=2)

            if arg:
                result = self.orchestrator.stop_strategy(arg)
                return json.dumps(result, ensure_ascii=True, indent=2)

            running = self.orchestrator.list_running_strategies()
            if not running:
                return "No active strategies."
            if len(running) == 1:
                result = self.orchestrator.stop_strategy(running[0])
                return json.dumps(result, ensure_ascii=True, indent=2)
            return "Multiple strategies are running. Use /stop <strategy> or /stop all."

        if command == "status":
            if args:
                status = self.orchestrator.get_strategy_status(args[0])
                if not status:
                    return "Strategy status not found."
                return _format_status(status)

            all_status = self.orchestrator.get_all_status()
            if not all_status:
                return "No active strategies."
            blocks = [_format_status(item) for item in all_status.values() if item]
            return "\n\n".join(blocks)

        if command == "pnl":
            parsed = _parse_pnl_args(args)
            mode = parsed["mode"]

            logger.info("PNL command: mode=%s", mode)

            try:
                broker_cfg = dict(self.orchestrator.broker_config)
                broker_cfg.setdefault("IS_PAPER", True)
                broker_cfg["IS_PAPER"] = mode != "live"

                report = get_pnl_report(broker_config=broker_cfg)

                # Convert to dict format for the formatter
                summary = {
                    "account_equity": report.equity,
                    "account_last_equity": report.last_equity,
                    "start_portfolio_value": report.base_value or report.cash,
                    "daily_pnl": report.pnl_today,
                    "weekly_pnl": report.pnl_week,
                    "alltime_pnl": report.pnl_alltime,
                    "total_pnl_pct": report.pnl_today_pct,
                    "positions": report.positions,
                    "closed_trades": report.closed_trades,
                    "total_realized_pnl_today": report.total_realized_pnl_today,
                    "trades_count_today": report.trades_count_today,
                    "period": "daily",
                }
                return _format_pnl_summary(summary)
            except Exception as exc:
                logger.exception("Failed to compute PnL for /pnl command: %s", exc)
                return f"No se pudo calcular el PnL: {exc}"

        if command == "set":
            if len(args) < 3:
                return (
                    "Usage:\n/set <strategy> <param> <value>\n"
                    "Example:\n/set LiveTestStrategy order_size_usd 10"
                )
            strategy_name = args[0]
            param_name = args[1]
            raw_value = " ".join(args[2:])
            value = _parse_value(raw_value)
            result = self.orchestrator.update_parameters(strategy_name, {param_name: value})
            return json.dumps(result, ensure_ascii=True, indent=2)

        return "Unknown command. Use /help"

    def _handle_chat(self, chat_id: int, user_id: int, text: str) -> str:
        watchlist_response = self._maybe_handle_watchlist_natural_language(text)
        if watchlist_response is not None:
            return watchlist_response
        report_response = self._maybe_handle_report_natural_language(chat_id, text)
        if report_response is not None:
            return report_response
        if self.alert_system is not None:
            self.alert_system.set_active_chat_id(chat_id)
            rsi_response = self._maybe_handle_rsi_natural_language(text, chat_id)
            if rsi_response is not None:
                return rsi_response
        if self.team is not None:
            session_id = f"telegram-{chat_id}"
            return run_team_message(
                self.team,
                text,
                user_id=str(user_id),
                session_id=session_id,
            )

        if self.agent is None:
            return (
                "Conversational mode needs OPENAI_API_KEY or ANTHROPIC_API_KEY.\n"
                "You can still use command mode: /help"
            )

        session_id = f"telegram-{chat_id}"
        return run_agent_message(
            self.agent,
            text,
            user_id=str(user_id),
            session_id=session_id,
        )

    def _maybe_handle_watchlist_natural_language(self, text: str) -> Optional[str]:
        if self.watchlist_store is None:
            return None
        lower = text.lower()
        delete_like = any(t in lower for t in {"borra", "elimina", "quita"})
        if delete_like:
            m_group = re.search(r"(?:borra|elimina|quita)\s+(?:grupo\s+)?([A-Za-z0-9_-]+)", text, flags=re.IGNORECASE)
            if m_group:
                target = m_group.group(1).strip()
                if "favorito" in lower and "listado" in lower:
                    try:
                        result = self.watchlist_store.remove_ticker(target, from_favorites=True)
                        if result.get("removed_from_favorites"):
                            return f"Quite {result['ticker']} del listado de favoritos."
                        return f"{result['ticker']} no estaba en favoritos."
                    except Exception as exc:
                        return f"No se pudo borrar de favoritos: {exc}"
                try:
                    cfg = self.watchlist_store.load()
                    if target.lower() in (cfg.groups or {}):
                        result = self.watchlist_store.remove_group(target)
                        return f"Grupo '{result['group']}' eliminado ({result['tickers_removed_count']} tickers)."
                except Exception:
                    pass
                try:
                    result = self.watchlist_store.remove_ticker(target, from_favorites=True)
                    if result.get("removed_from_groups") or result.get("removed_from_favorites"):
                        return (
                            f"Ticker {result['ticker']} eliminado de grupos={result.get('removed_from_groups') or []}"
                            + (" y favoritos" if result.get("removed_from_favorites") else "")
                        )
                    return f"No encontre {target} en watchlist/favoritos."
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
            return self.watchlist_store.summary_text()
        if (
            any(token in lower for token in {"que grupos", "qué grupos", "grupos de watchlist", "watchlist tienes"})
            or (("grupo" in lower or "grupos" in lower) and any(t in lower for t in {"tienes", "hay", "lista", "listar", "muestr"}))
        ):
            return self.watchlist_store.summary_text()
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
                cand = m2.group(1).strip().lower()
                if cand not in {"con", "las", "los", "siguientes", "stocks", "acciones"}:
                    group_name = cand

        symbols = self._extract_symbols(text)
        noise = {
            "CREA", "CREAR", "GRUPO", "FAVORITO", "FAVORITOS", "STOCK", "STOCKS", "ACCION", "ACCIONES",
            "SIGUIENTES", "CON", "QUE", "SE", "LLAME", "LAS", "LOS", "DE", "Y", "EL", "LA", "WATCHLIST",
        }
        dedup: List[str] = []
        seen = set()
        for s in symbols:
            if s.upper() in noise:
                continue
            if group_name and s.upper() == group_name.upper():
                continue
            if s in seen:
                continue
            seen.add(s)
            dedup.append(s)
        symbols = dedup
        if not symbols:
            return None

        if is_create_group:
            group_name = group_name or "favorites"
            added: List[str] = []
            for s in symbols:
                try:
                    self.watchlist_store.add_ticker(s, groups=[group_name], favorite=False)
                    added.append(s)
                except Exception:
                    continue
            if added:
                return f"Grupo '{group_name}' actualizado con {len(added)} tickers: " + ", ".join(added)
            return "No pude agregar tickers al grupo."

        if is_add_fav:
            added: List[str] = []
            for s in symbols:
                try:
                    self.watchlist_store.add_favorite(s)
                    added.append(s)
                except Exception:
                    continue
            if added:
                return "Favoritos actualizados: " + ", ".join(added)
        return None

    def _maybe_handle_report_natural_language(self, chat_id: int, text: str) -> Optional[str]:
        if self.portfolio_review_scheduler is None:
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
        if not group_name and self.watchlist_store is not None:
            try:
                cfg = self.watchlist_store.load()
                for g in (cfg.groups or {}).keys():
                    if re.search(rf"\\b{re.escape(g)}\\b", lower):
                        group_name = g
                        break
            except Exception:
                pass
        try:
            if group_name:
                started = self.portfolio_review_scheduler.trigger_async_with_group(kind, chat_id=chat_id, source="manual", group_name=group_name)
                if started:
                    return f"Generando reporte {kind} del grupo {group_name}... te lo envio cuando este listo."
                return f"Ya hay un reporte {kind} del grupo {group_name} ejecutandose para este chat."
            started = self.portfolio_review_scheduler.trigger_async(kind, chat_id=chat_id, source="manual")
            if started:
                return f"Generando reporte {kind}... te lo envio cuando este listo."
            return f"Ya hay un reporte {kind} ejecutandose para este chat."
        except Exception as exc:
            if group_name:
                return f"No se pudo iniciar reporte del grupo {group_name}: {exc}"
            return f"No se pudo iniciar reporte {kind}: {exc}"

    def _maybe_handle_rsi_natural_language(self, text: str, chat_id: int) -> Optional[str]:
        if self.alert_system is None:
            return None
        lower = text.lower()
        oversold_terms = {"oversold", "sobrevendida", "sobrevendido"}
        overbought_terms = {"overbought", "sobrecomprada", "sobrecomprado"}
        is_oversold = any(term in lower for term in oversold_terms)
        is_overbought = any(term in lower for term in overbought_terms)
        if not is_oversold and not is_overbought:
            return None

        symbols = self._extract_symbols(text)
        if not symbols:
            return "Dime el símbolo (ej: PLTR, NVDA) para crear la alerta RSI."

        created = []
        for symbol in symbols:
            rule = create_rsi_oversold(symbol) if is_oversold and not is_overbought else create_rsi_overbought(symbol)
            rule["id"] = f"{symbol}-{int(time.time())}"
            rule["chat_id"] = int(chat_id)
            saved = self.alert_system.add_rule(rule)
            created.append(saved)

        kind = "oversold" if is_oversold and not is_overbought else "overbought"
        lines = [f"RSI {kind} creado para:"]
        for rule in created:
            lines.append(f"• <code>{rule.get('symbol')}</code> | <i>{rule.get('id')}</i>")
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
            "RSI",
            "OVERBOUGHT",
            "OVERSOLD",
            "SOBRECOMPRADA",
            "SOBRECOMPRADO",
            "SOBREVENDIDA",
            "SOBREVENDIDO",
            "PARA",
            "QUIERO",
            "CREA",
            "ALERTA",
            "EL",
            "LA",
            "LOS",
            "LAS",
            "Y",
            "AND",
            "DE",
            "DEL",
            "EN",
            "UN",
            "UNA",
            "NUEVO",
            "NUEVA",
            "STOCKS",
            "STOCK",
            "ACCIONES",
            "ACCION",
        }

        symbols: List[str] = []
        pair_matches = re.findall(r"\b[A-Za-z]{2,6}[/-][A-Za-z]{2,6}\b", text)
        for token in pair_matches:
            symbols.append(token.upper().replace("-", "/"))

        word_matches = re.findall(r"\b[A-Za-z]{2,16}\b", text)
        for token in word_matches:
            upper = token.upper()
            if upper in stopwords:
                continue
            mapped = alias_map.get(upper, upper)
            if mapped not in symbols:
                symbols.append(mapped)

        return symbols

    def _handle_update(self, update: Dict[str, Any]) -> None:
        message = update.get("message") or {}
        text = (message.get("text") or "").strip()
        if not text:
            return

        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        chat_id = chat.get("id")
        user_id = sender.get("id", chat_id)

        if chat_id is None:
            return

        try:
            if text.startswith("/"):
                tokens = text.split()
                raw_command = tokens[0][1:]
                command = raw_command.split("@", 1)[0].lower()
                args = tokens[1:]
                response = self._handle_command(chat_id, user_id, command, args)
                parse_mode = "HTML"
            else:
                response = self._handle_chat(chat_id, user_id, text)
                parse_mode = None
            self._send_message(chat_id, response, parse_mode=parse_mode)
        except Exception as exc:
            logger.exception("Error handling update: %s", exc)
            self._send_message(chat_id, f"Error: {exc}")

    def run(self) -> None:
        logger.info("Starting Telegram polling bot")
        if self.stream_manager is not None:
            self.stream_manager.start_in_thread()
        if self.portfolio_review_scheduler is not None:
            self.portfolio_review_scheduler.start_in_thread()
        if self.news_scheduler is not None:
            self.news_scheduler.start_in_thread()
        offset: Optional[int] = None
        while True:
            try:
                updates = self._api_get_updates(offset)
                for update in updates:
                    offset = update["update_id"] + 1
                    self._handle_update(update)
            except KeyboardInterrupt:
                logger.info("Bot stopped by user")
                if self.stream_manager is not None:
                    self.stream_manager.stop()
                if self.portfolio_review_scheduler is not None:
                    self.portfolio_review_scheduler.stop()
                if self.news_scheduler is not None:
                    self.news_scheduler.stop()
                break
            except Exception as exc:
                logger.exception("Polling error: %s", exc)
                time.sleep(3)
