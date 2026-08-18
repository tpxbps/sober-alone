"""API routes initialization"""

from fastapi import APIRouter

from app.api.routes.game import router as game_router

# 组合所有路由
api_router = APIRouter()

# 注册子路由
api_router.include_router(game_router, prefix="/game")

__all__ = ["api_router"]
