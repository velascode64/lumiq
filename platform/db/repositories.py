from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from .core import (
    SQLALCHEMY_AVAILABLE,
    DatabaseManager,
    sa,
    watchlist_state,
    alerts_state,
    agent_messages,
    tasks,
    task_runs,
    artifacts,
    reports,
    observations,
    memory_semantic,
    memory_episodic,
    memory_procedural,
    chat_sessions,
    chat_turns,
)


logger = logging.getLogger(__name__)


def _uuid() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value in (None, ""):
        return {}
    try:
        if isinstance(value, str):
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
    except Exception:
        pass
    return {"value": value}


class DbWatchlistRepository:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def _default_payload(self) -> Dict[str, Any]:
        return {
            "groups": {},
            "favorites": [],
            "benchmarks": {"stocks": ["SPY", "QQQ"], "crypto": ["BTC/USD", "ETH/USD"]},
            "updated_at": _now_iso(),
            "schema_version": 1,
        }

    def _read_payload(self) -> Dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(sa.select(watchlist_state.c.payload).where(watchlist_state.c.id == 1)).scalar_one_or_none()
        payload = _safe_json(row)
        if not payload:
            payload = self._default_payload()
        payload.setdefault("groups", {})
        payload.setdefault("favorites", [])
        payload.setdefault("benchmarks", {"stocks": ["SPY", "QQQ"], "crypto": ["BTC/USD", "ETH/USD"]})
        payload.setdefault("schema_version", 1)
        return payload

    def _write_payload(self, payload: Dict[str, Any]) -> None:
        to_save = dict(payload or {})
        to_save["updated_at"] = _now_iso()
        to_save.setdefault("schema_version", 1)
        with self.db.begin() as conn:
            exists = conn.execute(sa.select(watchlist_state.c.id).where(watchlist_state.c.id == 1)).scalar_one_or_none()
            if exists is None:
                conn.execute(sa.insert(watchlist_state).values(id=1, payload=to_save, updated_at=sa.func.now()))
            else:
                conn.execute(
                    sa.update(watchlist_state)
                    .where(watchlist_state.c.id == 1)
                    .values(payload=to_save, updated_at=sa.func.now())
                )

    def load_config_dict(self) -> Dict[str, Any]:
        payload = self._read_payload()
        return {
            "groups": payload.get("groups") or {},
            "favorites": payload.get("favorites") or [],
            "benchmarks": payload.get("benchmarks") or {"stocks": ["SPY", "QQQ"], "crypto": ["BTC/USD", "ETH/USD"]},
        }

    def save_config_dict(self, payload: Dict[str, Any]) -> None:
        base = self._read_payload()
        base["groups"] = payload.get("groups") or {}
        base["favorites"] = payload.get("favorites") or []
        base["benchmarks"] = payload.get("benchmarks") or {}
        self._write_payload(base)

    def upsert_ticker(self, ticker: str, groups: Iterable[str], favorite: bool = False) -> Dict[str, Any]:
        payload = self._read_payload()
        all_groups: Dict[str, List[str]] = payload.get("groups") or {}
        favorites: List[str] = list(payload.get("favorites") or [])
        assigned: List[str] = []
        for g in groups:
            gname = str(g).strip().lower()
            if not gname:
                continue
            bucket = list(all_groups.get(gname) or [])
            if ticker not in bucket:
                bucket.append(ticker)
            all_groups[gname] = bucket
            assigned.append(gname)
        if favorite and ticker not in favorites:
            favorites.append(ticker)
        if "favorites" in assigned and ticker not in favorites:
            favorites.append(ticker)
        payload["groups"] = all_groups
        payload["favorites"] = favorites
        self._write_payload(payload)
        return {"ticker": ticker, "groups": assigned, "favorite": favorite or ("favorites" in assigned)}

    def remove_group(self, group_name: str) -> Dict[str, Any]:
        gname = str(group_name).strip().lower()
        payload = self._read_payload()
        groups = payload.get("groups") or {}
        existed = gname in groups
        removed = list(groups.pop(gname, [])) if existed else []
        payload["groups"] = groups
        self._write_payload(payload)
        removed_count = len(removed)
        return {"group": gname, "removed_group": existed, "tickers_removed_count": removed_count}

    def remove_ticker(self, ticker: str, group_name: Optional[str] = None, from_favorites: bool = False) -> Dict[str, Any]:
        payload = self._read_payload()
        groups = payload.get("groups") or {}
        favorites = list(payload.get("favorites") or [])
        removed_groups: List[str] = []
        removed_fav = False
        if group_name:
            gname = str(group_name).strip().lower()
            current = list(groups.get(gname) or [])
            if ticker in current:
                groups[gname] = [t for t in current if t != ticker]
                if not groups[gname]:
                    groups.pop(gname, None)
                removed_groups.append(gname)
        else:
            for gname, current in list(groups.items()):
                if ticker in current:
                    groups[gname] = [t for t in current if t != ticker]
                    if not groups[gname]:
                        groups.pop(gname, None)
                    removed_groups.append(gname)

        if from_favorites or (group_name and str(group_name).strip().lower() == "favorites"):
            if ticker in favorites:
                favorites = [t for t in favorites if t != ticker]
                removed_fav = True

        payload["groups"] = groups
        payload["favorites"] = favorites
        self._write_payload(payload)
        return {"ticker": ticker, "removed_from_groups": sorted(set(removed_groups)), "removed_from_favorites": removed_fav}


class DbAlertRulesStoreAdapter:
    """Compatibility adapter that mimics JsonStore(read/write) on top of one JSON SQL table."""

    def __init__(self, db: DatabaseManager):
        self.db = db

    def read(self) -> Dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(sa.select(alerts_state.c.payload, alerts_state.c.updated_at).where(alerts_state.c.id == 1)).mappings().first()
        if not row:
            return {"schema_version": 1, "updated_at": _now_iso(), "rules": []}
        payload = _safe_json(row.get("payload"))
        payload.setdefault("schema_version", 1)
        payload.setdefault("updated_at", str(row.get("updated_at") or _now_iso()))
        payload.setdefault("rules", [])
        return payload

    def write(self, data: Dict[str, Any]) -> None:
        payload = dict(data or {})
        payload.setdefault("schema_version", 1)
        payload["updated_at"] = _now_iso()
        now = datetime.now(timezone.utc)
        with self.db.begin() as conn:
            exists = conn.execute(sa.select(alerts_state.c.id).where(alerts_state.c.id == 1)).scalar_one_or_none()
            if exists is None:
                conn.execute(sa.insert(alerts_state).values(id=1, payload=payload, updated_at=now))
            else:
                conn.execute(
                    sa.update(alerts_state)
                    .where(alerts_state.c.id == 1)
                    .values(payload=payload, updated_at=now)
                )

    def log_event(self, alert_id: str, symbol: Optional[str], event_type: str, payload: Optional[Dict[str, Any]] = None, message: Optional[str] = None) -> None:
        try:
            data = self.read()
            events = list(data.get("events") or [])
            events.append(
                {
                    "id": _uuid(),
                    "alert_id": alert_id,
                    "symbol": symbol or "",
                    "event_type": event_type,
                    "payload": payload or {},
                    "message": message,
                    "created_at": _now_iso(),
                }
            )
            # keep storage bounded
            data["events"] = events[-500:]
            self.write(data)
        except Exception:
            logger.exception("Failed to persist alert event")


class DbCoordinationRepository:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def send_agent_message(
        self,
        *,
        thread_id: str,
        from_agent: str,
        message_type: str,
        payload: Dict[str, Any],
        to_agent: Optional[str] = None,
        to_team: Optional[str] = None,
        priority: str = "normal",
        subject: Optional[str] = None,
        related_symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        mid = _uuid()
        with self.db.begin() as conn:
            conn.execute(
                sa.insert(agent_messages).values(
                    id=mid,
                    thread_id=thread_id,
                    from_agent=from_agent,
                    to_agent=to_agent,
                    to_team=to_team,
                    message_type=message_type,
                    priority=priority,
                    status="pending",
                    subject=subject,
                    payload=payload,
                    related_symbol=related_symbol,
                )
            )
        return {"id": mid, "status": "pending"}

    def poll_agent_messages(self, *, to_agent: Optional[str] = None, to_team: Optional[str] = None, status: str = "pending", limit: int = 20) -> List[Dict[str, Any]]:
        with self.db.connect() as conn:
            stmt = sa.select(agent_messages).where(agent_messages.c.status == status)
            if to_agent:
                stmt = stmt.where(agent_messages.c.to_agent == to_agent)
            if to_team:
                stmt = stmt.where(agent_messages.c.to_team == to_team)
            stmt = stmt.order_by(agent_messages.c.created_at.asc()).limit(limit)
            rows = conn.execute(stmt).mappings().all()
        return [dict(r) for r in rows]

    def mark_agent_message_processed(self, message_id: str, status: str = "processed") -> None:
        with self.db.begin() as conn:
            conn.execute(
                sa.update(agent_messages)
                .where(agent_messages.c.id == message_id)
                .values(status=status, processed_at=sa.func.now())
            )

    def create_task(self, *, task_key: str, team_name: str, task_type: str, title: str, requested_by: str, input_payload: Optional[Dict[str, Any]] = None, description: Optional[str] = None, priority: int = 50) -> Dict[str, Any]:
        tid = _uuid()
        with self.db.begin() as conn:
            exists = conn.execute(sa.select(tasks.c.id).where(tasks.c.task_key == task_key)).scalar_one_or_none()
            if exists:
                return {"id": str(exists), "created": False}
            conn.execute(
                sa.insert(tasks).values(
                    id=tid,
                    task_key=task_key,
                    team_name=team_name,
                    task_type=task_type,
                    title=title,
                    requested_by=requested_by,
                    input=input_payload or {},
                    description=description,
                    priority=priority,
                    status="pending",
                    result={},
                )
            )
        return {"id": tid, "created": True}

    def log_artifact(self, *, artifact_type: str, path: str, created_by: str, task_id: Optional[str] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        aid = _uuid()
        with self.db.begin() as conn:
            conn.execute(
                sa.insert(artifacts).values(
                    id=aid,
                    artifact_type=artifact_type,
                    path=path,
                    created_by=created_by,
                    task_id=task_id,
                    meta=meta or {},
                )
            )
        return {"id": aid}

    def create_report(self, *, report_type: str, scope_type: str, title: str, summary: str, created_by: str, scope_value: Optional[str] = None, chat_id: Optional[int] = None, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        rid = _uuid()
        with self.db.begin() as conn:
            conn.execute(
                sa.insert(reports).values(
                    id=rid,
                    report_type=report_type,
                    scope_type=scope_type,
                    scope_value=scope_value,
                    chat_id=chat_id,
                    title=title,
                    summary=summary,
                    payload=payload or {},
                    created_by=created_by,
                )
            )
        return {"id": rid}

    def log_observation(self, *, source_agent: str, observation_type: str, content: str, team_name: Optional[str] = None, symbol: Optional[str] = None, strategy_name: Optional[str] = None, severity: str = "info", payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        oid = _uuid()
        with self.db.begin() as conn:
            conn.execute(
                sa.insert(observations).values(
                    id=oid,
                    source_agent=source_agent,
                    team_name=team_name,
                    observation_type=observation_type,
                    symbol=symbol,
                    strategy_name=strategy_name,
                    severity=severity,
                    content=content,
                    payload=payload or {},
                )
            )
        return {"id": oid}


class DbMemoryRepository:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def remember_fact(self, *, category: str, key: str, value: str, source: str, team_name: Optional[str] = None, strategy_name: Optional[str] = None, symbol: Optional[str] = None, confidence: float = 1.0, source_ref: Optional[str] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with self.db.begin() as conn:
            existing = conn.execute(
                sa.select(memory_semantic.c.id).where(
                    sa.and_(
                        memory_semantic.c.team_name.is_(team_name) if team_name is None else memory_semantic.c.team_name == team_name,
                        memory_semantic.c.strategy_name.is_(strategy_name) if strategy_name is None else memory_semantic.c.strategy_name == strategy_name,
                        memory_semantic.c.symbol.is_(symbol) if symbol is None else memory_semantic.c.symbol == symbol,
                        memory_semantic.c.category == category,
                        memory_semantic.c.fact_key == key,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                conn.execute(
                    sa.update(memory_semantic)
                    .where(memory_semantic.c.id == existing)
                    .values(
                        fact_value=value,
                        confidence=confidence,
                        source=source,
                        source_ref=source_ref,
                        meta=meta or {},
                        updated_at=sa.func.now(),
                    )
                )
                return {"id": str(existing), "updated": True}
            mid = _uuid()
            conn.execute(
                sa.insert(memory_semantic).values(
                    id=mid,
                    team_name=team_name,
                    strategy_name=strategy_name,
                    symbol=symbol,
                    category=category,
                    fact_key=key,
                    fact_value=value,
                    confidence=confidence,
                    source=source,
                    source_ref=source_ref,
                    meta=meta or {},
                )
            )
            return {"id": mid, "updated": False}

    def recall_facts(self, *, category: Optional[str] = None, strategy_name: Optional[str] = None, symbol: Optional[str] = None, team_name: Optional[str] = None, query: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        with self.db.connect() as conn:
            stmt = sa.select(memory_semantic)
            if category:
                stmt = stmt.where(memory_semantic.c.category == category)
            if strategy_name:
                stmt = stmt.where(memory_semantic.c.strategy_name == strategy_name)
            if symbol:
                stmt = stmt.where(memory_semantic.c.symbol == symbol)
            if team_name:
                stmt = stmt.where(memory_semantic.c.team_name == team_name)
            if query:
                like = f"%{query}%"
                stmt = stmt.where(sa.or_(memory_semantic.c.fact_key.ilike(like), memory_semantic.c.fact_value.ilike(like)))
            stmt = stmt.order_by(memory_semantic.c.updated_at.desc()).limit(limit)
            rows = conn.execute(stmt).mappings().all()
        return [dict(r) for r in rows]

    def log_experiment(self, *, episode_type: str, title: str, summary: str, created_by: str, outcome: Optional[str] = None, team_name: Optional[str] = None, strategy_name: Optional[str] = None, symbol: Optional[str] = None, importance: float = 0.5, payload: Optional[Dict[str, Any]] = None, task_id: Optional[str] = None, artifact_id: Optional[str] = None) -> Dict[str, Any]:
        eid = _uuid()
        with self.db.begin() as conn:
            conn.execute(
                sa.insert(memory_episodic).values(
                    id=eid,
                    team_name=team_name,
                    strategy_name=strategy_name,
                    symbol=symbol,
                    episode_type=episode_type,
                    title=title,
                    summary=summary,
                    outcome=outcome,
                    importance=importance,
                    payload=payload or {},
                    task_id=task_id,
                    artifact_id=artifact_id,
                    created_by=created_by,
                )
            )
        return {"id": eid}

    def save_procedure(self, *, procedure_name: str, description: str, steps: List[Dict[str, Any]], created_by: str, team_name: Optional[str] = None, strategy_name: Optional[str] = None, symbol: Optional[str] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        pid = _uuid()
        with self.db.begin() as conn:
            latest = conn.execute(
                sa.select(sa.func.max(memory_procedural.c.version)).where(
                    sa.and_(
                        memory_procedural.c.procedure_name == procedure_name,
                        memory_procedural.c.team_name.is_(team_name) if team_name is None else memory_procedural.c.team_name == team_name,
                        memory_procedural.c.strategy_name.is_(strategy_name) if strategy_name is None else memory_procedural.c.strategy_name == strategy_name,
                        memory_procedural.c.symbol.is_(symbol) if symbol is None else memory_procedural.c.symbol == symbol,
                    )
                )
            ).scalar_one()
            version = int(latest or 0) + 1
            conn.execute(
                sa.insert(memory_procedural).values(
                    id=pid,
                    team_name=team_name,
                    strategy_name=strategy_name,
                    symbol=symbol,
                    procedure_name=procedure_name,
                    description=description,
                    steps=steps,
                    version=version,
                    created_by=created_by,
                    meta=meta or {},
                )
            )
        return {"id": pid, "version": version}

    def recall_procedures(self, *, procedure_name: Optional[str] = None, query: Optional[str] = None, team_name: Optional[str] = None, strategy_name: Optional[str] = None, symbol: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        with self.db.connect() as conn:
            stmt = sa.select(memory_procedural)
            if procedure_name:
                stmt = stmt.where(memory_procedural.c.procedure_name == procedure_name)
            if team_name:
                stmt = stmt.where(memory_procedural.c.team_name == team_name)
            if strategy_name:
                stmt = stmt.where(memory_procedural.c.strategy_name == strategy_name)
            if symbol:
                stmt = stmt.where(memory_procedural.c.symbol == symbol)
            if query:
                like = f"%{query}%"
                stmt = stmt.where(sa.or_(memory_procedural.c.procedure_name.ilike(like), memory_procedural.c.description.ilike(like)))
            stmt = stmt.order_by(memory_procedural.c.updated_at.desc()).limit(limit)
            rows = conn.execute(stmt).mappings().all()
        return [dict(r) for r in rows]

    def review_memory_scope(self, *, team_name: Optional[str] = None, strategy_name: Optional[str] = None, symbol: Optional[str] = None) -> Dict[str, Any]:
        facts = self.recall_facts(team_name=team_name, strategy_name=strategy_name, symbol=symbol, limit=8)
        with self.db.connect() as conn:
            epi_stmt = sa.select(memory_episodic)
            if team_name:
                epi_stmt = epi_stmt.where(memory_episodic.c.team_name == team_name)
            if strategy_name:
                epi_stmt = epi_stmt.where(memory_episodic.c.strategy_name == strategy_name)
            if symbol:
                epi_stmt = epi_stmt.where(memory_episodic.c.symbol == symbol)
            episodes = conn.execute(epi_stmt.order_by(memory_episodic.c.created_at.desc()).limit(5)).mappings().all()
            proc_stmt = sa.select(memory_procedural)
            if team_name:
                proc_stmt = proc_stmt.where(memory_procedural.c.team_name == team_name)
            if strategy_name:
                proc_stmt = proc_stmt.where(memory_procedural.c.strategy_name == strategy_name)
            if symbol:
                proc_stmt = proc_stmt.where(memory_procedural.c.symbol == symbol)
            procedures = conn.execute(proc_stmt.order_by(memory_procedural.c.updated_at.desc()).limit(5)).mappings().all()
        return {
            "scope": {"team_name": team_name, "strategy_name": strategy_name, "symbol": symbol},
            "facts": [dict(r) for r in facts],
            "episodes": [dict(r) for r in episodes],
            "procedures": [dict(r) for r in procedures],
        }


class DbChatContextRepository:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def append_turn(self, *, chat_id: int, user_id: Optional[int], role: str, content: str, meta: Optional[Dict[str, Any]] = None) -> str:
        tid = _uuid()
        with self.db.begin() as conn:
            conn.execute(
                sa.insert(chat_turns).values(
                    id=tid,
                    chat_id=int(chat_id),
                    user_id=int(user_id) if user_id is not None else None,
                    role=role,
                    content=content,
                    meta=meta or {},
                )
            )
        return tid

    def get_recent_turns(self, *, chat_id: int, limit: int = 6) -> List[Dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                sa.select(chat_turns)
                .where(chat_turns.c.chat_id == int(chat_id))
                .order_by(chat_turns.c.created_at.desc())
                .limit(limit)
            ).mappings().all()
        out = [dict(r) for r in rows]
        out.reverse()
        return out

    def upsert_chat_state(self, *, chat_id: int, user_id: Optional[int] = None, active_domain: Optional[str] = None, active_symbol: Optional[str] = None, active_group: Optional[str] = None, timeframe: Optional[str] = None, last_agent: Optional[str] = None, context_json: Optional[Dict[str, Any]] = None) -> None:
        with self.db.begin() as conn:
            exists = conn.execute(sa.select(chat_sessions.c.chat_id).where(chat_sessions.c.chat_id == int(chat_id))).scalar_one_or_none()
            values = {
                "user_id": int(user_id) if user_id is not None else None,
                "active_domain": active_domain,
                "active_symbol": active_symbol,
                "active_group": active_group,
                "timeframe": timeframe,
                "last_agent": last_agent,
                "context_json": context_json or {},
                "updated_at": sa.func.now(),
            }
            if exists is None:
                conn.execute(sa.insert(chat_sessions).values(chat_id=int(chat_id), **values))
            else:
                # only overwrite provided non-None fields except context_json can be empty dict
                clean = {"updated_at": sa.func.now()}
                for k, v in values.items():
                    if k == "updated_at":
                        continue
                    if v is not None or k == "context_json":
                        clean[k] = v
                conn.execute(sa.update(chat_sessions).where(chat_sessions.c.chat_id == int(chat_id)).values(**clean))

    def get_chat_state(self, chat_id: int) -> Optional[Dict[str, Any]]:
        with self.db.connect() as conn:
            row = conn.execute(sa.select(chat_sessions).where(chat_sessions.c.chat_id == int(chat_id))).mappings().first()
        return dict(row) if row else None

    def build_context_summary(self, *, chat_id: int, max_turns: int = 4) -> Optional[str]:
        state = self.get_chat_state(chat_id)
        turns = self.get_recent_turns(chat_id=chat_id, limit=max_turns)
        if not state and not turns:
            return None
        lines: List[str] = ["Persisted chat context (shared state):"]
        if state:
            if state.get("active_domain"):
                lines.append(f"- active_domain: {state['active_domain']}")
            if state.get("active_symbol"):
                lines.append(f"- active_symbol: {state['active_symbol']}")
            if state.get("active_group"):
                lines.append(f"- active_group: {state['active_group']}")
            if state.get("timeframe"):
                lines.append(f"- timeframe: {state['timeframe']}")
        if turns:
            lines.append("- recent_turns:")
            for t in turns:
                role = t.get("role", "?")
                content = str(t.get("content") or "").strip().replace("\n", " ")
                if len(content) > 200:
                    content = content[:200] + "..."
                lines.append(f"  - {role}: {content}")
        lines.append("Use this context if it matches the current request; ask a clarification only if needed.")
        return "\n".join(lines)


# Convenience no-op fallbacks are intentionally omitted to surface configuration mistakes in integration points.
