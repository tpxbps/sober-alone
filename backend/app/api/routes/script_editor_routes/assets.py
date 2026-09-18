"""Asset/conversion progress and retry routes."""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.schemas.script_editor import ResumeWorkflowRequest
from app.core.inference import raise_for_inference_recovery
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


async def _persisted_progress(thread_id: str, kind: str):
    from sqlalchemy import select

    from app.db.models import EditorOperation
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        operation = await db.scalar(
            select(EditorOperation)
            .where(EditorOperation.thread_id == thread_id)
            .order_by(EditorOperation.created_at.desc())
            .limit(1)
        )
        return (operation.progress or {}).get(kind) if operation else None


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
        progress = (
            get_asset_progress(script_id)
            or await _persisted_progress(thread_id, "asset_progress")
            or snapshot.values.get("asset_progress")
        )
        return {"success": True, "progress": progress}
    except Exception as error:
        raise_for_inference_recovery(error)
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
        progress = (
            get_convert_progress(script_id)
            or await _persisted_progress(thread_id, "convert_progress")
            or snapshot.values.get("convert_progress")
        )
        return {"success": True, "progress": progress}
    except Exception as error:
        raise_for_inference_recovery(error)
        logger.error("Failed to get conversion progress: %s", error)
        raise HTTPException(status_code=500, detail=str(error)) from error


@operation_router.post("/{thread_id}/retry-asset/{task_id}", status_code=202)
async def retry_asset_task(
    thread_id: str,
    task_id: str,
    owner_key_hash: str = Depends(require_author_key_hash),
):
    """Legacy URL now queues the same durable, single-task retry as the workbench."""
    await _authorize_thread(thread_id, owner_key_hash)
    try:
        return await editor_operation_runner.queue_resume(
            thread_id,
            ResumeWorkflowRequest(action="retry_asset", asset_task_id=task_id),
            owner_key_hash,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@operation_router.post("/{thread_id}/retry-convert/{task_id}", status_code=202)
async def retry_convert_task(
    thread_id: str,
    task_id: str,
    owner_key_hash: str = Depends(require_author_key_hash),
):
    """Backward-compatible entry point that safely reruns the full conversion.

    Conversion tasks contribute to one normalized state object, so replaying one
    task without rebuilding the aggregate can report success while retaining old
    fallback data. New clients use the normal ``resume(retry_failed)`` operation.
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
            ResumeWorkflowRequest(action="retry_failed"),
            owner_key_hash,
        )
    except HTTPException:
        raise
    except Exception as error:
        raise_for_inference_recovery(error)
        logger.error("Retry conversion failed: %s", error, exc_info=True)
        raise HTTPException(status_code=500, detail=str(error)) from error


@stream_router.get("/{thread_id}/progress-stream")
async def progress_stream(
    thread_id: str,
    owner_key_hash: str = Depends(require_author_key_hash),
    operation_id: str | None = None,
):
    """Stream conversion and asset progress snapshots over SSE."""
    from app.script_editor.services.progress_bus import subscribe, unsubscribe

    try:
        await editor_operation_runner.authorize(thread_id, owner_key_hash)
    except WorkflowNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except WorkflowAuthorizationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    queue = subscribe(thread_id)

    async def event_generator():
        try:
            yield _sse({"type": "connected"})
            from app.script_editor.outline.runtime import projection
            from app.script_editor.services.workflow_service import ScriptEditorWorkflowService

            snapshot = await ScriptEditorWorkflowService()._get_snapshot(
                ScriptEditorWorkflowService.config(thread_id)
            )
            outline = await projection(thread_id, snapshot.values.get("outline_session"))
            if outline:
                yield _sse({"type": "outline_snapshot", "data": outline})

            try:
                script_id = await _script_id_for_thread(thread_id)
                if script_id:
                    from app.script_editor.nodes.convert import get_convert_progress
                    from app.script_editor.nodes.save import get_asset_progress

                    convert_progress = (
                        get_convert_progress(script_id)
                        or await _persisted_progress(thread_id, "convert_progress")
                        or snapshot.values.get("convert_progress")
                    )
                    if convert_progress:
                        yield _sse({"type": "convert_progress", "data": convert_progress})

                    asset_progress = (
                        get_asset_progress(script_id)
                        or await _persisted_progress(thread_id, "asset_progress")
                        or snapshot.values.get("asset_progress")
                    )
                    if asset_progress:
                        yield _sse({"type": "asset_progress", "data": asset_progress})
            except Exception:
                pass

            if operation_id:
                operation = await editor_operation_runner.get(
                    thread_id, operation_id, owner_key_hash
                )
                progress = operation.get("progress", {}).get("workflow", {})
                finished = operation["operation_status"] not in {"queued", "running"}
                yield _sse(
                    {
                        "type": "workflow_progress",
                        "data": {
                            **progress,
                            "operation_id": operation_id,
                            "current_step": operation.get("current_step", ""),
                            "finished": finished,
                            "outcome": operation["operation_status"],
                        },
                    }
                )
                if finished:
                    yield _sse({"type": "done", "data": {"operation_id": operation_id}})
                    return

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield _sse(event)
                    data = event.get("data")
                    if (
                        event.get("type") == "workflow_progress"
                        and isinstance(data, dict)
                        and data.get("finished")
                        and (not operation_id or data.get("operation_id") == operation_id)
                    ):
                        yield _sse({"type": "done"})
                        break
                except TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            unsubscribe(thread_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
