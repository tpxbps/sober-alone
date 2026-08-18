"""Thread-safe asset-generation progress facade."""

from app.script_editor.services.progress_registry import asset_progress_registry


def register_script_thread(script_id: str, thread_id: str):
    """由 API 层调用，注册 script_id → thread_id 映射"""
    asset_progress_registry.register_thread(script_id, thread_id)


def _init_asset_progress(script_id: str, phases: list[dict]):
    """初始化任务树，所有任务为 pending 状态"""
    asset_progress_registry.init(script_id, phases)
    _publish_asset_progress(script_id)


def _update_task_status(script_id: str, task_id: str, status: str, reason: str = ""):
    """更新单个任务状态"""
    asset_progress_registry.update_task(script_id, task_id, status, reason)
    _publish_asset_progress(script_id)


def _mark_progress_complete(script_id: str):
    """标记所有进度为完成"""
    asset_progress_registry.mark_complete(script_id)
    _publish_asset_progress(script_id)


def get_asset_progress(script_id: str) -> dict | None:
    """获取资产生成进度"""
    return asset_progress_registry.snapshot(script_id)


def _publish_asset_progress(script_id: str):
    """通过 SSE 发布 asset 进度"""
    asset_progress_registry.publish(script_id)
