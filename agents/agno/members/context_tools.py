from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from agno.tools import tool

try:
    from .live_trading_agent import LiveBrokerGateway
except ImportError:
    from agents.agno.members.live_trading_agent import LiveBrokerGateway


def _json_dump(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=True, default=str, indent=2)
    except Exception:
        return str(data)


def build_context_tools(
    *,
    orchestrator=None,
    alert_system=None,
    watchlist_store=None,
    live_gateway: Optional[LiveBrokerGateway] = None,
) -> List[Any]:
    """
    Build high-signal context tools for common user intents.

    These are the equivalents of the summary/context tools used in Mastra:
    one tool gives the agent the real current state, then the agent can drill
    down with lower-level tools only when needed.
    """
    tools: List[Any] = []

    if watchlist_store is not None:
        @tool
        def get_watchlist_context(group_name: Optional[str] = None) -> str:
            """
            Read the real watchlist from storage.

            Use this first for questions like:
            - "give me my watchlist"
            - "what tickers am I following?"
            - "show my watchlist groups"
            - "what is in my oil group?"
            """
            try:
                cfg = watchlist_store.load()
                groups = cfg.groups or {}
                requested_group = (group_name or "").strip().lower() or None
                if requested_group:
                    tickers = list(groups.get(requested_group) or [])
                    return _json_dump(
                        {
                            "requested_group": requested_group,
                            "group_exists": requested_group in groups,
                            "tickers": tickers,
                            "count": len(tickers),
                            "favorites": list(cfg.favorites or []),
                        }
                    )

                all_tickers = cfg.all_group_tickers()
                return _json_dump(
                    {
                        "groups": [
                            {
                                "name": name,
                                "tickers": list(tickers or []),
                                "count": len(tickers or []),
                            }
                            for name, tickers in sorted(groups.items())
                        ],
                        "favorites": list(cfg.favorites or []),
                        "benchmarks": dict(cfg.benchmarks or {}),
                        "followed_tickers": all_tickers,
                        "followed_tickers_count": len(all_tickers),
                    }
                )
            except Exception as exc:
                return f"Failed to get watchlist context: {exc}"

        @tool
        def get_followed_tickers(group_name: Optional[str] = None) -> str:
            """
            Return only the tickers the user is following.

            Use this for direct ticker-list questions when the user does not
            need a long summary.
            """
            try:
                cfg = watchlist_store.load()
                requested_group = (group_name or "").strip().lower() or None
                if requested_group:
                    tickers = list((cfg.groups or {}).get(requested_group) or [])
                    return _json_dump(
                        {
                            "group_name": requested_group,
                            "tickers": tickers,
                            "count": len(tickers),
                        }
                    )
                tickers = cfg.all_group_tickers()
                return _json_dump({"tickers": tickers, "count": len(tickers)})
            except Exception as exc:
                return f"Failed to get followed tickers: {exc}"

        tools.extend([get_watchlist_context, get_followed_tickers])

    if alert_system is not None:
        @tool
        def get_alerts_context(
            symbol: Optional[str] = None,
            active_only: bool = True,
        ) -> str:
            """
            Read the real alert rules for the current chat scope.

            Use this first for questions like:
            - "give me my alerts"
            - "what alerts do I have?"
            - "show alerts for NVDA"
            """
            try:
                chat_id = alert_system.get_active_chat_id()
                rules = list(alert_system.list_rules() or [])
                if chat_id is not None:
                    rules = [rule for rule in rules if int(rule.get("chat_id") or 0) == int(chat_id)]
                if symbol:
                    target_symbol = str(symbol).strip().upper()
                    rules = [rule for rule in rules if str(rule.get("symbol") or "").strip().upper() == target_symbol]
                if active_only:
                    rules = [rule for rule in rules if bool(rule.get("active", True))]
                return _json_dump(
                    {
                        "chat_id": chat_id,
                        "symbol_filter": (symbol or "").strip().upper() or None,
                        "active_only": bool(active_only),
                        "count": len(rules),
                        "rules": rules,
                    }
                )
            except Exception as exc:
                return f"Failed to get alerts context: {exc}"

        tools.append(get_alerts_context)

    if live_gateway is not None:
        @tool
        def get_user_execution_context(mode: str = "paper") -> str:
            """
            Read live broker execution state in one call.

            Use this first for:
            - portfolio/account questions
            - positions
            - open orders
            - current execution state
            """
            try:
                payload = {
                    "account": live_gateway.get_account_status(mode=mode),
                    "positions": live_gateway.list_positions(mode=mode),
                    "open_orders": live_gateway.list_open_orders(mode=mode),
                    "market_clock": live_gateway.get_market_clock(mode=mode),
                }
                return _json_dump(payload)
            except Exception as exc:
                return f"Failed to get execution context: {exc}"

        @tool
        def get_user_portfolio_value(mode: str = "paper") -> str:
            """
            Return current account value, cash, equity, and buying power.

            Use this for direct questions about invested value or account value.
            """
            try:
                account = live_gateway.get_account_status(mode=mode)
                return _json_dump(
                    {
                        "mode": mode,
                        "portfolio_value": account.get("portfolio_value"),
                        "cash": account.get("cash"),
                        "equity": account.get("equity"),
                        "buying_power": account.get("buying_power"),
                        "positions_count": account.get("positions_count"),
                    }
                )
            except Exception as exc:
                return f"Failed to get portfolio value: {exc}"

        tools.extend([get_user_execution_context, get_user_portfolio_value])

    if orchestrator is not None:
        @tool
        def get_user_strategy_context(
            strategy_name: Optional[str] = None,
        ) -> str:
            """
            Read the current strategy state from Lumiq.

            Use this first for:
            - running strategies
            - strategy status
            - current strategy configuration/state
            """
            try:
                running = orchestrator.list_running_strategies()
                payload: Dict[str, Any] = {
                    "running_strategies": running,
                    "running_count": len(running or []),
                    "system_status": orchestrator.get_all_status(),
                }
                if strategy_name:
                    payload["requested_strategy"] = strategy_name
                    payload["strategy_status"] = orchestrator.get_strategy_status(strategy_name)
                return _json_dump(payload)
            except Exception as exc:
                return f"Failed to get strategy context: {exc}"

        tools.append(get_user_strategy_context)

    return tools
