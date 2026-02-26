"""FastAPI dependency placeholders for the reorganized app package."""
from typing import Any
from fastapi import Request

def get_runtime(request: Request) -> Any:
    return request.app.state.runtime

def get_chat_service(request: Request) -> Any:
    return request.app.state.chat
