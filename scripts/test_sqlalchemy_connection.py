#!/usr/bin/env python3
"""
Simple SQLAlchemy connectivity test for Lumiq.

Usage:
  conda activate lumiq
  cd lumiq
  python scripts/test_sqlalchemy_connection.py

Reads:
  - LUMIQ_DATABASE_URL (preferred)
  - DATABASE_URL (fallback)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    root = Path(__file__).resolve().parents[1]
    for p in (root / ".env", root.parent / ".env"):
        if p.exists():
            load_dotenv(p)


def _mask_url(url: str) -> str:
    if not url:
        return ""
    # Keep scheme + host/db hints, hide credentials.
    try:
        if "://" not in url:
            return "<masked>"
        scheme, rest = url.split("://", 1)
        if "@" in rest:
            creds, tail = rest.split("@", 1)
            _ = creds
            return f"{scheme}://***:***@{tail}"
        return f"{scheme}://{rest}"
    except Exception:
        return "<masked>"


def main() -> int:
    _load_env()
    db_url = (os.getenv("LUMIQ_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    if not db_url:
        print("ERROR: LUMIQ_DATABASE_URL (or DATABASE_URL) is not set.")
        return 1

    try:
        import sqlalchemy as sa
    except Exception as exc:
        print(f"ERROR: SQLAlchemy is not installed in this environment: {exc}")
        return 2

    print("Testing SQLAlchemy connection...")
    print("DB URL:", _mask_url(db_url))

    try:
        engine = sa.create_engine(db_url, future=True, pool_pre_ping=True)
        with engine.connect() as conn:
            one = conn.exec_driver_sql("select 1 as ok").scalar_one()
            version = conn.exec_driver_sql("select version()").scalar_one()
        print("SELECT 1:", one)
        print("Postgres version:", str(version)[:180])
        print("RESULT: OK")
        return 0
    except Exception as exc:
        print(f"RESULT: FAIL ({type(exc).__name__})")
        print(str(exc))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

