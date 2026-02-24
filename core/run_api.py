#!/usr/bin/env python3
"""
Local entrypoint for Lumiq Core FastAPI server (conda-friendly).
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


def _load_env() -> None:
    if load_dotenv is None:
        return
    core_dir = Path(__file__).resolve().parent
    for env_path in (core_dir / ".env", core_dir.parent / ".env"):
        if env_path.exists():
            load_dotenv(env_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Lumiq Core API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument(
        "--strategies-path",
        default=str(Path(__file__).resolve().parent / "strategies" / "live"),
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    _load_env()

    try:
        import uvicorn
        from .api_server import create_app
    except ImportError:
        import uvicorn
        from api_server import create_app

    app = create_app(strategies_path=args.strategies_path)
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()

