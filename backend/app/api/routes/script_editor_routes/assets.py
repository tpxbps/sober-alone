"""Asset/conversion progress and retry routes."""

import asyncio
import json
import logging
from typing import cast

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.schemas.script_editor import ResumeWorkflowRequest
from app.script_editor.graph import get_script_gen_graph
from app.script_editor.ownership import require_author_key_hash
from app.script_editor.services.operation_service import editor_operation_runner
from app.script_editor.services.workflow_service import (
    ScriptEditorWorkflowService,
    WorkflowAuthorizationError,
    WorkflowNotFoundError,
)

logger = logging.getLogger(__name__)

operation_router = APIRouter()
stream_router = APIRouter()


async def _script_id_for_thread(thread_id: str) -> str:
    graph = get_script_gen_graph()
    state_snapshot = await graph.aget_state(ScriptEditorWorkflowService.config(thread_id))
    return state_snapshot.values.get("script_id", "")


async def _authorize_thread(thread_id: str, owner_key_hash: str) -> None:
    try:
        await ScriptEditorWorkflowService().authorize(thread_id, owner_key_hash)
    except WorkflowNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except WorkflowAuthorizationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


def _task_status(progress: dict | None, task_id: str) -> str:
    if progress:
        for phase in progress.get("phases", []):
            for task in phase.get("tasks", []):
                if task["id"] == task_id:
                    return task["status"]
    return "unknown"


@operation_router.get("/{thread_id}/asset-progress")
async def get_asset_progress_endpoint(
    thread_id: str, owner_key_hash: str = Depends(require_author_key_hash)
):
    """Poll asset-generation progress."""
    try:
        await _authorize_thread(thread_id, owner_key_hash)
        script_id = await _script_id_for_thread(thread_id)
        if not script_id:
            return {"success": True, "progress": None}

        from app.script_editor.nodes.save import get_asset_progress

        graph = get_script_gen_graph()
        snapshot = await graph.aget_state(ScriptEditorWorkflowService.config(thread_id))
        progress = get_asset_progress(script_id) or snapshot.values.get("asset_progress")
        return {"success": True, "progress": progress}
    except Exception as error:
        logger.error("Failed to get asset progress: %s", error)
        raise HTTPException(status_code=500, detail=str(error)) from error


@operation_router.get("/{thread_id}/convert-progress")
async def get_convert_progress_endpoint(
    thread_id: str, owner_key_hash: str = Depends(require_author_key_hash)
):
    """Poll structured-conversion progress."""
    try:
        await _authorize_thread(thread_id, owner_key_hash)
        script_id = await _script_id_for_thread(thread_id)
        if not script_id:
            return {"success": True, "progress": None}

        from app.script_editor.nodes.convert import get_convert_progress

        graph = get_script_gen_graph()
        snapshot = await graph.aget_state(ScriptEditorWorkflowService.config(thread_id))
        progress = get_convert_progress(script_id) or snapshot.values.get("convert_progress")
        return {"success": True, "progress": progress}
    except Exception as error:
        logger.error("Failed to get conversion progress: %s", error)
        raise HTTPException(status_code=500, detail=str(error)) from error


@operation_router.post("/{thread_id}/retry-asset/{task_id}")
async def retry_asset_task(
    thread_id: str,
    task_id: str,
    owner_key_hash: str = Depends(require_author_key_hash),
):
    """Retry one failed asset-generation task."""
    try:
        await _authorize_thread(thread_id, owner_key_hash)
        graph = get_script_gen_graph()
        state_snapshot = await graph.aget_state(ScriptEditorWorkflowService.config(thread_id))
        script_id = state_snapshot.values.get("script_id", "")
        if not script_id:
            raise HTTPException(status_code=404, detail="工作流不存在")

        from app.script_editor.nodes.save import get_asset_progress, retry_single_asset
        from app.script_editor.state import ScriptGenState

        await retry_single_asset(script_id, task_id, cast(ScriptGenState, state_snapshot.values))
        progress = get_asset_progress(script_id)
        await graph.aupdate_state(
            ScriptEditorWorkflowService.config(thread_id),
            {"asset_progress": progress or {}},
        )
        status = _task_status(progress, task_id)
        return {"success": True, "message": f"任务 {task_id} 重试完成", "task_status": status}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@operation_router.post("/{thread_id}/retry-convert/{task_id}", status_code=202)
async def retry_convert_task(
    thread_id: str,
    task_id: str,
    owner_key_hash: str = Depends(require_author_key_hash),
):
    """Backward-compatible entry point that safely reruns the full conversion.

    Conversion tasks contribute to one normalized state object, so replaying one
    task without rebuilding the aggregate can report success while retaining old
    fallback data. New clients use the normal ``resume(regenerate)`` operation.
    """
    try:
        await _authorize_thread(thread_id, owner_key_hash)
        logger.info(
            "Deprecated conversion retry requested thread=%s task=%s; rerunning full conversion",
            thread_id,
            task_id,
        )
        return await editor_operation_runner.queue_resume(
            thread_id,
            ResumeWorkflowRequest(action="regenerate"),
            owner_key_hash,
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.error("Retry conversion failed: %s", error, exc_info=True)
        raise HTTPException(status_code=500, detail=str(error)) from error


@stream_router.get("/{thread_id}/progress-stream")
async def progress_stream(thread_id: str, owner_key_hash: str = Depends(require_author_key_hash)):
    """Stream conversion and asset progress snapshots over SSE."""
    from app.script_editor.services.progress_bus import subscribe, unsubscribe

    await _authorize_thread(thread_id, owner_key_hash)
    queue = subscribe(thread_id)

    async def event_generator():
        try:
            yield _sse({"type": "connected"})

            try:
                script_id = await _script_id_for_thread(thread_id)
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
