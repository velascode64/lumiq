from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

try:
    import sqlalchemy as sa
    from sqlalchemy import MetaData, Table, Column
    from sqlalchemy import String, Text, Integer, Boolean, DateTime, Numeric
    from sqlalchemy import JSON
    from sqlalchemy.sql import func
except Exception:  # pragma: no cover
    sa = None  # type: ignore[assignment]
    MetaData = Table = Column = None  # type: ignore[assignment]
    String = Text = Integer = Boolean = DateTime = Numeric = JSON = None  # type: ignore[assignment]
    func = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)
SQLALCHEMY_AVAILABLE = sa is not None


metadata = MetaData() if SQLALCHEMY_AVAILABLE else None


def _t(*args, **kwargs):
    if not SQLALCHEMY_AVAILABLE:
        raise RuntimeError("SQLAlchemy is not installed")
    return Table(*args, **kwargs)


if SQLALCHEMY_AVAILABLE:
    watchlist_groups = _t(
        "watchlist_groups",
        metadata,
        Column("id", String(64), primary_key=True),
        Column("chat_id", sa.BigInteger, nullable=True, index=True),
        Column("user_id", sa.BigInteger, nullable=True, index=True),
        Column("name", String(128), nullable=False),
        Column("kind", String(32), nullable=False, server_default=sa.text("'custom'"), index=True),
        Column("tickers", JSON, nullable=False, server_default=sa.text("'[]'")),
        Column("benchmarks", JSON, nullable=False, server_default=sa.text("'{}'")),
        Column("meta", JSON, nullable=False, server_default=sa.text("'{}'")),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        sa.UniqueConstraint("chat_id", "user_id", "name", name="uq_watchlist_groups_owner_name"),
    )

    # Legacy singleton JSON store removed. Keep the symbol for import compatibility.
    watchlist_state = None

    # Legacy singleton JSON store removed. Keep the symbol for import compatibility.
    alerts_state = None

    alerts = _t(
        "alerts",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("chat_id", sa.BigInteger, nullable=True, index=True),
        Column("user_id", sa.BigInteger, nullable=True, index=True),
        Column("symbol", String(64), nullable=False, index=True),
        Column("rule_type", String(64), nullable=False, index=True),
        Column("active", Boolean, nullable=False, server_default=sa.text("true"), index=True),
        Column("cooldown_seconds", Integer, nullable=False, server_default=sa.text("3600")),
        Column("threshold_pct", Numeric(18, 8), nullable=True),
        Column("target_price", Numeric(18, 8), nullable=True),
        Column("reference_price", Numeric(18, 8), nullable=True),
        Column("last_triggered_price", Numeric(18, 8), nullable=True),
        Column("last_triggered_at", DateTime(timezone=True), nullable=True, index=True),
        Column("params", JSON, nullable=False, server_default=sa.text("'{}'")),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    )

    agent_messages = _t(
        "agent_messages",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("thread_id", String(255), nullable=False, index=True),
        Column("from_agent", String(128), nullable=False, index=True),
        Column("to_agent", String(128), nullable=True, index=True),
        Column("to_team", String(128), nullable=True, index=True),
        Column("message_type", String(64), nullable=False, index=True),
        Column("priority", String(16), nullable=False, server_default=sa.text("'normal'")),
        Column("status", String(16), nullable=False, server_default=sa.text("'pending'"), index=True),
        Column("subject", String(255), nullable=True),
        Column("payload", JSON, nullable=False),
        Column("related_strategy_id", String(36), nullable=True),
        Column("related_backtest_run_id", String(36), nullable=True),
        Column("related_symbol", String(64), nullable=True, index=True),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("processed_at", DateTime(timezone=True), nullable=True),
    )

    tasks = _t(
        "tasks",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("task_key", String(255), nullable=False, unique=True),
        Column("team_name", String(128), nullable=False, index=True),
        Column("task_type", String(64), nullable=False, index=True),
        Column("status", String(16), nullable=False, server_default=sa.text("'pending'"), index=True),
        Column("priority", Integer, nullable=False, server_default=sa.text("50"), index=True),
        Column("requested_by", String(128), nullable=False),
        Column("owner_agent", String(128), nullable=True, index=True),
        Column("title", String(255), nullable=False),
        Column("description", Text, nullable=True),
        Column("input", JSON, nullable=False, server_default=sa.text("'{}'")),
        Column("result", JSON, nullable=False, server_default=sa.text("'{}'")),
        Column("error", Text, nullable=True),
        Column("scheduled_for", DateTime(timezone=True), nullable=True, index=True),
        Column("started_at", DateTime(timezone=True), nullable=True),
        Column("finished_at", DateTime(timezone=True), nullable=True),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    )

    task_runs = _t(
        "task_runs",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("task_id", String(36), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True),
        Column("runner", String(128), nullable=False),
        Column("attempt", Integer, nullable=False),
        Column("status", String(16), nullable=False),
        Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("finished_at", DateTime(timezone=True), nullable=True),
        Column("logs_summary", Text, nullable=True),
        Column("metrics", JSON, nullable=False, server_default=sa.text("'{}'")),
        Column("error", Text, nullable=True),
    )

    artifacts = _t(
        "artifacts",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("artifact_type", String(64), nullable=False, index=True),
        Column("storage_kind", String(32), nullable=False, server_default=sa.text("'local_fs'")),
        Column("path", Text, nullable=False),
        Column("checksum", String(128), nullable=True),
        Column("size_bytes", sa.BigInteger, nullable=True),
        Column("mime_type", String(128), nullable=True),
        Column("meta", JSON, nullable=False, server_default=sa.text("'{}'")),
        Column("created_by", String(128), nullable=False),
        Column("task_id", String(36), sa.ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    )

    reports = _t(
        "reports",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("report_type", String(64), nullable=False, index=True),
        Column("scope_type", String(64), nullable=False, index=True),
        Column("scope_value", String(255), nullable=True, index=True),
        Column("chat_id", sa.BigInteger, nullable=True, index=True),
        Column("title", String(255), nullable=False),
        Column("summary", Text, nullable=False),
        Column("payload", JSON, nullable=False, server_default=sa.text("'{}'")),
        Column("created_by", String(128), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    )

    observations = _t(
        "observations",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("source_agent", String(128), nullable=False, index=True),
        Column("team_name", String(128), nullable=True, index=True),
        Column("observation_type", String(64), nullable=False, index=True),
        Column("symbol", String(64), nullable=True, index=True),
        Column("strategy_name", String(128), nullable=True, index=True),
        Column("severity", String(16), nullable=False, server_default=sa.text("'info'")),
        Column("content", Text, nullable=False),
        Column("payload", JSON, nullable=False, server_default=sa.text("'{}'")),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    )

    memory_semantic = _t(
        "memory_semantic",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("team_name", String(128), nullable=True, index=True),
        Column("strategy_name", String(128), nullable=True, index=True),
        Column("symbol", String(64), nullable=True, index=True),
        Column("category", String(64), nullable=False, index=True),
        Column("fact_key", String(255), nullable=False),
        Column("fact_value", Text, nullable=False),
        Column("confidence", Numeric(4, 3), nullable=False, server_default=sa.text("1.0")),
        Column("source", String(64), nullable=False),
        Column("source_ref", String(255), nullable=True),
        Column("meta", JSON, nullable=False, server_default=sa.text("'{}'")),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        sa.UniqueConstraint(
            "team_name",
            "strategy_name",
            "symbol",
            "category",
            "fact_key",
            name="uq_memory_semantic_scope_key",
        ),
    )

    memory_episodic = _t(
        "memory_episodic",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("team_name", String(128), nullable=True, index=True),
        Column("strategy_name", String(128), nullable=True, index=True),
        Column("symbol", String(64), nullable=True, index=True),
        Column("episode_type", String(64), nullable=False, index=True),
        Column("title", String(255), nullable=False),
        Column("summary", Text, nullable=False),
        Column("outcome", String(32), nullable=True),
        Column("importance", Numeric(4, 3), nullable=False, server_default=sa.text("0.5")),
        Column("task_id", String(36), nullable=True),
        Column("artifact_id", String(36), nullable=True),
        Column("payload", JSON, nullable=False, server_default=sa.text("'{}'")),
        Column("created_by", String(128), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    )

    memory_procedural = _t(
        "memory_procedural",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("team_name", String(128), nullable=True, index=True),
        Column("strategy_name", String(128), nullable=True, index=True),
        Column("symbol", String(64), nullable=True, index=True),
        Column("procedure_name", String(255), nullable=False, index=True),
        Column("description", Text, nullable=False),
        Column("steps", JSON, nullable=False),
        Column("version", Integer, nullable=False, server_default=sa.text("1")),
        Column("success_count", Integer, nullable=False, server_default=sa.text("0")),
        Column("failure_count", Integer, nullable=False, server_default=sa.text("0")),
        Column("last_used_at", DateTime(timezone=True), nullable=True),
        Column("created_by", String(128), nullable=False),
        Column("meta", JSON, nullable=False, server_default=sa.text("'{}'")),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    )

    chat_sessions = _t(
        "chat_sessions",
        metadata,
        Column("chat_id", sa.BigInteger, primary_key=True),
        Column("user_id", sa.BigInteger, nullable=True, index=True),
        Column("active_domain", String(64), nullable=True),
        Column("active_symbol", String(64), nullable=True),
        Column("active_group", String(128), nullable=True),
        Column("timeframe", String(32), nullable=True),
        Column("last_agent", String(128), nullable=True),
        Column("context_json", JSON, nullable=False, server_default=sa.text("'{}'")),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    )

    chat_turns = _t(
        "chat_turns",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("chat_id", sa.BigInteger, nullable=False, index=True),
        Column("user_id", sa.BigInteger, nullable=True, index=True),
        Column("role", String(16), nullable=False),  # user|assistant|system
        Column("content", Text, nullable=False),
        Column("meta", JSON, nullable=False, server_default=sa.text("'{}'")),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    )
else:  # pragma: no cover
    watchlist_groups = None
    watchlist_state = alerts_state = alerts = None
    agent_messages = tasks = task_runs = artifacts = reports = observations = None
    memory_semantic = memory_episodic = memory_procedural = None
    chat_sessions = chat_turns = None


@dataclass
class DatabaseManager:
    db_url: str
    echo: bool = False
    auto_create: bool = True

    def __post_init__(self) -> None:
        if not SQLALCHEMY_AVAILABLE:
            raise RuntimeError("SQLAlchemy is not installed")
        self.engine = sa.create_engine(self.db_url, future=True, pool_pre_ping=True, echo=self.echo)
        if self.auto_create:
            self.create_all()

    def create_all(self) -> None:
        metadata.create_all(self.engine)

    def begin(self):
        return self.engine.begin()

    def connect(self):
        return self.engine.connect()


def create_agno_postgres_db_from_env():
    """Optional Agno PostgresDb for Team/Agent session persistence + memory."""
    db_url = os.getenv("LUMIQ_AGNO_DB_URL", "").strip() or os.getenv("LUMIQ_DATABASE_URL", "").strip() or os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        logger.info("Agno PostgresDb disabled: set LUMIQ_AGNO_DB_URL (or LUMIQ_DATABASE_URL)")
        return None
    try:
        from agno.db.postgres import PostgresDb
    except Exception as exc:  # pragma: no cover
        logger.warning("Agno PostgresDb unavailable: %s", exc)
        return None
    schema = os.getenv("LUMIQ_AGNO_DB_SCHEMA", "agno_lumiq").strip() or "agno_lumiq"
    create_schema = os.getenv("LUMIQ_AGNO_DB_CREATE_SCHEMA", "true").strip().lower() in {"1", "true", "yes", "on"}
    try:
        return PostgresDb(
            db_url=db_url,
            db_schema=schema,
            create_schema=create_schema,
        )
    except Exception as exc:
        logger.exception("Failed to initialize Agno PostgresDb: %s", exc)
        return None


def create_database_manager_from_env() -> Optional[DatabaseManager]:
    db_url = os.getenv("LUMIQ_DATABASE_URL", "").strip() or os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        logger.info("Database disabled: set LUMIQ_DATABASE_URL to enable shared memory/persistence")
        return None
    if not SQLALCHEMY_AVAILABLE:
        logger.warning("Database requested but SQLAlchemy is not installed; DB features disabled")
        return None
    auto_create = os.getenv("LUMIQ_DB_AUTO_CREATE", "true").strip().lower() in {"1", "true", "yes", "on"}
    echo = os.getenv("LUMIQ_DB_ECHO", "false").strip().lower() in {"1", "true", "yes", "on"}
    try:
        return DatabaseManager(db_url=db_url, echo=echo, auto_create=auto_create)
    except Exception as exc:
        logger.exception("Failed to initialize database manager: %s", exc)
        return None
