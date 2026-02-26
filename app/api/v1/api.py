"""Router registry for v1 API (transitional wrappers)."""
from fastapi import APIRouter
from .endpoints import health, chat

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(chat.router)
