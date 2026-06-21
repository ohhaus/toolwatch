"""Top-level API router composition."""

from fastapi import APIRouter

from toolwatch.api.health import router as health_router
from toolwatch.api.sessions import router as sessions_router
from toolwatch.api.tool_calls import router as tool_calls_router
from toolwatch.api.tools import router as tools_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(tools_router)
api_router.include_router(sessions_router)
api_router.include_router(tool_calls_router)
