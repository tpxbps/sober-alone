"""Compatibility facade for the script editor API routes."""

from fastapi import APIRouter

from app.api.routes.script_editor_routes.assets import operation_router, stream_router
from app.api.routes.script_editor_routes.chat import router as chat_router
from app.api.routes.script_editor_routes.scripts import delete_script
from app.api.routes.script_editor_routes.scripts import router as scripts_router
from app.api.routes.script_editor_routes.workflow import entry_router, history_router

router = APIRouter(prefix="/script-editor", tags=["script-editor"])

# Preserve the historical registration order so the generated OpenAPI document stays stable.
router.include_router(entry_router)
router.include_router(scripts_router)
router.include_router(operation_router)
router.include_router(history_router)
router.include_router(chat_router)
router.include_router(stream_router)

__all__ = ["delete_script", "router"]
