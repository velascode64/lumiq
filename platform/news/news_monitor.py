"""
Watchlist news monitor (pre-open Telegram digest).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set
from zoneinfo import ZoneInfo

from alpaca.data.historical import NewsClient
from alpaca.data.requests import NewsRequest

try:
    from ..portfolio.review import NYSE_TZ, WatchlistStore, _parse_chat_ids_from_env, _normalize_symbol
except ImportError:
    from platform.portfolio.review import NYSE_TZ, WatchlistStore, _parse_chat_ids_from_env, _normalize_symbol

logger = logging.getLogger(__name__)


def _now_ny() -> datetime:
    return datetime.now(ZoneInfo(NYSE_TZ))


def _as_news_items(news_result: Any) -> List[Any]:
    if news_result is None:
        return []
    for attr in ("news", "articles", "data"):
        value = getattr(news_result, attr, None)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for key in ("news", "articles"):
                if isinstance(value.get(key), list):
                    return value[key]
    if isinstance(news_result, dict):
        for key in ("news", "articles"):
            if isinstance(news_result.get(key), list):
                return news_result[key]
    try:
        dumped = news_result.model_dump()  # pydantic
        if isinstance(dumped, dict):
            for key in ("news", "articles"):
                if isinstance(dumped.get(key), list):
                    return dumped[key]
    except Exception:
        pass
    return []


def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


@dataclass
class NewsHit:
    symbol: str
    headline: str
    source: str
    created_at: Optional[datetime]
    summary: str = ""
    url: Optional[str] = None
    impact_score: int = 0
    impact_reasons: List[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.impact_reasons is None:
            self.impact_reasons = []


class WatchlistNewsMonitorService:
    HIGH_IMPACT_KEYWORDS = {
        "earnings": 5,
        "guidance": 5,
        "downgrade": 4,
        "upgrade": 4,
        "sec": 4,
        "lawsuit": 4,
        "investigation": 4,
        "merger": 5,
        "acquisition": 5,
        "buyout": 5,
        "bankruptcy": 6,
        "offering": 4,
        "fda": 5,
        "recall": 4,
        "contract": 3,
        "partnership": 3,
        "guides": 2,
        "layoffs": 4,
    }

    def __init__(
        self,
        watchlist_store: Optional[WatchlistStore] = None,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
    ):
        self.watchlist_store = watchlist_store or WatchlistStore()
        api_key = api_key or os.getenv("ALPACA_API_KEY", "")
        secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY", "") or os.getenv("ALPACA_API_SECRET", "")
        if not api_key or not secret_key:
            raise ValueError("Alpaca credentials required for news monitor")
        self.client = NewsClient(api_key=api_key, secret_key=secret_key)

    def _watchlist_symbols(self, group_name: Optional[str] = None) -> List[str]:
        cfg = self.watchlist_store.load()
        if group_name:
            tickers = cfg.groups.get(str(group_name).strip().lower()) or []
            return [t for t in tickers if "/" not in t]  # Alpaca news is equities-focused
        seen: Set[str] = set()
        out: List[str] = []
        for s in cfg.favorites + cfg.all_group_tickers():
            s = _normalize_symbol(s)
            if not s or "/" in s:
                continue
            if s not in seen:
                out.append(s)
                seen.add(s)
        return out

    def _score_news(self, headline: str, summary: str, created_at: Optional[datetime]) -> tuple[int, List[str]]:
        score = 0
        reasons: List[str] = []
        text = f"{headline} {summary}".lower()
        for word, pts in self.HIGH_IMPACT_KEYWORDS.items():
            if word in text:
                score += pts
                reasons.append(word)
        if created_at is not None:
            now = datetime.now(timezone.utc)
            age_h = (now - created_at.astimezone(timezone.utc)).total_seconds() / 3600.0
            if age_h <= 4:
                score += 2
                reasons.append("muy_reciente")
            elif age_h <= 12:
                score += 1
                reasons.append("reciente")
        return score, reasons

    def fetch_watchlist_news_hits(
        self,
        group_name: Optional[str] = None,
        lookback_hours: int = 18,
        limit: int = 50,
    ) -> List[NewsHit]:
        symbols = self._watchlist_symbols(group_name=group_name)
        if not symbols:
            return []
        req = NewsRequest(
            symbols=",".join(symbols[:50]),
            start=datetime.now(timezone.utc) - timedelta(hours=max(1, lookback_hours)),
            end=datetime.now(timezone.utc),
            limit=max(1, min(int(limit), 200)),
            sort="desc",
        )
        result = self.client.get_news(req)
        raw_items = _as_news_items(result)
        hits: List[NewsHit] = []
        for item in raw_items:
            item_symbols = _safe_get(item, "symbols", []) or []
            if isinstance(item_symbols, str):
                item_symbols = [item_symbols]
            headline = str(_safe_get(item, "headline", "") or "").strip()
            summary = str(_safe_get(item, "summary", "") or "").strip()
            source = str(_safe_get(item, "source", "") or "")
            url = _safe_get(item, "url")
            created = _safe_get(item, "created_at")
            if not headline:
                continue
            if item_symbols:
                mapped_symbols = [s for s in item_symbols if s in symbols]
            else:
                mapped_symbols = []
            if not mapped_symbols:
                # If no explicit symbol in item, skip for watchlist mode
                continue
            score, reasons = self._score_news(headline, summary, created)
            for sym in mapped_symbols:
                hits.append(
                    NewsHit(
                        symbol=sym,
                        headline=headline,
                        source=source,
                        created_at=created,
                        summary=summary,
                        url=url,
                        impact_score=score,
                        impact_reasons=reasons[:],
                    )
                )
        hits.sort(key=lambda h: (h.impact_score, h.created_at or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
        return hits

    def generate_preopen_digest_text(
        self,
        group_name: Optional[str] = None,
        min_impact_score: int = 2,
        limit_symbols: int = 8,
    ) -> str:
        ny_now = _now_ny()
        hits = self.fetch_watchlist_news_hits(group_name=group_name, lookback_hours=18, limit=80)
        filtered = [h for h in hits if h.impact_score >= min_impact_score]
        title = "Noticias Pre-Apertura Watchlist"
        if group_name:
            title += f" - grupo {str(group_name).strip().lower()}"
        lines = [f"{title} ({ny_now.strftime('%Y-%m-%d %H:%M %Z')})", ""]
        if not hits:
            lines.append("Sin noticias encontradas para el watchlist en la ventana reciente.")
            return "\n".join(lines)

        by_symbol: Dict[str, List[NewsHit]] = {}
        for h in filtered or hits[:12]:
            by_symbol.setdefault(h.symbol, []).append(h)

        lines.append(f"Resumen: {len(hits)} noticias detectadas | {len(filtered)} con impacto>={min_impact_score}")
        lines.append("")
        lines.append("Tickers con noticias relevantes:")
        if not by_symbol:
            lines.append("- No hay noticias con impacto relevante (solo ruido/menor prioridad).")
        else:
            ranked_symbols = sorted(
                by_symbol.keys(),
                key=lambda s: max(x.impact_score for x in by_symbol[s]),
                reverse=True,
            )[:limit_symbols]
            for sym in ranked_symbols:
                top = by_symbol[sym][0]
                ts = top.created_at.astimezone(ZoneInfo(NYSE_TZ)).strftime("%H:%M") if top.created_at else "N/D"
                reasons = ",".join(top.impact_reasons[:3]) if top.impact_reasons else "headline"
                lines.append(f"- {sym}: score={top.impact_score} | {top.source} {ts} | {top.headline} [{reasons}]")

        lines.append("")
        lines.append("Noticias top (headlines):")
        top_hits = (filtered if filtered else hits)[:10]
        for h in top_hits:
            ts = h.created_at.astimezone(ZoneInfo(NYSE_TZ)).strftime("%H:%M") if h.created_at else "N/D"
            link = f" | {h.url}" if h.url else ""
            lines.append(f"- {h.symbol} | {h.source} {ts} | {h.headline}{link}")

        lines.append("")
        lines.append("Conclusion:")
        if filtered:
            lines.append(f"- Hay {len(filtered)} noticias con impacto relevante; prioriza los tickers con mayor score en pre-open.")
            top_syms = []
            seen: Set[str] = set()
            for h in filtered:
                if h.symbol not in seen:
                    top_syms.append(h.symbol)
                    seen.add(h.symbol)
                if len(top_syms) >= 3:
                    break
            if top_syms:
                lines.append(f"- Revisar primero: {', '.join(top_syms)}.")
        else:
            lines.append("- No se detectan catalizadores fuertes; probable apertura sin noticias dominantes en watchlist.")
        lines.append("Uso sugerido: revisar manualmente tickers con score alto antes de abrir posiciones nuevas o re-entries.")
        return "\n".join(lines)

    def export_news_payload(
        self,
        group_name: Optional[str] = None,
        lookback_hours: int = 18,
        limit: int = 80,
        min_impact_score: int = 0,
    ) -> Dict[str, Any]:
        hits = self.fetch_watchlist_news_hits(group_name=group_name, lookback_hours=lookback_hours, limit=limit)
        filtered = [h for h in hits if h.impact_score >= int(min_impact_score)]
        cfg = self.watchlist_store.load()
        symbols = self._watchlist_symbols(group_name=group_name)
        return {
            "as_of": _now_ny().isoformat(),
            "timezone": NYSE_TZ,
            "scope": {
                "group_name": str(group_name).strip().lower() if group_name else None,
                "watchlist_symbols_count": len(symbols),
                "favorites_count": len(cfg.favorites),
            },
            "totals": {
                "hits_count": len(hits),
                "filtered_hits_count": len(filtered),
                "min_impact_score": int(min_impact_score),
            },
            "hits": [
                {
                    "symbol": h.symbol,
                    "headline": h.headline,
                    "source": h.source,
                    "created_at": h.created_at.isoformat() if h.created_at else None,
                    "summary": h.summary,
                    "url": h.url,
                    "impact_score": h.impact_score,
                    "impact_reasons": list(h.impact_reasons or []),
                    "is_favorite": h.symbol in set(cfg.favorites),
                }
                for h in hits
            ],
        }


class WatchlistNewsScheduler:
    def __init__(
        self,
        service: WatchlistNewsMonitorService,
        send_callback: Callable[[int, str], None],
        chat_ids: Optional[Sequence[int]] = None,
        analyze_callback: Optional[Callable[[Optional[str]], str]] = None,
        persist_callback: Optional[Callable[..., None]] = None,
    ):
        self.service = service
        self.send_callback = send_callback
        self.analyze_callback = analyze_callback
        self.persist_callback = persist_callback
        self.chat_ids: List[int] = [int(c) for c in (chat_ids or _parse_chat_ids_from_env())]
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="watchlist-news")
        self._running = False
        self._last_preopen_key: Optional[str] = None

    def start_in_thread(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, name="watchlist-news-scheduler", daemon=True)
        self._thread.start()
        logger.info("WatchlistNewsScheduler started (chat_ids=%s)", self.chat_ids)

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                now = _now_ny()
                if now.weekday() < 5 and now.strftime("%H:%M") == "08:30":
                    key = now.strftime("%Y-%m-%d-preopen-news")
                    if self._last_preopen_key != key:
                        self._last_preopen_key = key
                        self.trigger_async(source="cron")
                time.sleep(20)
            except Exception as exc:
                logger.exception("WatchlistNewsScheduler loop error: %s", exc)
                time.sleep(10)

    def trigger_async(self, chat_id: Optional[int] = None, source: str = "manual", group_name: Optional[str] = None) -> bool:
        if self._running:
            return False
        self._running = True
        self._executor.submit(self._run_job, chat_id, source, group_name)
        return True

    def _run_job(self, chat_id: Optional[int], source: str, group_name: Optional[str]) -> None:
        try:
            if self.analyze_callback is not None:
                try:
                    text = self.analyze_callback(group_name)
                except Exception:
                    logger.exception("News analyze callback failed; falling back to deterministic digest")
                    text = self.service.generate_preopen_digest_text(group_name=group_name)
            else:
                text = self.service.generate_preopen_digest_text(group_name=group_name)
            final = (f"[{source}] " if source else "") + text
            if self.persist_callback is not None:
                try:
                    self.persist_callback(text=final, source=source, group_name=group_name, chat_id=chat_id)
                except Exception as exc:
                    logger.exception("Failed to persist news digest: %s", exc)
            target_ids = [int(chat_id)] if chat_id is not None else list(self.chat_ids)
            for cid in target_ids:
                self.send_callback(cid, final)
        except Exception as exc:
            logger.exception("Watchlist news job failed: %s", exc)
            if chat_id is not None:
                try:
                    self.send_callback(int(chat_id), f"No se pudo generar el digest de noticias: {exc}")
                except Exception:
                    pass
        finally:
            self._running = False
