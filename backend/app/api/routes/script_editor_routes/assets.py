"""Asset/conversion progress and retry routes."""

import asyncio
import json
import logging
from typing import cast

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.script_editor.graph import get_script_gen_graph
from app.script_editor.services.workflow_service import ScriptEditorWorkflowService

logger = logging.getLogger(__name__)

operation_router = APIRouter()
stream_router = APIRouter()


def _script_id_for_thread(thread_id: str) -> str:
    graph = get_script_gen_graph()
    state_snapshot = graph.get_state(ScriptEditorWorkflowService.config(thread_id))
    return state_snapshot.values.get("script_id", "")


def _task_status(progress: dict | None, task_id: str) -> str:
    if progress:
        for phase in progress.get("phases", []):
            for task in phase.get("tasks", []):
                if task["id"] == task_id:
                    return task["status"]
    return "unknown"


@operation_router.get("/{thread_id}/asset-progress")
async def get_asset_progress_endpoint(thread_id: str):
    """Poll asset-generation progress."""
    try:
        script_id = _script_id_for_thread(thread_id)
        if not script_id:
            return {"success": True, "progress": None}

        from app.script_editor.nodes.save import get_asset_progress

        return {"success": True, "progress": get_asset_progress(script_id)}
    except Exception as error:
        logger.error("Failed to get asset progress: %s", error)
        raise HTTPException(status_code=500, detail=str(error)) from error


@operation_router.get("/{thread_id}/convert-progress")
async def get_convert_progress_endpoint(thread_id: str):
    """Poll structured-conversion progress."""
    try:
        script_id = _script_id_for_thread(thread_id)
        if not script_id:
            return {"success": True, "progress": None}

        from app.script_editor.nodes.convert import get_convert_progress

        return {"success": True, "progress": get_convert_progress(script_id)}
    except Exception as error:
        logger.error("Failed to get conversion progress: %s", error)
        raise HTTPException(status_code=500, detail=str(error)) from error


@operation_router.post("/{thread_id}/retry-asset/{task_id}")
async def retry_asset_task(thread_id: str, task_id: str):
    """Retry one failed asset-generation task."""
    try:
        graph = get_script_gen_graph()
        state_snapshot = graph.get_state(ScriptEditorWorkflowService.config(thread_id))
        script_id = state_snapshot.values.get("script_id", "")
        if not script_id:
            raise HTTPException(status_code=404, detail="工作流不存在")

        from app.script_editor.nodes.save import get_asset_progress, retry_single_asset
        from app.script_editor.state import ScriptGenState

        await retry_single_asset(script_id, task_id, cast(ScriptGenState, state_snapshot.values))
        status = _task_status(get_asset_progress(script_id), task_id)
        return {"success": True, "message": f"任务 {task_id} 重试完成", "task_status": status}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@operation_router.post("/{thread_id}/retry-convert/{task_id}")
async def retry_convert_task(thread_id: str, task_id: str):
    """Retry one failed structured-conversion task."""
    try:
        graph = get_script_gen_graph()
        state_snapshot = graph.get_state(ScriptEditorWorkflowService.config(thread_id))
        script_id = state_snapshot.values.get("script_id", "")
        if not script_id:
            raise HTTPException(status_code=404, detail="工作流不存在")

        ScriptEditorWorkflowService.register_script_thread(script_id, thread_id)

        from app.script_editor.nodes.convert import get_convert_progress, retry_single_convert
        from app.script_editor.state import ScriptGenState

        await retry_single_convert(script_id, task_id, cast(ScriptGenState, state_snapshot.values))
        status = _task_status(get_convert_progress(script_id), task_id)
        return {
            "success": True,
            "message": f"转换任务 {task_id} 重试完成",
            "task_status": status,
        }
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Retry conversion failed: %s", error, exc_info=True)
        raise HTTPException(status_code=500, detail=str(error)) from error


@stream_router.get("/{thread_id}/progress-stream")
async def progress_stream(thread_id: str):
    """Stream conversion and asset progress snapshots over SSE."""
    from app.script_editor.services.progress_bus import subscribe, unsubscribe

    queue = subscribe(thread_id)

    async def event_generator():
        try:
            yield _sse({"type": "connected"})

            try:
                script_id = _script_id_for_thread(thread_id)
                if script_id:
                    from app.script_editor.nodes.convert import get_convert_progress
                    from app.script_editor.nodes.save import get_asset_progress

                    convert_progress = get_convert_progress(script_id)
                    if convert_progress:
                        yield _sse({"type": "convert_progress", "data": convert_progress})

                    asset_progress = get_asset_progress(script_id)
                    if asset_progress:
                        yield _sse({"type": "asset_progress", "data": asset_progress})
            except Exception:
                pass

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield _sse(event)
                    data = event.get("data")
                    if isinstance(data, dict) and data.get("isComplete"):
                        yield _sse({"type": "done"})
                        break
                except TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            unsubscribe(thread_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
