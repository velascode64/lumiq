"""
Alpaca PnL utilities - Clean implementation using Alpaca's native APIs.

Provides:
- Daily P&L: from account.equity - account.last_equity
- Weekly P&L: from portfolio_history with period="1W"
- All-time P&L: from portfolio_history with period="1A"
- Positions breakdown with unrealized P&L
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Prevent lumibot.credentials from auto-spawning a hidden broker/stream on import.
os.environ.setdefault("TRADING_BROKER", "none")

from lumibot.brokers import Alpaca

logger = logging.getLogger(__name__)


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


@dataclass
class ClosedTrade:
    """Represents a closed trade (round-trip: buy + sell)."""
    symbol: str
    side: str  # "long" or "short"
    qty: float
    entry_price: float
    exit_price: float
    realized_pnl: float
    closed_at: str


@dataclass
class PnLReport:
    """Complete P&L report with daily, weekly, and all-time data."""

    # Account info
    equity: float = 0.0
    last_equity: float = 0.0
    cash: float = 0.0
    buying_power: float = 0.0

    # P&L values
    pnl_today: float = 0.0
    pnl_today_pct: float = 0.0
    pnl_week: Optional[float] = None
    pnl_week_pct: Optional[float] = None
    pnl_alltime: Optional[float] = None
    pnl_alltime_pct: Optional[float] = None

    # Open positions (unrealized)
    positions: List[Dict[str, Any]] = field(default_factory=list)
    total_unrealized_pnl: float = 0.0
    total_unrealized_pnl_today: float = 0.0

    # Closed trades today (realized)
    closed_trades: List[Dict[str, Any]] = field(default_factory=list)
    total_realized_pnl_today: float = 0.0
    trades_count_today: int = 0

    # Metadata
    timestamp: str = ""
    account_created: Optional[str] = None
    base_value: Optional[float] = None  # Initial deposit/starting value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "equity": self.equity,
            "last_equity": self.last_equity,
            "cash": self.cash,
            "buying_power": self.buying_power,
            "pnl_today": self.pnl_today,
            "pnl_today_pct": self.pnl_today_pct,
            "pnl_week": self.pnl_week,
            "pnl_week_pct": self.pnl_week_pct,
            "pnl_alltime": self.pnl_alltime,
            "pnl_alltime_pct": self.pnl_alltime_pct,
            "positions": self.positions,
            "total_unrealized_pnl": self.total_unrealized_pnl,
            "total_unrealized_pnl_today": self.total_unrealized_pnl_today,
            "closed_trades": self.closed_trades,
            "total_realized_pnl_today": self.total_realized_pnl_today,
            "trades_count_today": self.trades_count_today,
            "timestamp": self.timestamp,
            "account_created": self.account_created,
            "base_value": self.base_value,
        }


def _fetch_portfolio_history_by_period(api: Any, period: str) -> Optional[Dict[str, Any]]:
    """
    Fetch portfolio history using Alpaca's period parameter.

    Args:
        api: Alpaca API client
        period: "1D", "1W", "1M", "1A" (day, week, month, year)

    Returns:
        Dict with profit_loss, profit_loss_pct, base_value, or None if failed
    """
    if not hasattr(api, "get_portfolio_history"):
        return None

    try:
        from alpaca.trading.requests import GetPortfolioHistoryRequest
    except ImportError:
        logger.warning("GetPortfolioHistoryRequest not available")
        return None

    try:
        request = GetPortfolioHistoryRequest(period=period)
        history = api.get_portfolio_history(request)

        profit_loss = _get_attr(history, "profit_loss") or []
        profit_loss_pct = _get_attr(history, "profit_loss_pct") or []
        base_value = _get_attr(history, "base_value")
        equity = _get_attr(history, "equity") or []

        # Get the last values (most recent)
        pnl = profit_loss[-1] if profit_loss else None
        pnl_pct = profit_loss_pct[-1] if profit_loss_pct else None

        return {
            "profit_loss": _to_float(pnl) if pnl is not None else None,
            "profit_loss_pct": _to_float(pnl_pct) * 100 if pnl_pct is not None else None,
            "base_value": _to_float(base_value) if base_value else None,
            "points": len(profit_loss),
            "equity_start": _to_float(equity[0]) if equity else None,
            "equity_end": _to_float(equity[-1]) if equity else None,
        }
    except Exception as exc:
        logger.warning("Failed to fetch portfolio history for period %s: %s", period, exc)
        return None


def _fetch_positions(api: Any) -> List[Dict[str, Any]]:
    """Fetch all open positions with P&L details."""
    if not hasattr(api, "get_all_positions"):
        return []

    try:
        positions = api.get_all_positions() or []
        result = []
        for pos in positions:
            result.append({
                "symbol": _get_attr(pos, "symbol"),
                "qty": _to_float(_get_attr(pos, "qty")),
                "side": _get_attr(pos, "side"),
                "market_value": _to_float(_get_attr(pos, "market_value")),
                "cost_basis": _to_float(_get_attr(pos, "cost_basis")),
                "avg_entry_price": _to_float(_get_attr(pos, "avg_entry_price")),
                "current_price": _to_float(_get_attr(pos, "current_price")),
                "unrealized_pl": _to_float(_get_attr(pos, "unrealized_pl")),
                "unrealized_plpc": _to_float(_get_attr(pos, "unrealized_plpc")) * 100,
                "unrealized_intraday_pl": _to_float(_get_attr(pos, "unrealized_intraday_pl")),
                "unrealized_intraday_plpc": _to_float(_get_attr(pos, "unrealized_intraday_plpc")) * 100,
            })
        return result
    except Exception as exc:
        logger.warning("Failed to fetch positions: %s", exc)
        return []


def _fetch_closed_orders_today(api: Any) -> List[Dict[str, Any]]:
    """
    Fetch all closed/filled orders from today.

    Returns a list of orders with their fill details.
    """
    if not hasattr(api, "get_orders"):
        return []

    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
    except ImportError:
        logger.warning("alpaca-py GetOrdersRequest not available")
        return []

    try:
        # Get today's date at midnight UTC
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        request = GetOrdersRequest(
            status=QueryOrderStatus.CLOSED,
            after=today_start,
            direction="desc",  # Most recent first
            limit=500,
        )
        orders = api.get_orders(filter=request)

        result = []
        for order in orders or []:
            status = str(_get_attr(order, "status", "")).lower()
            if status != "filled":
                continue

            filled_qty = _to_float(_get_attr(order, "filled_qty"))
            if filled_qty <= 0:
                continue

            result.append({
                "id": str(_get_attr(order, "id", "")),
                "symbol": _get_attr(order, "symbol"),
                "side": str(_get_attr(order, "side", "")).lower(),
                "qty": filled_qty,
                "filled_avg_price": _to_float(_get_attr(order, "filled_avg_price")),
                "filled_at": str(_get_attr(order, "filled_at", "")),
                "order_type": str(_get_attr(order, "order_type", "")),
                "notional": filled_qty * _to_float(_get_attr(order, "filled_avg_price")),
            })
        return result
    except Exception as exc:
        logger.warning("Failed to fetch closed orders: %s", exc)
        return []


def _calculate_realized_pnl_from_orders(orders: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Calculate realized P&L per symbol from a list of filled orders.

    Uses FIFO matching to pair buys and sells.
    Returns dict keyed by symbol with realized P&L and trade details.
    """
    from collections import deque

    # Group orders by symbol
    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for order in orders:
        symbol = order.get("symbol", "UNKNOWN")
        by_symbol.setdefault(symbol, []).append(order)

    result: Dict[str, Dict[str, Any]] = {}

    for symbol, symbol_orders in by_symbol.items():
        # Sort by filled_at time
        symbol_orders.sort(key=lambda x: x.get("filled_at", ""))

        buy_lots: deque = deque()  # (qty, price)
        sell_lots: deque = deque()

        realized_pnl = 0.0
        total_buy_qty = 0.0
        total_sell_qty = 0.0
        total_buy_value = 0.0
        total_sell_value = 0.0
        trades = []

        for order in symbol_orders:
            side = order.get("side", "")
            qty = order.get("qty", 0.0)
            price = order.get("filled_avg_price", 0.0)

            if side == "buy":
                total_buy_qty += qty
                total_buy_value += qty * price

                # Try to close short positions first
                remaining = qty
                while remaining > 0 and sell_lots:
                    sell_qty, sell_price = sell_lots[0]
                    close_qty = min(remaining, sell_qty)
                    pnl = (sell_price - price) * close_qty  # Short: profit when buy lower
                    realized_pnl += pnl
                    trades.append({
                        "type": "short_cover",
                        "qty": close_qty,
                        "entry_price": sell_price,
                        "exit_price": price,
                        "pnl": pnl,
                    })
                    sell_qty -= close_qty
                    remaining -= close_qty
                    if sell_qty <= 0:
                        sell_lots.popleft()
                    else:
                        sell_lots[0] = (sell_qty, sell_price)

                if remaining > 0:
                    buy_lots.append((remaining, price))

            elif side == "sell":
                total_sell_qty += qty
                total_sell_value += qty * price

                # Try to close long positions first
                remaining = qty
                while remaining > 0 and buy_lots:
                    buy_qty, buy_price = buy_lots[0]
                    close_qty = min(remaining, buy_qty)
                    pnl = (price - buy_price) * close_qty  # Long: profit when sell higher
                    realized_pnl += pnl
                    trades.append({
                        "type": "long_close",
                        "qty": close_qty,
                        "entry_price": buy_price,
                        "exit_price": price,
                        "pnl": pnl,
                    })
                    buy_qty -= close_qty
                    remaining -= close_qty
                    if buy_qty <= 0:
                        buy_lots.popleft()
                    else:
                        buy_lots[0] = (buy_qty, buy_price)

                if remaining > 0:
                    sell_lots.append((remaining, price))

        result[symbol] = {
            "symbol": symbol,
            "realized_pnl": realized_pnl,
            "total_buy_qty": total_buy_qty,
            "total_sell_qty": total_sell_qty,
            "total_buy_value": total_buy_value,
            "total_sell_value": total_sell_value,
            "order_count": len(symbol_orders),
            "trade_count": len(trades),
            "trades": trades,
            "open_long_qty": sum(q for q, _ in buy_lots),
            "open_short_qty": sum(q for q, _ in sell_lots),
        }

    return result


def get_pnl_report(broker_config: Dict[str, Any]) -> PnLReport:
    """
    Get a complete P&L report with daily, weekly, and all-time data.

    This is the main function to use for P&L reporting. It fetches:
    - Daily P&L from account.equity - account.last_equity
    - Weekly P&L from portfolio_history(period="1W")
    - All-time P&L from portfolio_history(period="1A")
    - All open positions with unrealized P&L

    Args:
        broker_config: Alpaca broker configuration dict

    Returns:
        PnLReport dataclass with all P&L data
    """
    # PnL summary only needs REST calls; keep stream disconnected to prevent 429 storms.
    broker = Alpaca(broker_config, connect_stream=False)
    api = broker.api
    report = PnLReport()
    report.timestamp = datetime.now(timezone.utc).isoformat()

    # 1. Get account info for daily P&L
    try:
        account = api.get_account()
        report.equity = _to_float(_get_attr(account, "equity"))
        report.last_equity = _to_float(_get_attr(account, "last_equity"))
        report.cash = _to_float(_get_attr(account, "cash"))
        report.buying_power = _to_float(_get_attr(account, "buying_power"))
        report.account_created = str(_get_attr(account, "created_at", ""))

        # Daily P&L is simply current equity - last equity (from previous close)
        report.pnl_today = report.equity - report.last_equity
        if report.last_equity > 0:
            report.pnl_today_pct = (report.pnl_today / report.last_equity) * 100
    except Exception as exc:
        logger.error("Failed to get account info: %s", exc)

    # 2. Get weekly P&L from portfolio_history
    weekly = _fetch_portfolio_history_by_period(api, "1W")
    if weekly:
        report.pnl_week = weekly.get("profit_loss")
        report.pnl_week_pct = weekly.get("profit_loss_pct")

    # 3. Get all-time P&L from portfolio_history (1 year max)
    alltime = _fetch_portfolio_history_by_period(api, "1A")
    if alltime:
        report.pnl_alltime = alltime.get("profit_loss")
        report.pnl_alltime_pct = alltime.get("profit_loss_pct")
        report.base_value = alltime.get("base_value")

    # 4. Get all open positions
    report.positions = _fetch_positions(api)
    for pos in report.positions:
        report.total_unrealized_pnl += pos.get("unrealized_pl", 0.0)
        report.total_unrealized_pnl_today += pos.get("unrealized_intraday_pl", 0.0)

    # 5. Get closed trades today and calculate realized P&L
    closed_orders = _fetch_closed_orders_today(api)
    if closed_orders:
        pnl_by_symbol = _calculate_realized_pnl_from_orders(closed_orders)
        report.trades_count_today = len(closed_orders)

        for symbol, data in pnl_by_symbol.items():
            realized = data.get("realized_pnl", 0.0)
            report.total_realized_pnl_today += realized
            report.closed_trades.append({
                "symbol": symbol,
                "realized_pnl": realized,
                "order_count": data.get("order_count", 0),
                "trade_count": data.get("trade_count", 0),
                "total_buy_qty": data.get("total_buy_qty", 0),
                "total_sell_qty": data.get("total_sell_qty", 0),
                "total_buy_value": data.get("total_buy_value", 0),
                "total_sell_value": data.get("total_sell_value", 0),
            })

    return report


# ============================================================================
# Legacy function for backwards compatibility with telegram_trading_bot.py
# ============================================================================

def get_realized_pnl_summary(
    broker_config: Dict[str, Any],
    period: str = "weekly",
    strategy_name: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Legacy function - returns P&L summary in the old format.

    For new code, use get_pnl_report() instead.
    """
    report = get_pnl_report(broker_config)

    # Map period to the appropriate P&L values
    if period in {"daily", "day", "1d"}:
        total_pnl = report.pnl_today
        total_pnl_pct = report.pnl_today_pct
    elif period in {"weekly", "week", "1w"}:
        total_pnl = report.pnl_week
        total_pnl_pct = report.pnl_week_pct
    else:
        total_pnl = report.pnl_alltime
        total_pnl_pct = report.pnl_alltime_pct

    # Convert positions to old format
    positions_old = []
    for pos in report.positions:
        positions_old.append({
            "symbol": pos["symbol"],
            "qty": pos["qty"],
            "market_value": pos["market_value"],
            "cost_basis": pos["cost_basis"],
            "unrealized_pl": pos["unrealized_pl"],
            "unrealized_plpc": pos["unrealized_plpc"],
            "unrealized_intraday_pl": pos["unrealized_intraday_pl"],
            "unrealized_intraday_plpc": pos["unrealized_intraday_plpc"],
        })

    return {
        "period": period,
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else report.timestamp,
        "pnl_source": "alpaca_native",
        "note": None,
        "start_portfolio_value": report.base_value,
        "end_portfolio_value": report.equity,
        "transactions_count": None,
        "transactions_note": None,
        "account_equity": report.equity,
        "account_last_equity": report.last_equity,
        "daily_pnl": report.pnl_today,
        "weekly_pnl": report.pnl_week,
        "alltime_pnl": report.pnl_alltime,
        "positions": positions_old,
        "strategy_filter": {
            "strategy_name": strategy_name,
            "applied": False,
            "reason": "strategy filtering not supported in native mode",
        },
        "total_realized_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "total_fees": 0.0,
        "total_fills": 0,
        "per_symbol": {},
        "portfolio_history": {
            "timeframe": None,
            "base_value": report.base_value,
            "points": None,
        },
    }
