#!/usr/bin/env python3
"""
Conda-friendly local launcher for Telegram frontend client.

Lets you run `python run_local_telegram.py` from the repo root.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    cmd = [
        "conda",
        "run",
        "--no-capture-output",
        "-n",
        "lumiq",
        "python",
        str(root / "telegram_bot" / "run_bot.py"),
        *sys.argv[1:],
    ]
    return subprocess.call(cmd, cwd=str(root), env=os.environ.copy())


if __name__ == "__main__":
    raise SystemExit(main())
