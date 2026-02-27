#!/usr/bin/env python3
"""
Root entrypoint for Lumiq Core FastAPI server.

Transitional launcher in the repo root (`lumiq/`) that uses the reorganized app path
while preserving current behavior and CLI flags.
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


def _load_env() -> None:
    if load_dotenv is None:
        return
    root_dir = Path(__file__).resolve().parent
    for env_path in (root_dir / ".env", root_dir.parent / ".env"):
        if env_path.exists():
            load_dotenv(env_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Lumiq Core API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument(
        "--strategies-path",
        default=str(Path(__file__).resolve().parent / "lumibot" / "strategies" / "live"),
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    _load_env()

    # Keep import resolution stable across local and container runs.
    # We avoid putting `script_dir` first in sys.path (to prevent stdlib shadowing
    # by local modules like `platform/`), but we keep it available for `app.*`.
    script_dir = Path(__file__).resolve().parent
    repo_parent = script_dir.parent
    # Remove direct occurrences, then re-add in safe order.
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != script_dir]
    if str(repo_parent) not in sys.path:
        sys.path.insert(0, str(repo_parent))
    # Append (not prepend) so stdlib/module resolution keeps precedence.
    if str(script_dir) not in sys.path:
        sys.path.append(str(script_dir))

    import uvicorn
    create_app = None
    try:
        from lumiq.app.main import create_app as _create_app
        create_app = _create_app
    except Exception:
        try:
            from app.main import create_app as _create_app
            create_app = _create_app
        except Exception:
            app_main_path = script_dir / "app" / "main.py"
            if not app_main_path.exists():
                raise RuntimeError(f"Unable to locate app entrypoint at {app_main_path}")
            spec = importlib.util.spec_from_file_location("lumiq_app_main", app_main_path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"Unable to build import spec for {app_main_path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            create_app = getattr(module, "create_app", None)
            if create_app is None:
                raise RuntimeError(f"create_app not found in {app_main_path}")

    app = create_app(strategies_path=args.strategies_path)
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
