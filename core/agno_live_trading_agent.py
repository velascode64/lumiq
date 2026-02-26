"""
Agno conversational agent for direct manual trading via the Lumibot broker (no MCP).
"""

from __future__ import annotations

import inspect
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from agno.agent import Agent
from agno.tools import tool
from lumibot.brokers import Alpaca

try:
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest
except Exception:  # pragma: no cover
    OrderSide = None  # type: ignore[assignment]
    TimeInForce = None  # type: ignore[assignment]
    LimitOrderRequest = None  # type: ignore[assignment]
    MarketOrderRequest = None  # type: ignore[assignment]

try:
    from .agno_strategy_ops_agent import _json_dump, _resolve_model
except ImportError:
    from agno_strategy_ops_agent import _json_dump, _resolve_model


logger = logging.getLogger(__name__)


class LiveBrokerGateway:
    """Small wrapper around the Lumibot broker's underlying Alpaca API for manual trading tools."""

    def __init__(self, broker_config: Dict[str, Any]):
        self._broker_config = dict(broker_config or {})

    def _broker(self, mode: str = "paper") -> Alpaca:
        cfg = dict(self._broker_config)
        cfg.setdefault("IS_PAPER", True)
        cfg["IS_PAPER"] = str(mode).strip().lower() != "live"
        cfg["PAPER"] = cfg["IS_PAPER"]
        return Alpaca(cfg)

    @staticmethod
    def _is_crypto(symbol: str) -> bool:
        return "/" in (symbol or "")

    def _default_tif(self, symbol: str):
        if TimeInForce is None:
            return "gtc" if self._is_crypto(symbol) else "day"
        return TimeInForce.GTC if self._is_crypto(symbol) else TimeInForce.DAY

    def _order_side(self, side: str):
        if OrderSide is None:
            return side.lower()
        return OrderSide.BUY if str(side).lower() == "buy" else OrderSide.SELL

    def get_account_status(self, mode: str = "paper") -> Dict[str, Any]:
        broker = self._broker(mode)
        account = broker.api.get_account()
        positions = broker.api.get_all_positions() or []
        return {
            "mode": mode,
            "status": getattr(account, "status", None),
            "account_id": getattr(account, "id", None),
            "currency": getattr(account, "currency", None),
            "portfolio_value": float(getattr(account, "portfolio_value", 0) or 0),
            "cash": float(getattr(account, "cash", 0) or 0),
            "buying_power": float(getattr(account, "buying_power", 0) or 0),
            "equity": float(getattr(account, "equity", 0) or 0),
            "positions_count": len(positions),
        }

    def list_positions(self, mode: str = "paper") -> List[Dict[str, Any]]:
        broker = self._broker(mode)
        positions = broker.api.get_all_positions() or []
        out: List[Dict[str, Any]] = []
        for pos in positions:
            out.append(
                {
                    "symbol": getattr(pos, "symbol", None),
                    "qty": float(getattr(pos, "qty", 0) or 0),
                    "market_value": float(getattr(pos, "market_value", 0) or 0),
                    "avg_entry_price": float(getattr(pos, "avg_entry_price", 0) or 0),
                    "unrealized_pl": float(getattr(pos, "unrealized_pl", 0) or 0),
                    "side": "long" if float(getattr(pos, "qty", 0) or 0) >= 0 else "short",
                }
            )
        return out

    def get_position(self, symbol: str, mode: str = "paper") -> Dict[str, Any]:
        broker = self._broker(mode)
        pos = broker.api.get_open_position(symbol)
        return {
            "symbol": getattr(pos, "symbol", None),
            "qty": float(getattr(pos, "qty", 0) or 0),
            "market_value": float(getattr(pos, "market_value", 0) or 0),
            "avg_entry_price": float(getattr(pos, "avg_entry_price", 0) or 0),
            "unrealized_pl": float(getattr(pos, "unrealized_pl", 0) or 0),
        }

    def list_open_orders(self, mode: str = "paper", symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        broker = self._broker(mode)
        orders = broker.api.get_orders() or []
        out: List[Dict[str, Any]] = []
        for order in orders:
            if symbol and str(getattr(order, "symbol", "")).upper() != symbol.upper():
                continue
            status = str(getattr(order, "status", "")).lower()
            if status in {"canceled", "filled", "expired", "rejected"}:
                continue
            out.append(
                {
                    "id": str(getattr(order, "id", "")),
                    "client_order_id": getattr(order, "client_order_id", None),
                    "symbol": getattr(order, "symbol", None),
                    "side": str(getattr(order, "side", "")),
                    "type": str(getattr(order, "order_type", getattr(order, "type", ""))),
                    "qty": getattr(order, "qty", None),
                    "notional": getattr(order, "notional", None),
                    "status": str(getattr(order, "status", "")),
                }
            )
        return out

    def get_order(self, order_id: str, mode: str = "paper") -> Dict[str, Any]:
        broker = self._broker(mode)
        order = broker.api.get_order_by_id(order_id)
        return self._order_to_dict(order)

    def cancel_order(self, order_id: str, mode: str = "paper") -> Dict[str, Any]:
        broker = self._broker(mode)
        broker.api.cancel_order_by_id(order_id)
        return {"success": True, "order_id": order_id, "mode": mode, "message": "cancel requested"}

    def cancel_all_orders(self, mode: str = "paper") -> Dict[str, Any]:
        broker = self._broker(mode)
        result = broker.api.cancel_orders()
        return {"success": True, "mode": mode, "result": str(result)}

    def get_market_clock(self, mode: str = "paper") -> Dict[str, Any]:
        broker = self._broker(mode)
        clock = broker.api.get_clock()
        return {
            "is_open": bool(getattr(clock, "is_open", False)),
            "next_open": str(getattr(clock, "next_open", "")),
            "next_close": str(getattr(clock, "next_close", "")),
            "timestamp": str(getattr(clock, "timestamp", "")),
            "mode": mode,
        }

    def get_asset(self, symbol: str, mode: str = "paper") -> Dict[str, Any]:
        broker = self._broker(mode)
        asset = broker.api.get_asset(symbol)
        return {
            "symbol": getattr(asset, "symbol", None),
            "name": getattr(asset, "name", None),
            "class": getattr(asset, "asset_class", None),
            "status": getattr(asset, "status", None),
            "tradable": bool(getattr(asset, "tradable", False)),
            "fractionable": bool(getattr(asset, "fractionable", False)),
            "shortable": bool(getattr(asset, "shortable", False)),
            "easy_to_borrow": bool(getattr(asset, "easy_to_borrow", False)),
        }

    def place_market_order(
        self,
        symbol: str,
        side: str,
        mode: str = "paper",
        qty: Optional[float] = None,
        notional: Optional[float] = None,
        time_in_force: Optional[str] = None,
    ) -> Dict[str, Any]:
        if MarketOrderRequest is None or TimeInForce is None or OrderSide is None:
            raise RuntimeError("alpaca-py trading request classes are not available")
        if qty is None and notional is None:
            raise ValueError("Provide qty or notional")
        broker = self._broker(mode)
        tif = self._default_tif(symbol) if not time_in_force else getattr(TimeInForce, str(time_in_force).upper(), self._default_tif(symbol))
        payload: Dict[str, Any] = {
            "symbol": symbol,
            "side": self._order_side(side),
            "time_in_force": tif,
        }
        if qty is not None:
            payload["qty"] = float(qty)
        if notional is not None:
            payload["notional"] = float(notional)
        req = MarketOrderRequest(**payload)
        order = broker.api.submit_order(order_data=req)
        return self._order_to_dict(order) | {"mode": mode}

    def place_limit_order(
        self,
        symbol: str,
        side: str,
        limit_price: float,
        mode: str = "paper",
        qty: Optional[float] = None,
        notional: Optional[float] = None,
        time_in_force: Optional[str] = None,
        extended_hours: Optional[bool] = None,
    ) -> Dict[str, Any]:
        if LimitOrderRequest is None or TimeInForce is None or OrderSide is None:
            raise RuntimeError("alpaca-py trading request classes are not available")
        if qty is None and notional is None:
            raise ValueError("Provide qty or notional")
        broker = self._broker(mode)
        tif = self._default_tif(symbol) if not time_in_force else getattr(TimeInForce, str(time_in_force).upper(), self._default_tif(symbol))
        payload: Dict[str, Any] = {
            "symbol": symbol,
            "side": self._order_side(side),
            "time_in_force": tif,
            "limit_price": float(limit_price),
        }
        if qty is not None:
            payload["qty"] = float(qty)
        if notional is not None:
            payload["notional"] = float(notional)
        if extended_hours is not None and not self._is_crypto(symbol):
            payload["extended_hours"] = bool(extended_hours)
        req = LimitOrderRequest(**payload)
        order = broker.api.submit_order(order_data=req)
        return self._order_to_dict(order) | {"mode": mode}

    def close_position(
        self,
        symbol: str,
        mode: str = "paper",
        qty: Optional[float] = None,
        percentage: Optional[float] = None,
    ) -> Dict[str, Any]:
        broker = self._broker(mode)
        kwargs: Dict[str, Any] = {}
        if qty is not None:
            kwargs["qty"] = str(float(qty))
        if percentage is not None:
            kwargs["percentage"] = str(float(percentage))
        order = broker.api.close_position(symbol, **kwargs)
        return self._order_to_dict(order) | {"mode": mode}

    @staticmethod
    def _order_to_dict(order: Any) -> Dict[str, Any]:
        return {
            "id": str(getattr(order, "id", "")),
            "client_order_id": getattr(order, "client_order_id", None),
            "symbol": getattr(order, "symbol", None),
            "side": str(getattr(order, "side", "")),
            "status": str(getattr(order, "status", "")),
            "type": str(getattr(order, "order_type", getattr(order, "type", ""))),
            "qty": getattr(order, "qty", None),
            "notional": getattr(order, "notional", None),
            "filled_qty": getattr(order, "filled_qty", None),
            "filled_avg_price": getattr(order, "filled_avg_price", None),
            "limit_price": getattr(order, "limit_price", None),
            "submitted_at": str(getattr(order, "submitted_at", "")),
        }


def _build_live_trading_tools(gateway: LiveBrokerGateway) -> List[Any]:
    @tool
    def get_account_status(mode: str = "paper") -> str:
        """Get account summary (cash, equity, buying power, positions count)."""
        try:
            return _json_dump(gateway.get_account_status(mode=mode))
        except Exception as exc:
            return f"Failed to get account status: {exc}"

    @tool
    def list_positions(mode: str = "paper") -> str:
        """List open positions for the selected mode (paper/live)."""
        try:
            return _json_dump(gateway.list_positions(mode=mode))
        except Exception as exc:
            return f"Failed to list positions: {exc}"

    @tool
    def get_position(symbol: str, mode: str = "paper") -> str:
        """Get one open position by symbol."""
        try:
            return _json_dump(gateway.get_position(symbol=symbol, mode=mode))
        except Exception as exc:
            return f"Failed to get position: {exc}"

    @tool
    def list_open_orders(mode: str = "paper", symbol: Optional[str] = None) -> str:
        """List open/pending orders. Optionally filter by symbol."""
        try:
            return _json_dump(gateway.list_open_orders(mode=mode, symbol=symbol))
        except Exception as exc:
            return f"Failed to list open orders: {exc}"

    @tool
    def get_order(order_id: str, mode: str = "paper") -> str:
        """Get a specific order by order_id."""
        try:
            return _json_dump(gateway.get_order(order_id=order_id, mode=mode))
        except Exception as exc:
            return f"Failed to get order: {exc}"

    @tool
    def cancel_order(order_id: str, mode: str = "paper") -> str:
        """Cancel a single order by order_id."""
        try:
            return _json_dump(gateway.cancel_order(order_id=order_id, mode=mode))
        except Exception as exc:
            return f"Failed to cancel order: {exc}"

    @tool
    def cancel_all_orders(mode: str = "paper") -> str:
        """Cancel all open orders."""
        try:
            return _json_dump(gateway.cancel_all_orders(mode=mode))
        except Exception as exc:
            return f"Failed to cancel all orders: {exc}"

    @tool
    def get_market_clock(mode: str = "paper") -> str:
        """Get stock market clock (open/closed and next open/close)."""
        try:
            return _json_dump(gateway.get_market_clock(mode=mode))
        except Exception as exc:
            return f"Failed to get market clock: {exc}"

    @tool
    def get_asset(symbol: str, mode: str = "paper") -> str:
        """Get asset metadata (tradable, fractionable, class, status)."""
        try:
            return _json_dump(gateway.get_asset(symbol=symbol, mode=mode))
        except Exception as exc:
            return f"Failed to get asset: {exc}"

    @tool
    def place_market_order(
        symbol: str,
        side: str,
        mode: str = "paper",
        qty: Optional[float] = None,
        notional: Optional[float] = None,
        time_in_force: Optional[str] = None,
    ) -> str:
        """Place a market order. Provide qty or notional. Crypto supports 24/7 via Alpaca crypto symbols like ETH/USD."""
        try:
            return _json_dump(
                gateway.place_market_order(
                    symbol=symbol,
                    side=side,
                    mode=mode,
                    qty=qty,
                    notional=notional,
                    time_in_force=time_in_force,
                )
            )
        except Exception as exc:
            return f"Failed to place market order: {exc}"

    @tool
    def place_limit_order(
        symbol: str,
        side: str,
        limit_price: float,
        mode: str = "paper",
        qty: Optional[float] = None,
        notional: Optional[float] = None,
        time_in_force: Optional[str] = None,
        extended_hours: Optional[bool] = None,
    ) -> str:
        """Place a limit order. Provide qty or notional. For stocks, extended_hours can be set when supported."""
        try:
            return _json_dump(
                gateway.place_limit_order(
                    symbol=symbol,
                    side=side,
                    limit_price=limit_price,
                    mode=mode,
                    qty=qty,
                    notional=notional,
                    time_in_force=time_in_force,
                    extended_hours=extended_hours,
                )
            )
        except Exception as exc:
            return f"Failed to place limit order: {exc}"

    @tool
    def close_position(symbol: str, mode: str = "paper", qty: Optional[float] = None, percentage: Optional[float] = None) -> str:
        """Close a position fully or partially (qty or percentage)."""
        try:
            return _json_dump(gateway.close_position(symbol=symbol, mode=mode, qty=qty, percentage=percentage))
        except Exception as exc:
            return f"Failed to close position: {exc}"

    return [
        get_account_status,
        list_positions,
        get_position,
        list_open_orders,
        get_order,
        cancel_order,
        cancel_all_orders,
        get_market_clock,
        get_asset,
        place_market_order,
        place_limit_order,
        close_position,
    ]


def _parse_simple_trade_intent(text: str) -> Optional[Dict[str, Any]]:
    raw = (text or "").strip()
    lower = raw.lower()
    side = None
    if any(k in lower for k in ["compra", "comprar", "buy"]):
        side = "buy"
    elif any(k in lower for k in ["vende", "vender", "sell"]):
        side = "sell"
    if not side:
        return None

    # Symbol like ETH/USD or AAPL
    sym_match = re.search(r"\b([A-Z]{1,10}(?:/[A-Z]{1,10})?)\b", raw)
    symbol = sym_match.group(1) if sym_match else None
    if not symbol:
        return None

    notional_match = re.search(r"\$\s*([0-9]+(?:\.[0-9]+)?)", raw)
    qty_match = re.search(r"\b(?:buy|sell|compra|vende|comprar|vender)\s+([0-9]+(?:\.[0-9]+)?)\b", lower)

    payload: Dict[str, Any] = {"side": side, "symbol": symbol, "type": "market"}
    if notional_match:
        payload["notional"] = float(notional_match.group(1))
    elif qty_match:
        payload["qty"] = float(qty_match.group(1))
    else:
        return None
    return payload


def _normalize_enum_text(value: Any) -> str:
    text = str(value or "").strip()
    if "." in text:
        text = text.split(".")[-1]
    return text


def _format_order_result_for_user(result: Dict[str, Any]) -> str:
    try:
        symbol = str(result.get("symbol") or "?")
        side = _normalize_enum_text(result.get("side")).upper() or "ORDER"
        status = _normalize_enum_text(result.get("status")).replace("_", " ").upper() or "UNKNOWN"
        order_type = _normalize_enum_text(result.get("type")).upper() or "ORDER"
        mode = str(result.get("mode") or "paper").lower()
        order_id = str(result.get("id") or "")
        client_order_id = str(result.get("client_order_id") or "")
        qty = result.get("qty")
        notional = result.get("notional")
        filled_qty = result.get("filled_qty")
        filled_avg_price = result.get("filled_avg_price")

        size_text = None
        if notional not in (None, "", "None"):
            size_text = f"${float(notional):,.2f} notional"
        elif qty not in (None, "", "None"):
            size_text = f"{float(qty):g} qty"
        else:
            size_text = "size not returned"

        lines = [
            f"{side} {order_type} order submitted for {symbol} ({mode})",
            f"Status: {status}",
            f"Size: {size_text}",
        ]
        if filled_qty not in (None, "", "0", 0):
            fill_line = f"Filled: {filled_qty}"
            if filled_avg_price not in (None, "", "None"):
                try:
                    fill_line += f" @ ${float(filled_avg_price):,.4f}"
                except Exception:
                    fill_line += f" @ {filled_avg_price}"
            lines.append(fill_line)
        if order_id:
            lines.append(f"Order ID: {order_id}")
        if client_order_id:
            lines.append(f"Client Order ID: {client_order_id}")
        return "\n".join(lines)
    except Exception:
        return _json_dump(result)


def create_live_trading_agent(broker_config: Optional[Dict[str, Any]] = None) -> Optional[Agent]:
    """Create a conversational Agno agent dedicated to direct broker execution via Lumibot broker tools."""
    model = _resolve_model()
    if model is None:
        return None
    if not broker_config:
        return None

    gateway = LiveBrokerGateway(broker_config)
    tools = _build_live_trading_tools(gateway)

    instructions = [
        "You are the LiveTradingAgent for direct broker execution using the Lumibot broker tools (backed by Alpaca in this environment).",
        "Your only responsibility is manual order execution and broker/account/order management (buy, sell, close, cancel, order status, positions, account).",
        "Do NOT manage Lumibot strategies, strategy parameters, or strategy lifecycle. Those belong to the StrategyOpsAgent.",
        "For explicit executable trade intents, you must call the appropriate order tool immediately and then summarize the result.",
        "Do not answer an executable trade intent with a fake execution message if no tool call was made.",
        "Default order type to MARKET when the user does not specify order type.",
        "Do not ask 'paper or live'. The execution mode policy is injected by the caller.",
        "Only ask follow-up questions when required parameters are missing (e.g., no symbol or no qty/notional).",
        "Use get_asset/get_market_clock when needed for stock trading validation context. Crypto symbols (e.g., ETH/USD) are 24/7.",
        "Respond in the same language as the user's latest message (Spanish or English).",
    ]

    desired_kwargs = {
        "name": "LiveTradingAgent",
        "model": model,
        "tools": tools,
        "role": "Broker execution specialist using Lumibot broker tools",
        "goal": "Execute valid manual broker operations accurately and safely with low latency.",
        "success_criteria": "Use order/account tools correctly, avoid strategy administration, and return concise execution summaries.",
        "instructions": instructions,
        "show_tool_calls": False,
        "add_history_to_messages": True,
        "num_history_runs": 8,
        "markdown": False,
    }
    accepted = set(inspect.signature(Agent.__init__).parameters.keys())
    filtered_kwargs = {key: value for key, value in desired_kwargs.items() if key in accepted}
    agent = Agent(**filtered_kwargs)
    setattr(agent, "_live_broker_gateway", gateway)
    return agent


def run_live_trading_message(
    agent: Agent,
    message: str,
    user_id: str,
    session_id: str,
    trade_execution_mode: str = "paper",
) -> str:
    """Run a manual-trading message through the LiveTradingAgent and return plain text output."""
    logger.info(
        "Agno LiveTrading input | agent=%s | session_id=%s | user_id=%s | message=%s",
        getattr(agent, "name", None) or agent.__class__.__name__,
        session_id,
        user_id,
        message,
    )

    trade_execution_mode = (trade_execution_mode or "paper").strip().lower()
    if trade_execution_mode not in {"paper", "live"}:
        trade_execution_mode = "paper"

    gateway: Optional[LiveBrokerGateway] = getattr(agent, "_live_broker_gateway", None)
    if gateway is not None:
        parsed = _parse_simple_trade_intent(message)
        if parsed:
            try:
                result = gateway.place_market_order(
                    symbol=parsed["symbol"],
                    side=parsed["side"],
                    mode=trade_execution_mode,
                    qty=parsed.get("qty"),
                    notional=parsed.get("notional"),
                )
                logger.info(
                    "Agno LiveTrading fast-path executed | session_id=%s | mode=%s | side=%s | symbol=%s",
                    session_id,
                    trade_execution_mode,
                    parsed.get("side"),
                    parsed.get("symbol"),
                )
                return _format_order_result_for_user(result)
            except Exception as exc:
                logger.exception("LiveTradingAgent fast-path failed; falling back to agent tool execution: %s", exc)

    final_message = (
        "EXECUTE broker tools for this request; do not reply with text only if the request is executable.\n"
        f"Execution mode policy: use mode='{trade_execution_mode}' and do not ask whether to use paper or live.\n"
        "If the user omitted order type, default to MARKET.\n"
        "If side + symbol + qty/notional are present, execute immediately.\n"
        f"User request: {message}"
    )
    response = agent.run(final_message, user_id=user_id, session_id=session_id)

    logger.info(
        "Agno LiveTrading output | agent=%s | session_id=%s | agent_name=%s | backend=lumibot_broker",
        getattr(agent, "name", None) or agent.__class__.__name__,
        session_id,
        getattr(response, "agent_name", None),
    )

    content = getattr(response, "content", None)
    if content is None:
        return "Could not generate a response."
    if isinstance(content, str):
        return content
    return _json_dump(content)
