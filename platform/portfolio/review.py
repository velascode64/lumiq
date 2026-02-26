"""
Portfolio review monitor (Telegram-focused).

Provides:
- Watchlist storage (groups/favorites/optional benchmarks)
- Daily/weekly text reports for portfolio + watchlist
- Background scheduler (NYSE timezone) with async execution and Telegram callback
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo

try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None

from lumibot.brokers import Alpaca

try:
    from ..alerts.services.alpaca_data_service import AlpacaDataService
except ImportError:
    from platform.alerts.services.alpaca_data_service import AlpacaDataService

logger = logging.getLogger(__name__)

NYSE_TZ = "America/New_York"


def _now_ny() -> datetime:
    return datetime.now(ZoneInfo(NYSE_TZ))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _parse_chat_ids_from_env() -> List[int]:
    ids: List[int] = []
    raw = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if raw:
        try:
            ids.append(int(raw))
        except Exception:
            pass
    allowed = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    if allowed:
        for token in allowed.replace(";", ",").split(","):
            token = token.strip()
            if not token:
                continue
            try:
                cid = int(token)
                if cid not in ids:
                    ids.append(cid)
            except Exception:
                continue
    return ids


def _normalize_symbol(symbol: str) -> str:
    sym = (symbol or "").strip().upper()
    if not sym:
        return sym
    if "/" in sym:
        return sym.replace("-", "/")
    if "-" in sym and len(sym) <= 12:
        return sym.replace("-", "/")
    return sym


def _is_crypto_symbol(symbol: str) -> bool:
    s = _normalize_symbol(symbol)
    return "/" in s or s.endswith("USD")


def _asset_kind(symbol: str) -> str:
    return "crypto" if _is_crypto_symbol(symbol) else "stock"


@dataclass
class WatchlistConfig:
    groups: Dict[str, List[str]] = field(default_factory=dict)
    favorites: List[str] = field(default_factory=list)
    benchmarks: Dict[str, List[str]] = field(default_factory=lambda: {"stocks": ["SPY", "QQQ"], "crypto": ["BTC/USD", "ETH/USD"]})

    def normalize(self) -> "WatchlistConfig":
        norm_groups: Dict[str, List[str]] = {}
        for group, tickers in (self.groups or {}).items():
            key = str(group).strip().lower()
            seen: Set[str] = set()
            out: List[str] = []
            for t in tickers or []:
                sym = _normalize_symbol(str(t))
                if sym and sym not in seen:
                    out.append(sym)
                    seen.add(sym)
            if out:
                norm_groups[key] = out
        fav_seen: Set[str] = set()
        favorites: List[str] = []
        for t in self.favorites or []:
            sym = _normalize_symbol(str(t))
            if sym and sym not in fav_seen:
                favorites.append(sym)
                fav_seen.add(sym)
        bench: Dict[str, List[str]] = {}
        for k, vals in (self.benchmarks or {}).items():
            b_seen: Set[str] = set()
            out: List[str] = []
            for t in vals or []:
                sym = _normalize_symbol(str(t))
                if sym and sym not in b_seen:
                    out.append(sym)
                    b_seen.add(sym)
            if out:
                bench[str(k).strip().lower()] = out
        self.groups = norm_groups
        self.favorites = favorites
        self.benchmarks = bench or {"stocks": ["SPY", "QQQ"], "crypto": ["BTC/USD", "ETH/USD"]}
        return self

    def all_group_tickers(self) -> List[str]:
        seen: Set[str] = set()
        out: List[str] = []
        for tickers in self.groups.values():
            for t in tickers:
                if t not in seen:
                    out.append(t)
                    seen.add(t)
        return out


class WatchlistStore:
    def __init__(self, path: Optional[Path] = None):
        default_path = Path(__file__).resolve().parent / "portfolio" / "data" / "watchlist.json"
        self.path = Path(path or default_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.save(WatchlistConfig().normalize())

    def load(self) -> WatchlistConfig:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if "groups" in raw or "favorites" in raw or "benchmarks" in raw:
                cfg = WatchlistConfig(
                    groups=raw.get("groups") or {},
                    favorites=raw.get("favorites") or [],
                    benchmarks=raw.get("benchmarks") or {},
                )
            else:
                # Backward compatible minimal format: {group:[tickers]}
                cfg = WatchlistConfig(groups=raw or {})
            return cfg.normalize()
        except Exception as exc:
            logger.warning("Failed to load watchlist file %s: %s", self.path, exc)
            cfg = WatchlistConfig().normalize()
            self.save(cfg)
            return cfg

    def save(self, config: WatchlistConfig) -> None:
        config = config.normalize()
        payload = {
            "groups": config.groups,
            "favorites": config.favorites,
            "benchmarks": config.benchmarks,
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def add_ticker(self, ticker: str, groups: Optional[Sequence[str]] = None, favorite: bool = False) -> Dict[str, Any]:
        cfg = self.load()
        sym = _normalize_symbol(ticker)
        if not sym:
            raise ValueError("ticker vacío")
        assigned_groups = [str(g).strip().lower() for g in (groups or []) if str(g).strip()]
        if not assigned_groups:
            assigned_groups = ["favorites"] if favorite else ["ungrouped"]
        for group in assigned_groups:
            current = cfg.groups.setdefault(group, [])
            if sym not in current:
                current.append(sym)
        if favorite and sym not in cfg.favorites:
            cfg.favorites.append(sym)
        self.save(cfg)
        return {"ticker": sym, "groups": assigned_groups, "favorite": sym in cfg.favorites}

    def add_favorite(self, ticker: str) -> Dict[str, Any]:
        return self.add_ticker(ticker, groups=["favorites"], favorite=True)

    def remove_group(self, group_name: str) -> Dict[str, Any]:
        cfg = self.load()
        group = str(group_name or "").strip().lower()
        if not group:
            raise ValueError("group_name vacío")
        existed = group in cfg.groups
        removed = cfg.groups.pop(group, [])
        self.save(cfg)
        return {"group": group, "removed_group": bool(existed), "tickers_removed_count": len(removed)}

    def remove_ticker(
        self,
        ticker: str,
        group_name: Optional[str] = None,
        from_favorites: bool = False,
    ) -> Dict[str, Any]:
        cfg = self.load()
        sym = _normalize_symbol(ticker)
        if not sym:
            raise ValueError("ticker vacío")

        removed_from_groups: List[str] = []
        if group_name:
            g = str(group_name).strip().lower()
            current = cfg.groups.get(g) or []
            if sym in current:
                cfg.groups[g] = [t for t in current if t != sym]
                if not cfg.groups[g]:
                    cfg.groups.pop(g, None)
                removed_from_groups.append(g)
        else:
            for g, current in list(cfg.groups.items()):
                if sym in current:
                    cfg.groups[g] = [t for t in current if t != sym]
                    if not cfg.groups[g]:
                        cfg.groups.pop(g, None)
                    removed_from_groups.append(g)

        removed_favorite = False
        if from_favorites or (group_name and str(group_name).strip().lower() == "favorites"):
            if sym in cfg.favorites:
                cfg.favorites = [t for t in cfg.favorites if t != sym]
                removed_favorite = True
        self.save(cfg)
        return {
            "ticker": sym,
            "removed_from_groups": removed_from_groups,
            "removed_from_favorites": removed_favorite,
        }

    def summary_text(self) -> str:
        cfg = self.load()
        lines = ["Watchlist groups:"]
        for group in sorted(cfg.groups.keys()):
            tickers = cfg.groups[group]
            lines.append(f"- {group}: {len(tickers)} ({', '.join(tickers[:12])}{'...' if len(tickers)>12 else ''})")
        if cfg.favorites:
            lines.append(f"Favorites ({len(cfg.favorites)}): {', '.join(cfg.favorites[:20])}{'...' if len(cfg.favorites)>20 else ''}")
        if cfg.benchmarks:
            b = []
            for k, vals in cfg.benchmarks.items():
                b.append(f"{k}={','.join(vals)}")
            lines.append("Benchmarks: " + " | ".join(b))
        return "\n".join(lines)


@dataclass
class TickerSnapshot:
    symbol: str
    asset_type: str
    current_price: Optional[float] = None
    prev_close: Optional[float] = None
    open_price: Optional[float] = None
    day_change_pct: Optional[float] = None
    week_change_pct: Optional[float] = None
    m1_change_pct: Optional[float] = None
    m3_change_pct: Optional[float] = None
    m6_change_pct: Optional[float] = None
    ytd_change_pct: Optional[float] = None
    volume_rel_20: Optional[float] = None
    open_vs_prev_close_pct: Optional[float] = None
    opened_positive: Optional[bool] = None
    speed_label: str = "normal"
    data_ok: bool = False


class PortfolioReviewService:
    def __init__(
        self,
        broker_config: Dict[str, Any],
        watchlist_store: Optional[WatchlistStore] = None,
        data_service: Optional[AlpacaDataService] = None,
    ):
        self.broker_config = dict(broker_config)
        self.watchlist_store = watchlist_store or WatchlistStore()
        self.data_service = data_service or AlpacaDataService()

    def _alpaca_api(self):
        broker_cfg = dict(self.broker_config)
        broker_cfg.setdefault("IS_PAPER", True)
        broker = Alpaca(broker_cfg)
        return broker.api

    def _fetch_positions(self) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
        api = self._alpaca_api()
        account = api.get_account()
        positions_raw = api.get_all_positions() or []
        by_symbol: Dict[str, Dict[str, Any]] = {}
        for p in positions_raw:
            sym = _normalize_symbol(getattr(p, "symbol", "") or "")
            if not sym:
                continue
            by_symbol[sym] = {
                "symbol": sym,
                "qty": _safe_float(getattr(p, "qty", 0)),
                "market_value": _safe_float(getattr(p, "market_value", 0)),
                "avg_entry_price": _safe_float(getattr(p, "avg_entry_price", 0)),
                "current_price": _safe_float(getattr(p, "current_price", 0)),
                "unrealized_pl": _safe_float(getattr(p, "unrealized_pl", 0)),
                "unrealized_plpc": _safe_float(getattr(p, "unrealized_plpc", 0)) * 100.0,
            }
        account_info = {
            "equity": _safe_float(getattr(account, "equity", 0)),
            "cash": _safe_float(getattr(account, "cash", 0)),
            "buying_power": _safe_float(getattr(account, "buying_power", 0)),
            "portfolio_value": _safe_float(getattr(account, "portfolio_value", 0)),
        }
        return by_symbol, account_info

    def _fetch_recent_sells(self, days: int = 30) -> Set[str]:
        api = self._alpaca_api()
        recent_sells: Set[str] = set()
        try:
            from alpaca.trading.enums import QueryOrderStatus
            from alpaca.trading.requests import GetOrdersRequest
            from datetime import timedelta, timezone

            after = datetime.now(timezone.utc) - timedelta(days=days)
            request = GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=after, direction="desc", limit=500)
            orders = api.get_orders(filter=request) or []
            for o in orders:
                status = str(getattr(o, "status", "")).lower()
                side = str(getattr(o, "side", "")).lower()
                if status == "filled" and side == "sell":
                    sym = _normalize_symbol(getattr(o, "symbol", "") or "")
                    if sym:
                        recent_sells.add(sym)
        except Exception as exc:
            logger.warning("Recent sells fetch unavailable: %s", exc)
        return recent_sells

    def _calc_period_change(self, closes, idx_from_end: int) -> Optional[float]:
        if closes is None or len(closes) <= idx_from_end:
            return None
        curr = _safe_float(closes.iloc[-1], 0.0)
        prev = _safe_float(closes.iloc[-1 - idx_from_end], 0.0)
        if prev == 0:
            return None
        return ((curr - prev) / prev) * 100.0

    def _calc_ytd_change(self, df) -> Optional[float]:
        if df is None or len(df) < 2:
            return None
        try:
            closes = df["close"]
            curr = _safe_float(closes.iloc[-1], 0.0)
            if curr == 0:
                return None
            now_ny = _now_ny()
            ystart = datetime(now_ny.year, 1, 1, tzinfo=now_ny.tzinfo)
            candidates = df[df.index >= ystart]
            if candidates.empty:
                first = _safe_float(closes.iloc[0], 0.0)
            else:
                first = _safe_float(candidates["close"].iloc[0], 0.0)
            if first == 0:
                return None
            return ((curr - first) / first) * 100.0
        except Exception:
            return None

    def _ticker_snapshot(self, symbol: str, lookback_days: int = 400) -> TickerSnapshot:
        snap = TickerSnapshot(symbol=symbol, asset_type=_asset_kind(symbol))
        if pd is None:
            return snap
        try:
            bars = self.data_service.get_stock_bars(symbol, days=lookback_days)
            if bars is None or bars.empty:
                return snap
            df = bars.sort_index().copy()
            closes = df["close"]
            current_price = self.data_service.get_latest_price(symbol)
            if current_price is None:
                current_price = _safe_float(closes.iloc[-1], 0.0)
            if current_price == 0:
                return snap

            snap.current_price = float(current_price)
            snap.prev_close = _safe_float(closes.iloc[-2], 0.0) if len(df) >= 2 else None
            snap.open_price = _safe_float(df["open"].iloc[-1], 0.0) if "open" in df.columns else None
            if snap.prev_close and snap.prev_close != 0:
                snap.day_change_pct = ((snap.current_price - snap.prev_close) / snap.prev_close) * 100.0
                if snap.open_price is not None:
                    snap.open_vs_prev_close_pct = ((snap.open_price - snap.prev_close) / snap.prev_close) * 100.0
                    snap.opened_positive = snap.open_vs_prev_close_pct >= 0
            snap.week_change_pct = self._calc_period_change(closes, 5)
            snap.m1_change_pct = self._calc_period_change(closes, 21)
            snap.m3_change_pct = self._calc_period_change(closes, 63)
            snap.m6_change_pct = self._calc_period_change(closes, 126)
            snap.ytd_change_pct = self._calc_ytd_change(df)

            if "volume" in df.columns and len(df) >= 20:
                avg20 = _safe_float(df["volume"].iloc[-20:].mean(), 0.0)
                if avg20 > 0:
                    snap.volume_rel_20 = _safe_float(df["volume"].iloc[-1], 0.0) / avg20

            if snap.day_change_pct is not None and abs(snap.day_change_pct) >= 5.0:
                snap.speed_label = "rapido"
            else:
                snap.speed_label = "normal"
            snap.data_ok = True
            return snap
        except Exception as exc:
            logger.warning("Ticker snapshot failed for %s: %s", symbol, exc)
            return snap

    def _build_universe(self, include_benchmark: bool = True) -> Dict[str, Any]:
        cfg = self.watchlist_store.load()
        positions, account = self._fetch_positions()
        portfolio_symbols = list(positions.keys())
        group_tickers = cfg.all_group_tickers()
        favorite_tickers = list(cfg.favorites)
        benchmarks: List[str] = []
        if include_benchmark:
            for vals in (cfg.benchmarks or {}).values():
                benchmarks.extend(vals or [])
        universe: List[str] = []
        seen: Set[str] = set()
        for s in portfolio_symbols + favorite_tickers + group_tickers + benchmarks:
            sym = _normalize_symbol(s)
            if sym and sym not in seen:
                universe.append(sym)
                seen.add(sym)
        return {
            "config": cfg,
            "positions": positions,
            "account": account,
            "universe": universe,
        }

    def _collect_snapshots(self, symbols: Sequence[str]) -> Dict[str, TickerSnapshot]:
        snapshots: Dict[str, TickerSnapshot] = {}
        for sym in symbols:
            snapshots[sym] = self._ticker_snapshot(sym)
        return snapshots

    def _format_pct(self, value: Optional[float]) -> str:
        if value is None:
            return "N/D"
        sign = "+" if value >= 0 else ""
        return f"{sign}{value:.2f}%"

    def _format_money(self, value: Optional[float]) -> str:
        if value is None:
            return "N/D"
        sign = "+" if value >= 0 else ""
        return f"{sign}${value:,.2f}"

    def _build_group_exposure(self, positions: Dict[str, Dict[str, Any]], cfg: WatchlistConfig) -> List[Tuple[str, float]]:
        exposure: Dict[str, float] = {}
        for group, tickers in cfg.groups.items():
            total = 0.0
            for t in tickers:
                pos = positions.get(t)
                if pos:
                    total += _safe_float(pos.get("market_value"), 0.0)
            if total > 0:
                exposure[group] = total
        return sorted(exposure.items(), key=lambda kv: kv[1], reverse=True)

    def _build_benchmarks_section(self, cfg: WatchlistConfig, snaps: Dict[str, TickerSnapshot]) -> List[str]:
        lines: List[str] = []
        bench = cfg.benchmarks or {}
        if not bench:
            return lines
        lines.append("Benchmark (opcional):")
        for kind in ("stocks", "crypto"):
            tickers = bench.get(kind) or []
            if not tickers:
                continue
            parts = []
            for t in tickers:
                s = snaps.get(t)
                if not s or not s.data_ok:
                    continue
                parts.append(f"{t} {self._format_pct(s.day_change_pct)}")
            if parts:
                lines.append(f"- {kind}: " + " | ".join(parts))
        return lines

    def _suggest_alerts(self, candidates: List[TickerSnapshot], positions: Dict[str, Dict[str, Any]]) -> List[str]:
        suggestions: List[str] = []
        for s in candidates[:4]:
            if s.current_price is None:
                continue
            if s.symbol in positions:
                price = s.current_price
                suggestions.append(f"{s.symbol}: alerta de caída 2% desde ~{price:.2f} para proteger ganancia")
            else:
                price = s.current_price
                suggestions.append(f"{s.symbol}: alerta de ruptura +2% o pullback -3% desde ~{price:.2f}")
        return suggestions

    def _weekly_fundamentals_lines(self, cfg: WatchlistConfig, positions: Dict[str, Dict[str, Any]]) -> List[str]:
        # Optional integration hook: intentionally lightweight/fail-soft for v1.
        # We do not force TradingAgents dependency here.
        focus = list(positions.keys())
        for t in cfg.favorites:
            if t not in focus:
                focus.append(t)
        focus = [t for t in focus if _asset_kind(t) == "stock"][:6]
        if not focus:
            return ["Fundamentals: sin tickers stock para revisar."]
        lines = ["Fundamentals (weekly, v1):"]
        lines.append("- Fuente externa no configurada en este runtime (TradingAgents/provider).")
        lines.append("- Tickers objetivo para fundamentals: " + ", ".join(focus))
        return lines

    def _weekly_earnings_lines(self, cfg: WatchlistConfig) -> List[str]:
        focus = [t for t in cfg.favorites if _asset_kind(t) == "stock"][:10]
        if not focus:
            focus = [t for t in cfg.all_group_tickers() if _asset_kind(t) == "stock"][:10]
        lines = ["Earnings calendar (weekly):"]
        lines.append("- Fuente de earnings no configurada aún en este runtime.")
        if focus:
            lines.append("- Revisar earnings para: " + ", ".join(focus))
        return lines

    def generate_report_text(
        self,
        report_kind: str,
        include_benchmark: bool = True,
        group_name: Optional[str] = None,
    ) -> str:
        kind = (report_kind or "").strip().lower()
        if kind not in {"pre_open", "midday", "close", "weekly"}:
            raise ValueError("report_kind must be one of: pre_open, midday, close, weekly")

        ny_now = _now_ny()
        base = self._build_universe(include_benchmark=include_benchmark)
        cfg: WatchlistConfig = base["config"]
        positions: Dict[str, Dict[str, Any]] = base["positions"]
        account = base["account"]
        universe: List[str] = base["universe"]
        normalized_group_name: Optional[str] = None
        group_filtered_symbols: Optional[Set[str]] = None
        if group_name:
            normalized_group_name = str(group_name).strip().lower()
            group_tickers = cfg.groups.get(normalized_group_name)
            if not group_tickers:
                available = ", ".join(sorted(cfg.groups.keys())) or "sin grupos"
                raise ValueError(f"Grupo '{normalized_group_name}' no existe. Grupos disponibles: {available}")
            group_filtered_symbols = set(group_tickers)
            # Strict group filter: only tickers from requested group.
            universe = [s for s in universe if s in group_filtered_symbols]
            include_benchmark = False
        recent_sells = self._fetch_recent_sells(days=30)
        snaps = self._collect_snapshots(universe)

        valid_snaps = [s for s in snaps.values() if s.data_ok]
        portfolio_snaps = [snaps[s] for s in positions.keys() if s in snaps and snaps[s].data_ok]
        watch_only_snaps = [s for s in valid_snaps if s.symbol not in positions]
        favorites_set = set(cfg.favorites)

        top_movers = sorted(valid_snaps, key=lambda s: abs(s.day_change_pct or 0.0), reverse=True)[:8]
        rapid_moves = [s for s in valid_snaps if (s.day_change_pct is not None and abs(s.day_change_pct) >= 5.0)]
        rapid_moves = sorted(rapid_moves, key=lambda s: abs(s.day_change_pct or 0.0), reverse=True)[:10]

        missed = [
            s for s in watch_only_snaps
            if s.symbol in favorites_set and (s.day_change_pct or 0.0) >= 5.0
        ]
        missed = sorted(missed, key=lambda s: (s.day_change_pct or 0.0), reverse=True)[:8]

        reentries = [
            s for s in watch_only_snaps
            if s.symbol in recent_sells and s.day_change_pct is not None and s.day_change_pct > 0
        ]
        reentries = sorted(reentries, key=lambda s: (s.week_change_pct or 0.0), reverse=True)[:6]

        new_entries = [
            s for s in watch_only_snaps
            if s.symbol not in recent_sells and s.symbol in favorites_set and (s.week_change_pct or 0.0) > 0 and abs(s.day_change_pct or 0.0) < 5
        ]
        new_entries = sorted(new_entries, key=lambda s: (s.week_change_pct or 0.0), reverse=True)[:6]

        noise = [
            s for s in watch_only_snaps
            if s.day_change_pct is not None and abs(s.day_change_pct) >= 5.0 and abs(s.week_change_pct or 0.0) < 2.0
        ]
        noise = sorted(noise, key=lambda s: abs(s.day_change_pct or 0.0), reverse=True)[:6]

        lines: List[str] = []
        title_map = {
            "pre_open": "Reporte Pre-Apertura",
            "midday": "Reporte Medio Dia",
            "close": "Reporte Cierre",
            "weekly": "Reporte Semanal",
        }
        if normalized_group_name:
            lines.append(f"{title_map[kind]} - grupo {normalized_group_name} ({ny_now.strftime('%Y-%m-%d %H:%M %Z')})")
        else:
            lines.append(f"{title_map[kind]} ({ny_now.strftime('%Y-%m-%d %H:%M %Z')})")
        lines.append("")
        lines.append("Resumen ejecutivo:")
        lines.append(
            f"- Portfolio value: {self._format_money(account.get('portfolio_value'))} | Cash: {self._format_money(account.get('cash'))} | Buying power: {self._format_money(account.get('buying_power'))}"
        )
        if normalized_group_name:
            group_positions_count = sum(1 for s in (group_filtered_symbols or set()) if s in positions)
            lines.append(f"- Posiciones abiertas (totales): {len(positions)} | Posiciones en grupo: {group_positions_count} | Universe monitoreado: {len(universe)} tickers")
        else:
            lines.append(f"- Posiciones abiertas: {len(positions)} | Universe monitoreado: {len(universe)} tickers")
        if normalized_group_name:
            lines.append(f"- Filtro de grupo activo: {normalized_group_name} ({len(cfg.groups.get(normalized_group_name, []))} tickers)")
        if portfolio_snaps:
            port_day_moves = [s.day_change_pct for s in portfolio_snaps if s.day_change_pct is not None]
            if port_day_moves:
                avg_port_day = sum(port_day_moves) / len(port_day_moves)
                lines.append(f"- Ritmo portfolio hoy (promedio %): {self._format_pct(avg_port_day)}")
        lines.append(f"- Movimientos rapidos >=5% detectados: {len(rapid_moves)}")
        lines.append(f"- Oportunidades perdidas (watchlist sin posicion, +5%): {len(missed)}")

        bench_lines = self._build_benchmarks_section(cfg, snaps) if include_benchmark else []
        if bench_lines:
            lines.append("")
            lines.extend(bench_lines)

        lines.append("")
        lines.append("Top movimientos:")
        if not top_movers:
            lines.append("- Sin datos")
        else:
            for s in top_movers:
                open_flag = "abrió+" if s.opened_positive else "abrió-" if s.opened_positive is not None else "apertura N/D"
                pos_tag = "posicion" if s.symbol in positions else "watchlist"
                lines.append(f"- {s.symbol} ({pos_tag}) {self._format_pct(s.day_change_pct)} | {open_flag} | ritmo={s.speed_label}")

        lines.append("")
        lines.append("Movimientos rapidos (>=5%):")
        if not rapid_moves:
            lines.append("- Ninguno")
        else:
            for s in rapid_moves[:8]:
                vr = f" | vol {s.volume_rel_20:.1f}x" if s.volume_rel_20 is not None else ""
                lines.append(f"- {s.symbol}: {self._format_pct(s.day_change_pct)} ({'sin posicion' if s.symbol not in positions else 'en portfolio'}){vr}")

        lines.append("")
        lines.append("Oportunidades perdidas (watchlist sin posicion):")
        if not missed:
            lines.append("- Ninguna >5% hoy en favoritos")
        else:
            for s in missed:
                lines.append(f"- {s.symbol}: {self._format_pct(s.day_change_pct)} hoy | 1W {self._format_pct(s.week_change_pct)}")

        lines.append("")
        lines.append("Nuevas entradas potenciales vs re-entries:")
        if reentries:
            lines.append("- Re-entries:")
            for s in reentries[:4]:
                lines.append(f"  - {s.symbol}: 1W {self._format_pct(s.week_change_pct)} | hoy {self._format_pct(s.day_change_pct)}")
        else:
            lines.append("- Re-entries: ninguno claro")
        if new_entries:
            lines.append("- Nuevas entradas potenciales:")
            for s in new_entries[:4]:
                lines.append(f"  - {s.symbol}: 1W {self._format_pct(s.week_change_pct)} | hoy {self._format_pct(s.day_change_pct)}")
        else:
            lines.append("- Nuevas entradas potenciales: ninguna clara")

        lines.append("")
        lines.append("Ruido (volatil pero sin señal util clara):")
        if not noise:
            lines.append("- Ninguno")
        else:
            for s in noise:
                lines.append(f"- {s.symbol}: hoy {self._format_pct(s.day_change_pct)} | 1W {self._format_pct(s.week_change_pct)}")

        exposure = self._build_group_exposure(positions, cfg)
        lines.append("")
        lines.append("Exposicion por grupo:")
        if normalized_group_name:
            mv = 0.0
            for t in (cfg.groups.get(normalized_group_name) or []):
                pos = positions.get(t)
                if pos:
                    mv += _safe_float(pos.get("market_value"), 0.0)
            lines.append(f"- {normalized_group_name}: {self._format_money(mv) if mv else '$0.00'}")
        elif not exposure:
            lines.append("- Sin posiciones mapeadas a grupos del watchlist")
        else:
            for group, mv in exposure[:8]:
                lines.append(f"- {group}: {self._format_money(mv)}")
        lines.append("- Sector (stocks): pendiente de proveedor fundamentals/sector")

        if kind == "weekly":
            lines.append("")
            lines.append("Rendimiento semanal y periodos (favoritos/portfolio destacados):")
            weekly_focus = [s for s in valid_snaps if s.symbol in favorites_set or s.symbol in positions][:12]
            weekly_focus = sorted(weekly_focus, key=lambda s: abs(s.week_change_pct or 0.0), reverse=True)
            if not weekly_focus:
                lines.append("- Sin datos")
            else:
                for s in weekly_focus[:10]:
                    lines.append(
                        f"- {s.symbol}: 1W {self._format_pct(s.week_change_pct)} | 1M {self._format_pct(s.m1_change_pct)} | 3M {self._format_pct(s.m3_change_pct)} | 6M {self._format_pct(s.m6_change_pct)} | YTD {self._format_pct(s.ytd_change_pct)}"
                    )
            lines.append("")
            lines.extend(self._weekly_fundamentals_lines(cfg, positions))
            lines.append("")
            lines.extend(self._weekly_earnings_lines(cfg))

        suggestions = self._suggest_alerts(missed or rapid_moves or top_movers, positions)
        lines.append("")
        lines.append("Alertas sugeridas (no se crean automatico):")
        if not suggestions:
            lines.append("- Sin sugerencias")
        else:
            for s in suggestions:
                lines.append(f"- {s}")

        lines.append("")
        lines.append("Nota: reporte puntual para monitoreo manual. Si quieres detalle de un ticker, pídelo por chat.")
        return "\n".join(lines)


class PortfolioReviewScheduler:
    def __init__(
        self,
        review_service: PortfolioReviewService,
        send_callback: Callable[[int, str], None],
        chat_ids: Optional[Sequence[int]] = None,
    ):
        self.review_service = review_service
        self.send_callback = send_callback
        self.chat_ids: List[int] = [int(c) for c in (chat_ids or _parse_chat_ids_from_env())]
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="portfolio-review")
        self._running_jobs: Set[str] = set()
        self._lock = threading.Lock()
        self._last_fire: Set[str] = set()

    def start_in_thread(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, name="portfolio-review-scheduler", daemon=True)
        self._thread.start()
        logger.info("PortfolioReviewScheduler started (chat_ids=%s)", self.chat_ids)

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _slot_key(self, now: datetime, report_kind: str) -> str:
        if report_kind == "weekly":
            return f"{now.strftime('%Y-W%W')}-weekly"
        return f"{now.strftime('%Y-%m-%d')}-{report_kind}"

    def _run_loop(self) -> None:
        schedule_map = {
            ("08:30", None): "pre_open",
            ("12:00", None): "midday",
            ("16:10", None): "close",
            ("16:30", 4): "weekly",  # Friday
        }
        while not self._stop.is_set():
            try:
                now = _now_ny()
                hhmm = now.strftime("%H:%M")
                weekday = now.weekday()
                for (time_key, weekday_filter), report_kind in schedule_map.items():
                    if hhmm != time_key:
                        continue
                    if weekday_filter is not None and weekday != weekday_filter:
                        continue
                    if report_kind != "weekly" and weekday >= 5:
                        continue
                    dedupe = self._slot_key(now, report_kind)
                    with self._lock:
                        if dedupe in self._last_fire:
                            continue
                        self._last_fire.add(dedupe)
                    self.trigger_async(report_kind, source="cron")
                time.sleep(20)
            except Exception as exc:
                logger.exception("PortfolioReviewScheduler loop error: %s", exc)
                time.sleep(10)

    def trigger_async(self, report_kind: str, chat_id: Optional[int] = None, source: str = "manual") -> bool:
        return self.trigger_async_with_group(report_kind, chat_id=chat_id, source=source, group_name=None)

    def trigger_async_with_group(
        self,
        report_kind: str,
        chat_id: Optional[int] = None,
        source: str = "manual",
        group_name: Optional[str] = None,
    ) -> bool:
        kind = (report_kind or "").strip().lower()
        if kind in {"daily", "day"}:
            kind = "close"
        if kind not in {"pre_open", "midday", "close", "weekly"}:
            raise ValueError("Invalid report kind")
        gk = (group_name or "").strip().lower() or "all"
        job_key = f"{kind}:{gk}:{chat_id or 'broadcast'}"
        with self._lock:
            if job_key in self._running_jobs:
                return False
            self._running_jobs.add(job_key)
        self._executor.submit(self._run_job, job_key, kind, chat_id, source, (group_name or None))
        return True

    def _run_job(self, job_key: str, report_kind: str, chat_id: Optional[int], source: str, group_name: Optional[str] = None) -> None:
        try:
            text = self.review_service.generate_report_text(report_kind, include_benchmark=True, group_name=group_name)
            prefix = f"[{source}] " if source else ""
            final_text = prefix + text
            target_ids = [int(chat_id)] if chat_id is not None else list(self.chat_ids)
            if not target_ids:
                logger.warning("Portfolio report generated but no Telegram chat_ids configured")
                return
            for cid in target_ids:
                try:
                    self.send_callback(cid, final_text)
                except Exception as exc:
                    logger.exception("Failed to send portfolio report to chat_id=%s: %s", cid, exc)
        except Exception as exc:
            logger.exception("Portfolio report job failed (%s, group=%s): %s", report_kind, group_name, exc)
            if chat_id is not None:
                try:
                    extra = f" del grupo {group_name}" if group_name else ""
                    self.send_callback(int(chat_id), f"No se pudo generar el reporte {report_kind}{extra}: {exc}")
                except Exception:
                    pass
        finally:
            with self._lock:
                self._running_jobs.discard(job_key)
