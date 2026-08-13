"""Workflow lifecycle routes for script creation."""

import logging

from fastapi import APIRouter, HTTPException

from app.api.schemas.script_editor import (
    ForkRequest,
    ResumeWorkflowRequest,
    StartWorkflowRequest,
    UpdatePromptRequest,
    UpdateTitleRequest,
)
from app.script_editor.services.workflow_service import (
    ScriptEditorWorkflowService,
    WorkflowNotFoundError,
)

logger = logging.getLogger(__name__)

entry_router = APIRouter()
history_router = APIRouter()


@entry_router.post("/start")
async def start_workflow(request: StartWorkflowRequest):
    """Start a new script-creation workflow."""
    try:
        return await ScriptEditorWorkflowService().start(request)
    except Exception as error:
        logger.error("Failed to start workflow: %s", error, exc_info=True)
        raise HTTPException(status_code=500, detail=f"工作流启动失败: {error}") from error


@entry_router.get("/{thread_id}/state")
async def get_workflow_state(thread_id: str):
    """Return the current workflow state."""
    try:
        return ScriptEditorWorkflowService().get_state(thread_id)
    except WorkflowNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        logger.error("Failed to get state: %s", error)
        raise HTTPException(status_code=500, detail=str(error)) from error


@entry_router.post("/{thread_id}/resume")
async def resume_workflow(thread_id: str, request: ResumeWorkflowRequest):
    """Resume a workflow from its current interrupt."""
    try:
        return await ScriptEditorWorkflowService().resume(thread_id, request)
    except Exception as error:
        logger.error("Failed to resume workflow: %s", error, exc_info=True)
        raise HTTPException(status_code=500, detail=f"工作流恢复失败: {error}") from error


@entry_router.put("/{thread_id}/prompt/{step}")
async def update_prompt(thread_id: str, step: str, request: UpdatePromptRequest):
    """Update the prompt for a workflow step."""
    try:
        return ScriptEditorWorkflowService().update_prompt(thread_id, step, request.prompt)
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@entry_router.put("/{thread_id}/title")
async def update_title(thread_id: str, request: UpdateTitleRequest):
    """Update the generated script title."""
    try:
        return ScriptEditorWorkflowService().update_title(thread_id, request.script_title)
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
async def get_workflow_history(thread_id: str):
    """Return checkpoints in reverse chronological order."""
    try:
        return ScriptEditorWorkflowService().get_history(thread_id)
    except Exception as error:
        logger.error("Failed to get history: %s", error)
        raise HTTPException(status_code=500, detail=str(error)) from error


@history_router.get("/{thread_id}/checkpoint/{checkpoint_id}")
async def get_checkpoint_state(thread_id: str, checkpoint_id: str):
    """Return a read-only checkpoint state."""
    try:
        return ScriptEditorWorkflowService().get_checkpoint(thread_id, checkpoint_id)
    except WorkflowNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        logger.error("Failed to get checkpoint: %s", error)
        raise HTTPException(status_code=500, detail=str(error)) from error


@history_router.post("/{thread_id}/fork")
async def fork_from_checkpoint(thread_id: str, request: ForkRequest):
    """Fork a workflow from a historical checkpoint."""
    try:
        return await ScriptEditorWorkflowService().fork(
            thread_id, request.checkpoint_id, request.state_updates
        )
    except WorkflowNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        logger.error("Failed to fork: %s", error, exc_info=True)
        raise HTTPException(status_code=500, detail=f"分叉失败: {error}") from error
