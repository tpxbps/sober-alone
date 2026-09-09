"""Compatibility facade for LangGraph save and asset nodes."""

from app.core.config import settings
from app.script_editor.asset_generation.progress import (
    get_asset_progress,
    register_script_thread,
)
from app.script_editor.asset_generation.service import AssetGenerationService
from app.script_editor.repositories.script_repository import ScriptRepository
from app.script_editor.state import ScriptGenState

_asset_service = AssetGenerationService()


async def save_to_database(state: ScriptGenState) -> dict:
    from app.script_editor.nodes.quality_check import quality_approved

    if not quality_approved(state):
        return {
            "current_step": "save_to_database",
            "error_message": "质量报告缺失或已失效，请返回游戏数据重新检查",
        }
    return await ScriptRepository.save_generated_script(state)


async def generate_assets(state: ScriptGenState) -> dict:
    return await _asset_service.generate(state)


async def retry_single_asset(script_id: str, task_id: str, state: ScriptGenState):
    return await _asset_service.retry(script_id, task_id, state)


__all__ = [
    "generate_assets",
    "get_asset_progress",
    "register_script_thread",
    "retry_single_asset",
    "save_to_database",
    "settings",
]
