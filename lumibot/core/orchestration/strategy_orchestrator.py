"""
Strategy orchestrator for running Lumibot live/paper strategies as subprocesses.

This design provides a real kill switch per strategy (SIGTERM/SIGKILL), which is
not possible with in-process Python threads.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import logging
import os
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Prevent lumibot.credentials from auto-spawning a hidden broker/stream on import.
os.environ.setdefault("TRADING_BROKER", "none")

from lumibot.strategies import Strategy

try:
    from .trading_core import TradingCore
except ImportError:
    from trading_core import TradingCore


logger = logging.getLogger(__name__)


@dataclass
class RunningStrategy:
    """In-memory state for one running strategy process."""

    strategy_name: str
    mode: str
    parameters: Dict[str, Any]
    process: subprocess.Popen[Any]
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: Optional[datetime] = None
    status: str = "running"
    last_error: Optional[str] = None
    exit_code: Optional[int] = None


class StrategyOrchestrator:
    """
    Runs and controls strategies concurrently from a single process.

    Each strategy is isolated in its own subprocess so stop/kill is enforceable.
    """

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
        self._worker_script = Path(__file__).resolve().parent / "strategy_process_worker.py"

        self.discovered_count = self.register_strategies_from_path(self.strategies_path)

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
            raise ValueError(f"Strategy '{requested_name}' not found. Available: {available}")
        raise ValueError(f"Strategy name '{requested_name}' is ambiguous. Matches: {partial_hits}")

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
        raise ValueError(f"Running strategy name '{requested_name}' is ambiguous. Matches: {partial_hits}")

    def _poll_processes(self) -> None:
        with self._lock:
            active_items = list(self._active.items())

        for name, state in active_items:
            rc = state.process.poll()
            if rc is None:
                continue
            state.exit_code = rc
            state.ended_at = datetime.now(timezone.utc)
            if state.status not in {"stopped", "killed"}:
                state.status = "stopped" if rc == 0 else "error"
                if rc != 0:
                    state.last_error = f"process exited with code {rc}"
            with self._lock:
                self._active.pop(name, None)
                self._history[name] = state

    def _spawn_strategy_process(
        self,
        strategy_name: str,
        parameters: Optional[Dict[str, Any]],
        mode: str,
    ) -> subprocess.Popen[Any]:
        env = os.environ.copy()
        cmd = [
            sys.executable,
            str(self._worker_script),
            "--strategy-name",
            strategy_name,
            "--mode",
            mode,
            "--strategies-path",
            str(self.strategies_path),
            "--broker-config-json",
            json.dumps(self.broker_config),
            "--params-json",
            json.dumps(parameters or {}),
        ]
        logger.info("Starting strategy process: %s (%s)", strategy_name, mode)
        return subprocess.Popen(cmd, env=env, cwd=str(Path(__file__).resolve().parent))

    def start_strategy(
        self,
        strategy_name: str,
        parameters: Optional[Dict[str, Any]] = None,
        mode: str = "paper",
    ) -> Dict[str, Any]:
        self._poll_processes()
        mode = mode.lower().strip()
        if mode not in {"paper", "live"}:
            raise ValueError("mode must be 'paper' or 'live'")

        resolved_name = self._resolve_strategy_name(strategy_name)
        with self._lock:
            if resolved_name in self._active:
                return {"success": False, "message": f"Strategy '{resolved_name}' is already running"}

        try:
            process = self._spawn_strategy_process(resolved_name, parameters, mode)
        except Exception as exc:
            return {
                "success": False,
                "message": f"Failed to initialize '{resolved_name}': {exc}",
                "strategy": resolved_name,
                "mode": mode,
            }

        state = RunningStrategy(
            strategy_name=resolved_name,
            mode=mode,
            parameters=(parameters or {}).copy(),
            process=process,
        )
        with self._lock:
            self._active[resolved_name] = state

        return {
            "success": True,
            "message": f"Started '{resolved_name}' in {mode} mode",
            "strategy": resolved_name,
            "mode": mode,
            "pid": process.pid,
            "parameters": state.parameters,
        }

    def stop_strategy(self, strategy_name: str, timeout_seconds: float = 8.0) -> Dict[str, Any]:
        """Graceful stop (SIGTERM) with forced kill fallback."""
        self._poll_processes()
        resolved_name = self._resolve_running_name(strategy_name)
        with self._lock:
            state = self._active.get(resolved_name)
        if state is None:
            return {"success": False, "message": f"Strategy '{resolved_name}' is not running"}

        proc = state.process
        if proc.poll() is not None:
            self._poll_processes()
            return {"success": True, "message": f"Strategy '{resolved_name}' already stopped"}

        state.status = "stopping"
        try:
            proc.terminate()
        except Exception as exc:
            state.last_error = str(exc)
            return {"success": False, "message": f"Failed to stop '{resolved_name}': {exc}"}

        try:
            proc.wait(timeout=timeout_seconds)
            state.status = "stopped"
            state.exit_code = proc.returncode
            state.ended_at = datetime.now(timezone.utc)
            with self._lock:
                self._active.pop(resolved_name, None)
                self._history[resolved_name] = state
            return {"success": True, "message": f"Stopped '{resolved_name}'", "exit_code": proc.returncode}
        except subprocess.TimeoutExpired:
            logger.warning("Strategy '%s' did not stop in %.1fs; forcing kill", resolved_name, timeout_seconds)
            return self.kill_strategy(resolved_name)

    def kill_strategy(self, strategy_name: str) -> Dict[str, Any]:
        """Immediate forced kill of a strategy process."""
        self._poll_processes()
        resolved_name = self._resolve_running_name(strategy_name)
        with self._lock:
            state = self._active.get(resolved_name)
        if state is None:
            return {"success": False, "message": f"Strategy '{resolved_name}' is not running"}

        proc = state.process
        if proc.poll() is not None:
            self._poll_processes()
            return {"success": True, "message": f"Strategy '{resolved_name}' already stopped"}

        state.status = "killing"
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception as exc:
            state.last_error = str(exc)
            return {"success": False, "message": f"Failed to kill '{resolved_name}': {exc}"}

        state.status = "killed"
        state.exit_code = proc.returncode
        state.ended_at = datetime.now(timezone.utc)
        with self._lock:
            self._active.pop(resolved_name, None)
            self._history[resolved_name] = state
        return {"success": True, "message": f"Killed '{resolved_name}'", "exit_code": proc.returncode}

    def stop_all(self) -> Dict[str, Any]:
        self._poll_processes()
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
        self._poll_processes()
        with self._lock:
            return sorted(self._active.keys())

    def update_parameters(self, strategy_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update parameters for a running strategy.

        Process-based mode cannot mutate a live strategy safely without IPC.
        """
        if not params:
            return {"success": False, "message": "No parameters provided"}

        self._poll_processes()
        resolved_name = self._resolve_running_name(strategy_name)
        with self._lock:
            state = self._active.get(resolved_name)
        if state is None:
            return {"success": False, "message": f"Strategy '{resolved_name}' is not running"}
        return {
            "success": False,
            "message": (
                f"Live parameter updates are not supported in process-based mode for '{resolved_name}'. "
                "Stop/start the strategy with new parameters."
            ),
            "strategy": resolved_name,
            "requested_params": params,
        }

    def get_strategy_status(self, strategy_name: str) -> Optional[Dict[str, Any]]:
        self._poll_processes()
        resolved_name: Optional[str] = None
        with self._lock:
            names = list(self._active.keys()) + list(self._history.keys())

        if strategy_name in names:
            resolved_name = strategy_name
        else:
            normalized = self._normalize(strategy_name)
            exact_map = {self._normalize(name): name for name in names}
            if normalized in exact_map:
                resolved_name = exact_map[normalized]
            else:
                partial_hits = [name for name in names if normalized in self._normalize(name)]
                if len(partial_hits) == 1:
                    resolved_name = partial_hits[0]

        if resolved_name is None:
            return None

        with self._lock:
            state = self._active.get(resolved_name) or self._history.get(resolved_name)
        if state is None:
            return None

        process_alive = state.process.poll() is None
        if state.status == "running" and not process_alive:
            self._poll_processes()
            process_alive = False

        return {
            "strategy": state.strategy_name,
            "mode": state.mode,
            "status": state.status,
            "started_at": state.started_at.isoformat(),
            "ended_at": state.ended_at.isoformat() if state.ended_at else None,
            "thread_alive": process_alive,  # kept for compatibility with existing formatting
            "process_alive": process_alive,
            "pid": state.process.pid,
            "portfolio_value": None,
            "cash": None,
            "positions": [],
            "parameters": state.parameters,
            "last_error": state.last_error,
            "exit_code": state.exit_code,
            "runner_type": "process",
        }

    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        self._poll_processes()
        with self._lock:
            running_names = list(self._active.keys())
        return {name: self.get_strategy_status(name) for name in running_names}
