from __future__ import annotations

import pytest
import sys
from pathlib import Path
from urllib.parse import quote_plus
import os

try:
    from pytest_postgresql import factories
except ModuleNotFoundError:  # pragma: no cover
    factories = None

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lumiq.platform.db.core import DatabaseManager


if factories is not None:
    pg_port = int(os.getenv("PYTEST_PG_PORT", "55432"))
    postgresql_proc = factories.postgresql_proc(port=pg_port)
    postgresql = factories.postgresql("postgresql_proc")
else:
    @pytest.fixture()
    def postgresql():
        pytest.skip("pytest-postgresql is not installed")


def _build_db_url(pg_conn) -> str:
    params = {}
    if hasattr(pg_conn, "get_dsn_parameters"):
        # psycopg2 connection
        params = pg_conn.get_dsn_parameters() or {}
    elif hasattr(pg_conn, "info"):
        # psycopg3 connection
        info = pg_conn.info
        params = {
            "user": getattr(info, "user", None),
            "password": None,
            "host": getattr(info, "host", None),
            "port": str(getattr(info, "port", "") or ""),
            "dbname": getattr(info, "dbname", None),
        }
    user = params.get("user") or "postgres"
    password = params.get("password") or ""
    host = params.get("host") or "127.0.0.1"
    port = params.get("port") or "5432"
    dbname = params.get("dbname") or "test"
    auth = quote_plus(user)
    if password:
        auth = f"{auth}:{quote_plus(password)}"
    return f"postgresql+psycopg://{auth}@{host}:{port}/{dbname}"


def _build_db_url_from_proc(pg_proc) -> str:
    host = getattr(pg_proc, "host", None) or "127.0.0.1"
    port = str(getattr(pg_proc, "port", None) or "5432")
    user = getattr(pg_proc, "user", None) or "postgres"
    password = getattr(pg_proc, "password", None) or ""
    dbname = getattr(pg_proc, "dbname", None) or "test"
    auth = quote_plus(user)
    if password:
        auth = f"{auth}:{quote_plus(password)}"
    return f"postgresql+psycopg://{auth}@{host}:{port}/{dbname}"


@pytest.fixture()
def db_manager(postgresql, postgresql_proc):
    if factories is None:
        pytest.skip("pytest-postgresql is not installed")
    try:
        db_url = _build_db_url(postgresql)
    except Exception:
        db_url = _build_db_url_from_proc(postgresql_proc)
    manager = DatabaseManager(db_url=db_url, auto_create=True, echo=False)
    yield manager
