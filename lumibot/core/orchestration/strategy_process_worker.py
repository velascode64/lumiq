#!/usr/bin/env python3
"""
Worker process that runs exactly one Lumibot strategy.
"""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import logging
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

# Prevent lumibot.credentials from auto-spawning a hidden broker/stream on import.
os.environ.setdefault("TRADING_BROKER", "none")

from lumibot.brokers import Alpaca
from lumibot.strategies import Strategy
from lumibot.traders import Trader

try:
    from .trading_core import TradingCore
except ImportError:
    from trading_core import TradingCore


logger = logging.getLogger("strategy_process_worker")

_ACTIVE_TRADER: Optional[Trader] = None


def _register_strategies(core: TradingCore, strategies_path: Path) -> int:
    discovered = 0
    existing_names = set(core.factory.get_available_strategies().keys())
    for py_file in sorted(strategies_path.glob("*.py")):
        if py_file.name.startswith("__") or py_file.name.endswith("_ui.py"):
            continue
        module_name = f"worker_live_{py_file.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for _name, obj in inspect.getmembers(module, inspect.isclass):
                if obj is Strategy or not issubclass(obj, Strategy):
                    continue
                if obj.__module__ != module.__name__:
                    continue
                if obj.__name__ in existing_names:
                    continue
                default_params = getattr(obj, "parameters", {}) or {}
                if not isinstance(default_params, dict):
                    default_params = {}
                core.factory.register_strategy(obj.__name__, obj, default_params)
                existing_names.add(obj.__name__)
                discovered += 1
        except Exception as exc:
            logger.warning("Failed to load strategy from %s: %s", py_file, exc)
    return discovered


def _install_signal_handlers() -> None:
    def _shutdown(signum, frame):  # type: ignore[unused-argument]
        logger.warning("Received signal %s, requesting trader stop", signum)
        global _ACTIVE_TRADER
        if _ACTIVE_TRADER is not None:
            try:
                _ACTIVE_TRADER.stop_all()
            except Exception as exc:
                logger.error("Failed to stop trader gracefully: %s", exc)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)


def _patch_thread_signals() -> None:
    """
    Keep compatibility if Lumibot registers signals from a non-main thread internally.
    """
    import lumibot.traders.trader as trader_module

    original_signal = trader_module.signal.signal
    main_thread = threading.main_thread()

    def safe_signal(sig, handler):
        if threading.current_thread() is main_thread:
            return original_signal(sig, handler)
        return None

    trader_module.signal.signal = safe_signal


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy-name", required=True)
    parser.add_argument("--mode", choices=["paper", "live"], required=True)
    parser.add_argument("--strategies-path", required=True)
    parser.add_argument("--broker-config-json", required=True)
    parser.add_argument("--params-json", required=True)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    _patch_thread_signals()
    _install_signal_handlers()

    broker_config = json.loads(args.broker_config_json)
    params: Dict[str, Any] = json.loads(args.params_json)
    broker_config = dict(broker_config)
    broker_config["IS_PAPER"] = args.mode == "paper"

    core = TradingCore(broker_config=broker_config)
    strategies_path = Path(args.strategies_path).resolve()
    _register_strategies(core, strategies_path)

    logger.info("Launching strategy %s (mode=%s)", args.strategy_name, args.mode)
    broker = Alpaca(broker_config)
    strategy_instance = core.factory.create_strategy(args.strategy_name, broker=broker, parameters=params or {})

    trader = Trader()
    trader.add_strategy(strategy_instance)

    global _ACTIVE_TRADER
    _ACTIVE_TRADER = trader

    try:
        trader.run_all()
        logger.info("Strategy %s exited normally", args.strategy_name)
        return 0
    except Exception as exc:
        logger.exception("Strategy %s crashed: %s", args.strategy_name, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
