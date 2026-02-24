"""
Strategy orchestrator for running Lumibot live/paper strategies in background threads.

This module is designed to be used by a conversational interface (Telegram + Agno)
without blocking the main event loop.
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from lumibot.brokers import Alpaca
from lumibot.strategies import Strategy
from lumibot.traders import Trader

try:
    from .trading_core import TradingCore
except ImportError:
    from trading_core import TradingCore


logger = logging.getLogger(__name__)


@dataclass
class RunningStrategy:
    """In-memory state for one running strategy."""

    strategy_name: str
    mode: str
    parameters: Dict[str, Any]
    trader: Trader
    strategy: Strategy
    thread: threading.Thread
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: Optional[datetime] = None
    status: str = "running"
    last_error: Optional[str] = None


class StrategyOrchestrator:
    """
    Runs and controls strategies concurrently from a single process.

    Notes:
    - Lumibot's Trader registers OS signal handlers, which fails outside the main
      thread. This orchestrator patches that behavior once so strategies can be
      started from background threads safely.
    """

    _signal_patch_lock = threading.Lock()
    _signal_patch_done = False

    def __init__(self, broker_config: Dict[str, Any], strategies_path: Optional[str] = None):
        if not broker_config:
            raise ValueError("Broker configuration is required")

        self.broker_config = broker_config
        self.core = TradingCore(broker_config=broker_config)
        self._lock = threading.RLock()
        self._active: Dict[str, RunningStrategy] = {}
        self._history: Dict[str, RunningStrategy] = {}

        default_path = Path(__file__).resolve().parent / "strategies" / "live"
        self.strategies_path = Path(strategies_path).resolve() if strategies_path else default_path

        self._ensure_thread_safe_trader_signals()
        self.discovered_count = self.register_strategies_from_path(self.strategies_path)

    @classmethod
    def _ensure_thread_safe_trader_signals(cls) -> None:
        """Patch signal registration so Trader can run from non-main threads."""
        with cls._signal_patch_lock:
            if cls._signal_patch_done:
                return

            # Import inside method to keep this class import-light.
            import lumibot.traders.trader as trader_module

            original_signal = trader_module.signal.signal
            main_thread = threading.main_thread()

            def safe_signal(sig, handler):
                if threading.current_thread() is main_thread:
                    return original_signal(sig, handler)
                return None

            trader_module.signal.signal = safe_signal
            cls._signal_patch_done = True
            logger.info("Applied thread-safe signal patch for lumibot Trader")

    def register_strategies_from_path(self, strategies_path: Path) -> int:
        """Discover and register Strategy subclasses from a directory."""
        if not strategies_path.exists():
            logger.warning("Strategies path not found: %s", strategies_path)
            return 0

        discovered = 0
        existing_names = set(self.core.factory.get_available_strategies().keys())
        for py_file in sorted(strategies_path.glob("*.py")):
            if py_file.name.startswith("__"):
                continue
            if py_file.name.endswith("_ui.py"):
                continue

            module_name = f"core_live_{py_file.stem}"
            try:
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec is None or spec.loader is None:
                    logger.warning("Unable to load module spec for %s", py_file)
                    continue

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                for _name, obj in inspect.getmembers(module, inspect.isclass):
                    if obj is Strategy:
                        continue
                    if not issubclass(obj, Strategy):
                        continue
                    if obj.__module__ != module.__name__:
                        continue

                    default_params = getattr(obj, "parameters", {}) or {}
                    if not isinstance(default_params, dict):
                        default_params = {}

                    if obj.__name__ not in existing_names:
                        self.core.factory.register_strategy(
                            name=obj.__name__,
                            strategy_class=obj,
                            default_config=default_params,
                        )
                        existing_names.add(obj.__name__)
                        discovered += 1
            except Exception as exc:
                logger.warning("Failed to register strategies from %s: %s", py_file, exc)

        return discovered

    @staticmethod
    def _normalize(name: str) -> str:
        return "".join(ch for ch in name.lower() if ch.isalnum())

    def list_available_strategies(self) -> List[str]:
        return sorted(self.core.list_strategies().keys())

    def _resolve_strategy_name(self, requested_name: str) -> str:
        available = self.list_available_strategies()
        if requested_name in available:
            return requested_name

        normalized = self._normalize(requested_name)
        exact_map = {self._normalize(name): name for name in available}
        if normalized in exact_map:
            return exact_map[normalized]

        partial_hits = [name for name in available if normalized in self._normalize(name)]
        if len(partial_hits) == 1:
            return partial_hits[0]
        if not partial_hits:
            raise ValueError(
                f"Strategy '{requested_name}' not found. Available: {available}"
            )
        raise ValueError(
            f"Strategy name '{requested_name}' is ambiguous. Matches: {partial_hits}"
        )

    def _resolve_running_name(self, requested_name: str) -> str:
        with self._lock:
            running = list(self._active.keys())

        if requested_name in running:
            return requested_name

        normalized = self._normalize(requested_name)
        exact_map = {self._normalize(name): name for name in running}
        if normalized in exact_map:
            return exact_map[normalized]

        partial_hits = [name for name in running if normalized in self._normalize(name)]
        if len(partial_hits) == 1:
            return partial_hits[0]
        if not partial_hits:
            raise ValueError(f"Strategy '{requested_name}' is not currently running")
        raise ValueError(
            f"Running strategy name '{requested_name}' is ambiguous. Matches: {partial_hits}"
        )

    def _run_strategy(self, running_strategy: RunningStrategy) -> None:
        """Background thread target that executes one Trader.run_all()."""
        try:
            running_strategy.trader.run_all()
            running_strategy.status = "stopped"
        except Exception as exc:
            running_strategy.status = "error"
            running_strategy.last_error = str(exc)
            logger.exception(
                "Strategy '%s' ended with error: %s",
                running_strategy.strategy_name,
                exc,
            )
        finally:
            running_strategy.ended_at = datetime.now(timezone.utc)
            with self._lock:
                self._active.pop(running_strategy.strategy_name, None)
                self._history[running_strategy.strategy_name] = running_strategy

    def start_strategy(
        self,
        strategy_name: str,
        parameters: Optional[Dict[str, Any]] = None,
        mode: str = "paper",
    ) -> Dict[str, Any]:
        """
        Start a strategy in the background.

        Args:
            strategy_name: Registered strategy name (case-insensitive).
            parameters: Optional parameter overrides.
            mode: 'paper' or 'live'.
        """
        mode = mode.lower().strip()
        if mode not in {"paper", "live"}:
            raise ValueError("mode must be 'paper' or 'live'")

        resolved_name = self._resolve_strategy_name(strategy_name)
        with self._lock:
            if resolved_name in self._active:
                return {
                    "success": False,
                    "message": f"Strategy '{resolved_name}' is already running",
                }

        try:
            broker_config = {**self.broker_config, "IS_PAPER": mode == "paper"}
            broker = Alpaca(broker_config)

            strategy_instance = self.core.factory.create_strategy(
                resolved_name,
                broker=broker,
                parameters=parameters or {},
            )

            trader = Trader()
            trader.add_strategy(strategy_instance)
        except Exception as exc:
            return {
                "success": False,
                "message": f"Failed to initialize '{resolved_name}': {exc}",
                "strategy": resolved_name,
                "mode": mode,
            }

        running_state = RunningStrategy(
            strategy_name=resolved_name,
            mode=mode,
            parameters=(parameters or {}).copy(),
            trader=trader,
            strategy=strategy_instance,
            thread=threading.current_thread(),  # replaced immediately below
        )

        thread = threading.Thread(
            target=self._run_strategy,
            args=(running_state,),
            name=f"strategy-{resolved_name}",
            daemon=True,
        )
        running_state.thread = thread

        with self._lock:
            self._active[resolved_name] = running_state

        thread.start()
        return {
            "success": True,
            "message": f"Started '{resolved_name}' in {mode} mode",
            "strategy": resolved_name,
            "mode": mode,
            "parameters": strategy_instance.parameters,
        }

    def stop_strategy(self, strategy_name: str, timeout_seconds: float = 8.0) -> Dict[str, Any]:
        """Stop one running strategy."""
        resolved_name = self._resolve_running_name(strategy_name)
        with self._lock:
            running_state = self._active.get(resolved_name)

        if running_state is None:
            return {
                "success": False,
                "message": f"Strategy '{resolved_name}' is not running",
            }

        running_state.status = "stopping"

        try:
            running_state.trader.stop_all()
        except Exception as exc:
            return {
                "success": False,
                "message": f"Failed to stop '{resolved_name}': {exc}",
            }

        running_state.thread.join(timeout=timeout_seconds)
        if running_state.thread.is_alive():
            return {
                "success": False,
                "message": f"Stop requested for '{resolved_name}', still shutting down",
            }

        return {
            "success": True,
            "message": f"Stopped '{resolved_name}'",
        }

    def stop_all(self) -> Dict[str, Any]:
        """Stop all running strategies."""
        with self._lock:
            running_names = list(self._active.keys())

        results = [self.stop_strategy(name) for name in running_names]
        success_count = sum(1 for item in results if item.get("success"))
        return {
            "success": True,
            "message": f"Stop requested for {len(running_names)} strategies",
            "stopped": success_count,
            "results": results,
        }

    def list_running_strategies(self) -> List[str]:
        with self._lock:
            return sorted(self._active.keys())

    def update_parameters(self, strategy_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Update parameters for a running strategy."""
        if not params:
            return {"success": False, "message": "No parameters provided"}

        resolved_name = self._resolve_running_name(strategy_name)
        with self._lock:
            running_state = self._active.get(resolved_name)

        if running_state is None:
            return {
                "success": False,
                "message": f"Strategy '{resolved_name}' is not running",
            }

        strategy = running_state.strategy
        old_values = {key: strategy.parameters.get(key) for key in params.keys()}

        if hasattr(strategy, "update_parameters"):
            strategy.update_parameters(params)
        else:
            strategy.parameters.update(params)

        return {
            "success": True,
            "message": f"Updated parameters for '{resolved_name}'",
            "changes": {key: {"old": old_values[key], "new": value} for key, value in params.items()},
            "parameters": strategy.parameters,
        }

    def get_strategy_status(self, strategy_name: str) -> Optional[Dict[str, Any]]:
        """
        Return status for one strategy (running or most recent historical state).
        """
        resolved_name: Optional[str] = None
        with self._lock:
            running_names = list(self._active.keys())
            history_names = list(self._history.keys())

        if strategy_name in running_names or strategy_name in history_names:
            resolved_name = strategy_name
        else:
            normalized = self._normalize(strategy_name)
            for name in running_names + history_names:
                if self._normalize(name) == normalized:
                    resolved_name = name
                    break
            if resolved_name is None:
                partial_hits = [
                    name
                    for name in running_names + history_names
                    if normalized in self._normalize(name)
                ]
                if len(partial_hits) == 1:
                    resolved_name = partial_hits[0]

        if resolved_name is None:
            return None

        with self._lock:
            running_state = self._active.get(resolved_name) or self._history.get(resolved_name)

        if running_state is None:
            return None

        strategy = running_state.strategy
        positions = []
        portfolio_value = None
        cash = None
        try:
            positions = [str(pos) for pos in strategy.get_positions()]
            portfolio_value = strategy.portfolio_value
            cash = strategy.cash
        except Exception:
            # Strategy may have fully shut down; return metadata anyway.
            pass

        return {
            "strategy": running_state.strategy_name,
            "mode": running_state.mode,
            "status": running_state.status,
            "started_at": running_state.started_at.isoformat(),
            "ended_at": running_state.ended_at.isoformat() if running_state.ended_at else None,
            "thread_alive": running_state.thread.is_alive(),
            "portfolio_value": portfolio_value,
            "cash": cash,
            "positions": positions,
            "parameters": strategy.parameters,
            "last_error": running_state.last_error,
        }

    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """Return status for all currently running strategies."""
        with self._lock:
            running_names = list(self._active.keys())
        return {
            name: self.get_strategy_status(name)
            for name in running_names
        }
