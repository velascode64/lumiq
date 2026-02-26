"""
FastAPI server for Lumiq core runtime.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

try:
    from .services.chat_service import ChatService
    from ..platform.runtime.app_runtime import CoreRuntime
except ImportError:
    from app.services.chat_service import ChatService
    from platform.runtime.app_runtime import CoreRuntime


logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    chat_id: int
    user_id: Optional[int] = None
    text: str


class ChatReply(BaseModel):
    text: str
    parse_mode: Optional[str] = None


class StartStrategyRequest(BaseModel):
    strategy_name: str
    mode: str = "paper"
    parameters: Optional[Dict[str, Any]] = None


class StopStrategyRequest(BaseModel):
    strategy_name: str
    timeout_seconds: float = Field(default=8.0, ge=0.1)


class UpdateStrategyParamsRequest(BaseModel):
    strategy_name: str
    params: Dict[str, Any]


def create_app(strategies_path: Optional[str] = None) -> FastAPI:
    runtime = CoreRuntime(strategies_path=strategies_path)
    chat = ChatService(runtime)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime.start_background()
        logger.info("Core runtime started")
        try:
            yield
        finally:
            runtime.stop_background()
            logger.info("Core runtime stopped")

    app = FastAPI(title="Lumiq Core API", version="0.1.0", lifespan=lifespan)
    app.state.runtime = runtime
    app.state.chat = chat

    @app.get("/health")
    def health() -> Dict[str, Any]:
        return {
            "ok": True,
            "strategies_running": runtime.orchestrator.list_running_strategies(),
            "alerts_enabled": runtime.alert_system is not None,
            "team_enabled": runtime.team is not None,
        }

    @app.post("/chat/message", response_model=ChatReply)
    def chat_message(req: ChatRequest) -> ChatReply:
        reply = chat.handle_text(req.chat_id, req.user_id or req.chat_id, req.text)
        return ChatReply(text=reply.text, parse_mode=reply.parse_mode)

    @app.get("/strategies")
    def list_strategies() -> Dict[str, Any]:
        return runtime.orchestrator.core.list_strategies()

    @app.get("/strategies/running")
    def list_running_strategies() -> Dict[str, Any]:
        return {"running": runtime.orchestrator.list_running_strategies()}

    @app.post("/strategies/start")
    def start_strategy(req: StartStrategyRequest) -> Dict[str, Any]:
        return runtime.orchestrator.start_strategy(
            strategy_name=req.strategy_name,
            parameters=req.parameters,
            mode=req.mode,
        )

    @app.post("/strategies/stop")
    def stop_strategy(req: StopStrategyRequest) -> Dict[str, Any]:
        try:
            return runtime.orchestrator.stop_strategy(req.strategy_name, timeout_seconds=req.timeout_seconds)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/strategies/kill")
    def kill_strategy(req: StopStrategyRequest) -> Dict[str, Any]:
        try:
            return runtime.orchestrator.kill_strategy(req.strategy_name)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/strategies/stop-all")
    def stop_all() -> Dict[str, Any]:
        return runtime.orchestrator.stop_all()

    @app.get("/strategies/status")
    def get_all_status() -> Dict[str, Any]:
        return runtime.orchestrator.get_all_status()

    @app.get("/strategies/status/{strategy_name}")
    def get_status(strategy_name: str) -> Dict[str, Any]:
        status = runtime.orchestrator.get_strategy_status(strategy_name)
        if not status:
            raise HTTPException(status_code=404, detail="Strategy status not found")
        return status

    @app.post("/strategies/set")
    def update_strategy_params(req: UpdateStrategyParamsRequest) -> Dict[str, Any]:
        return runtime.orchestrator.update_parameters(req.strategy_name, req.params)

    @app.get("/alerts/rules")
    def list_alert_rules(chat_id: Optional[int] = None) -> Dict[str, Any]:
        if runtime.alert_system is None:
            raise HTTPException(status_code=503, detail="Alert system not available")
        rules = runtime.alert_system.list_rules()
        if chat_id is not None:
            rules = [r for r in rules if int(r.get("chat_id") or 0) == int(chat_id)]
        return {"rules": rules}

    @app.post("/alerts/evaluate")
    def evaluate_alerts() -> Dict[str, Any]:
        if runtime.alert_system is None:
            raise HTTPException(status_code=503, detail="Alert system not available")
        return {"messages": runtime.alert_system.evaluate_rules()}

    return app
