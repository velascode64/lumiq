"""
Simple JSON persistence for alerts and portfolio.

Designed to be replaced by a real database later.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_portfolio(now_iso: str | None = None) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "updated_at": now_iso or _utc_now_iso(),
        "positions": [],
        "cash": None,
        "currency": "USD",
    }


def default_alert_rules(now_iso: str | None = None) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "updated_at": now_iso or _utc_now_iso(),
        "rules": [],
    }


@dataclass
class JsonStore:
    path: Path
    default_factory: callable

    def read(self) -> Dict[str, Any]:
        if not self.path.exists():
            data = self.default_factory()
            self.write(data)
            return data

        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def write(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=True, indent=2, sort_keys=True)
            f.write("\n")
        tmp_path.replace(self.path)


def portfolio_store(path: Path) -> JsonStore:
    return JsonStore(path=path, default_factory=default_portfolio)


def alert_rules_store(path: Path) -> JsonStore:
    return JsonStore(path=path, default_factory=default_alert_rules)
