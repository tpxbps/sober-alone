"""Workflow lifecycle routes for script creation."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.schemas.script_editor import (
    ForkRequest,
    ResumeWorkflowRequest,
    StartWorkflowRequest,
    UpdatePromptRequest,
    UpdateTitleRequest,
)
from app.db.models import EditorOperation
from app.db.session import AsyncSessionLocal
from app.script_editor.outline.contracts import OutlineAction, OutlineConflict
from app.script_editor.ownership import require_author_key_hash
from app.script_editor.services.operation_service import editor_operation_runner
from app.script_editor.services.workflow_service import (
    ScriptEditorWorkflowService,
    WorkflowAuthorizationError,
    WorkflowNotFoundError,
)

logger = logging.getLogger(__name__)

entry_router = APIRouter()
history_router = APIRouter()


@entry_router.post("/start", status_code=202)
async def start_workflow(
    request: StartWorkflowRequest,
    owner_key_hash: str = Depends(require_author_key_hash),
):
    """Start a new script-creation workflow."""
    try:
        return await editor_operation_runner.queue_start(request, owner_key_hash)
    except Exception as error:
        logger.error("Failed to start workflow: %s", error, exc_info=True)
        raise HTTPException(status_code=500, detail=f"工作流启动失败: {error}") from error


@entry_router.get("/{thread_id}/state")
async def get_workflow_state(
    thread_id: str, owner_key_hash: str = Depends(require_author_key_hash)
):
    """Return the current workflow state."""
    try:
        await editor_operation_runner.authorize(thread_id, owner_key_hash)
        service = ScriptEditorWorkflowService()
        from app.script_editor.outline.runtime import projection, workflow_response

        response = await workflow_response(service, thread_id)

        response["outline_progress"] = await projection(
            thread_id, response["state"].get("outline_session")
        )
        return response
    except WorkflowNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except WorkflowAuthorizationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Exception as error:
        logger.error("Failed to get state: %s", error)
        raise HTTPException(status_code=500, detail=str(error)) from error


@entry_router.post("/{thread_id}/resume", status_code=202)
async def resume_workflow(
    thread_id: str,
    request: ResumeWorkflowRequest,
    owner_key_hash: str = Depends(require_author_key_hash),
):
    """Resume a workflow from its current interrupt."""
    try:
        return await editor_operation_runner.queue_resume(thread_id, request, owner_key_hash)
    except WorkflowNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except WorkflowAuthorizationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.error("Failed to resume workflow: %s", error, exc_info=True)
        raise HTTPException(status_code=500, detail=f"工作流恢复失败: {error}") from error


@entry_router.get("/{thread_id}/operations/{operation_id}")
async def get_operation(
    thread_id: str,
    operation_id: str,
    owner_key_hash: str = Depends(require_author_key_hash),
):
    try:
        return await editor_operation_runner.get(thread_id, operation_id, owner_key_hash)
    except WorkflowNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except WorkflowAuthorizationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@entry_router.put("/{thread_id}/prompt/{step}")
async def update_prompt(
    thread_id: str,
    step: str,
    request: UpdatePromptRequest,
    owner_key_hash: str = Depends(require_author_key_hash),
):
    """Update the prompt for a workflow step."""
    try:
        service = ScriptEditorWorkflowService()
        await editor_operation_runner.authorize(thread_id, owner_key_hash)
        return await service.update_prompt(thread_id, step, request.prompt)
    except WorkflowAuthorizationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@entry_router.put("/{thread_id}/title")
async def update_title(
    thread_id: str,
    request: UpdateTitleRequest,
    owner_key_hash: str = Depends(require_author_key_hash),
):
    """Update the generated script title."""
    try:
        service = ScriptEditorWorkflowService()
        await editor_operation_runner.authorize(thread_id, owner_key_hash)
        return await service.update_title(thread_id, request.script_title)
    except WorkflowAuthorizationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@entry_router.get("/prompts/defaults")
async def get_default_prompts():
    """Return the default prompts for every workflow step."""
    return ScriptEditorWorkflowService.get_defaults()


@entry_router.get("/steps/info")
async def get_steps_info():
    """Return labels, ordering, and confirmation metadata for workflow steps."""
    return ScriptEditorWorkflowService.get_steps()


@history_router.get("/{thread_id}/history")
async def get_workflow_history(
    thread_id: str, owner_key_hash: str = Depends(require_author_key_hash)
):
    """Return checkpoints in reverse chronological order."""
    try:
        service = ScriptEditorWorkflowService()
        await editor_operation_runner.authorize(thread_id, owner_key_hash)
        return await service.get_history(thread_id)
    except WorkflowAuthorizationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Exception as error:
        logger.error("Failed to get history: %s", error)
        raise HTTPException(status_code=500, detail=str(error)) from error


@history_router.get("/{thread_id}/checkpoint/{checkpoint_id}")
async def get_checkpoint_state(
    thread_id: str,
    checkpoint_id: str,
    owner_key_hash: str = Depends(require_author_key_hash),
):
    """Return a read-only checkpoint state."""
    try:
        service = ScriptEditorWorkflowService()
        await editor_operation_runner.authorize(thread_id, owner_key_hash)
        return await service.get_checkpoint(thread_id, checkpoint_id)
    except WorkflowNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except WorkflowAuthorizationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Exception as error:
        logger.error("Failed to get checkpoint: %s", error)
        raise HTTPException(status_code=500, detail=str(error)) from error


@history_router.post("/{thread_id}/fork")
async def fork_from_checkpoint(
    thread_id: str,
    request: ForkRequest,
    owner_key_hash: str = Depends(require_author_key_hash),
):
    """Fork a workflow from a historical checkpoint."""
    try:
        service = ScriptEditorWorkflowService()
        async with editor_operation_runner.command_lock(thread_id):
            await editor_operation_runner.authorize(thread_id, owner_key_hash)
            async with AsyncSessionLocal() as db:
                active = await db.scalar(
                    select(EditorOperation).where(
                        EditorOperation.thread_id == thread_id,
                        EditorOperation.status.in_(("queued", "running")),
                    )
                )
            if active:
                raise OutlineConflict("当前创作尚未结束，请先暂停再回退")
            target = await service._get_snapshot(service.config(thread_id, request.checkpoint_id))
            session = target.values.get("outline_session") or {}
            if (
                session
                and target.values.get("current_step") != "init"
                and session.get("status") not in {"ready", "needs_revision"}
            ):
                raise OutlineConflict(
                    "共创过程请使用回答旁的“从这里修改”，阶段回退可选择已完成的大纲"
                )
            from app.script_editor.outline.actions import sync_review_fork

            result = await service.fork(thread_id, request.checkpoint_id, request.state_updates)
            return await sync_review_fork(service, thread_id, result)
    except OutlineConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except WorkflowNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except WorkflowAuthorizationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Exception as error:
        logger.error("Failed to fork: %s", error, exc_info=True)
        raise HTTPException(status_code=500, detail=f"分叉失败: {error}") from error


@entry_router.post("/{thread_id}/outline/actions", status_code=202)
async def outline_action(
    thread_id: str,
    request: OutlineAction,
    owner_key_hash: str = Depends(require_author_key_hash),
):
    from app.script_editor.outline.actions import queue_action

    try:
        return await queue_action(editor_operation_runner, thread_id, request, owner_key_hash)
    except WorkflowNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except WorkflowAuthorizationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except OutlineConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
