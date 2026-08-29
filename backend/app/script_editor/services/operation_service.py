"""Durable background execution for long-running editor graph operations."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.api.schemas.script_editor import ResumeWorkflowRequest, StartWorkflowRequest
from app.db.models import EditorOperation, EditorWorkflow
from app.db.session import AsyncSessionLocal
from app.script_editor.ownership import owner_hash_matches
from app.script_editor.services.workflow_service import (
    ScriptEditorWorkflowService,
    WorkflowAuthorizationError,
    WorkflowNotFoundError,
)

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("queued", "running")


class EditorOperationRunner:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    async def queue_start(
        self, request: StartWorkflowRequest, owner_key_hash: str
    ) -> dict[str, Any]:
        thread_id = str(uuid.uuid4())
        return await self._create(
            thread_id=thread_id,
            owner_key_hash=owner_key_hash,
            workflow_mode="create",
            kind="start",
            target_step="generate_outline",
            payload=request.model_dump(),
        )

    async def queue_edit(
        self,
        *,
        initial_state: dict[str, Any],
        owner_key_hash: str,
        script_id: str,
    ) -> dict[str, Any]:
        thread_id = str(uuid.uuid4())
        payload = dict(initial_state)
        payload.pop("owner_key_hash", None)
        return await self._create(
            thread_id=thread_id,
            owner_key_hash=owner_key_hash,
            workflow_mode="edit",
            kind="edit",
            target_step="review_game_data",
            payload=payload,
            script_id=script_id,
        )

    async def queue_resume(
        self, thread_id: str, request: ResumeWorkflowRequest, owner_key_hash: str
    ) -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            workflow = await db.get(EditorWorkflow, thread_id)
            if not workflow:
                raise WorkflowNotFoundError("工作流不存在")
            if not owner_hash_matches(workflow.owner_key_hash, owner_key_hash):
                raise WorkflowAuthorizationError("无权访问该工作流")
            active = await db.scalar(
                select(EditorOperation).where(
                    EditorOperation.thread_id == thread_id,
                    EditorOperation.status.in_(ACTIVE_STATUSES),
                )
            )
            if active:
                return self._accepted(active)
            operation = EditorOperation(
                operation_id=str(uuid.uuid4()),
                thread_id=thread_id,
                kind="resume",
                target_step=workflow.current_step,
                request_payload=request.model_dump(exclude_none=True),
                progress={"message": "等待后台执行"},
            )
            workflow.status = "running"
            workflow.updated_at = datetime.now()
            db.add(operation)
            await db.commit()
            self._schedule(operation.operation_id)
            return self._accepted(operation)

    async def _create(
        self,
        *,
        thread_id: str,
        owner_key_hash: str,
        workflow_mode: str,
        kind: str,
        target_step: str,
        payload: dict[str, Any],
        script_id: str | None = None,
    ) -> dict[str, Any]:
        operation = EditorOperation(
            operation_id=str(uuid.uuid4()),
            thread_id=thread_id,
            kind=kind,
            target_step=target_step,
            request_payload=payload,
            progress={"message": "等待后台执行"},
        )
        workflow = EditorWorkflow(
            thread_id=thread_id,
            owner_key_hash=owner_key_hash,
            workflow_mode=workflow_mode,
            script_id=script_id,
            current_step=target_step,
            status="running",
        )
        async with AsyncSessionLocal() as db:
            db.add(workflow)
            db.add(operation)
            await db.commit()
        self._schedule(operation.operation_id)
        return self._accepted(operation)

    @staticmethod
    def _accepted(operation: EditorOperation) -> dict[str, Any]:
        return {
            "success": True,
            "thread_id": operation.thread_id,
            "operation_id": operation.operation_id,
            "operation_status": operation.status,
            "target_step": operation.target_step,
            "progress": operation.progress,
        }

    def _schedule(self, operation_id: str) -> None:
        task = asyncio.create_task(self._run(operation_id))
        self._tasks[operation_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(operation_id, None))

    async def recover_pending(self) -> None:
        try:
            async with AsyncSessionLocal() as db:
                pending = list(
                    await db.scalars(
                        select(EditorOperation).where(EditorOperation.status.in_(ACTIVE_STATUSES))
                    )
                )
                for operation in pending:
                    operation.status = "queued"
                    operation.progress = {"message": "服务重启后恢复执行"}
                await db.commit()
        except OperationalError:
            # Keeps isolated lifespan tests/injected engines independent. Normal startup
            # has already passed ensure_database_ready against the same configured DB.
            logger.warning("Editor operation table unavailable; recovery skipped")
            return
        for operation in pending:
            self._schedule(operation.operation_id)

    async def shutdown(self) -> None:
        # Operations are durable. Cancelling only releases process tasks; startup reclaims them.
        for task in tuple(self._tasks.values()):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    async def get(self, thread_id: str, operation_id: str, owner_key_hash: str) -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            workflow = await db.get(EditorWorkflow, thread_id)
            operation = await db.get(EditorOperation, operation_id)
            if not workflow or not operation or operation.thread_id != thread_id:
                raise WorkflowNotFoundError("操作不存在")
            if not owner_hash_matches(workflow.owner_key_hash, owner_key_hash):
                raise WorkflowAuthorizationError("无权访问该工作流")
            response = self._accepted(operation)
            if operation.error_message:
                response["error_message"] = operation.error_message
        if response["operation_status"] == "complete":
            live = await ScriptEditorWorkflowService().get_state(thread_id)
            response.update(live)
            state = live.get("state", {})
            response["script_id"] = state.get("script_id", "")
            response["script_title"] = state.get("script_title", "")
            response["operation_id"] = operation_id
            response["operation_status"] = "complete"
        return response

    async def authorize(self, thread_id: str, owner_key_hash: str) -> EditorWorkflow:
        async with AsyncSessionLocal() as db:
            workflow = await db.get(EditorWorkflow, thread_id)
            if not workflow:
                raise WorkflowNotFoundError("工作流不存在")
            if not owner_hash_matches(workflow.owner_key_hash, owner_key_hash):
                raise WorkflowAuthorizationError("无权访问该工作流")
            return workflow

    async def _run(self, operation_id: str) -> None:
        try:
            async with AsyncSessionLocal() as db:
                operation = await db.get(EditorOperation, operation_id)
                if not operation:
                    return
                workflow = await db.get(EditorWorkflow, operation.thread_id)
                if not workflow:
                    return
                operation.status = "running"
                operation.progress = {"message": "后台执行中"}
                await db.commit()
                kind = operation.kind
                target_step = operation.target_step
                payload = dict(operation.request_payload or {})
                thread_id = operation.thread_id
                owner_key_hash = workflow.owner_key_hash

            service = ScriptEditorWorkflowService()
            existing = await service._get_snapshot(service.config(thread_id))
            existing_interrupt = service.extract_interrupt(existing) if existing.values else None
            if kind == "start":
                if existing_interrupt:
                    result = service._live_response(thread_id, existing)
                elif existing.values:
                    await service.graph.ainvoke(None, service.config(thread_id))
                    result = service._live_response(
                        thread_id, await service._get_snapshot(service.config(thread_id))
                    )
                else:
                    result = await service.start(
                        StartWorkflowRequest.model_validate(payload), owner_key_hash, thread_id
                    )
            elif kind == "edit":
                if existing_interrupt:
                    result = service._live_response(thread_id, existing)
                elif existing.values:
                    await service.graph.ainvoke(None, service.config(thread_id))
                else:
                    payload["owner_key_hash"] = owner_key_hash
                    await service.graph.ainvoke(payload, service.config(thread_id))
                if not existing_interrupt:
                    result = service._live_response(
                        thread_id, await service._get_snapshot(service.config(thread_id))
                    )
            else:
                if existing_interrupt and existing_interrupt.get("step") != target_step:
                    result = service._live_response(thread_id, existing)
                elif existing.values and existing_interrupt is None:
                    await service.graph.ainvoke(None, service.config(thread_id))
                    result = service._live_response(
                        thread_id, await service._get_snapshot(service.config(thread_id))
                    )
                else:
                    result = await service.resume(
                        thread_id, ResumeWorkflowRequest.model_validate(payload)
                    )

            async with AsyncSessionLocal() as db:
                operation = await db.get(EditorOperation, operation_id)
                workflow = await db.get(EditorWorkflow, thread_id)
                if not operation or not workflow:
                    return
                operation.status = "complete"
                operation.progress = {"message": "执行完成", "percent": 100}
                workflow.current_step = result.get("current_step", workflow.current_step)
                workflow.script_id = result.get("script_id") or workflow.script_id
                workflow.status = "complete" if result.get("is_complete") else "idle"
                workflow.updated_at = datetime.now()
                await db.commit()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.exception("Editor operation %s failed", operation_id)
            async with AsyncSessionLocal() as db:
                operation = await db.get(EditorOperation, operation_id)
                if operation:
                    operation.status = "failed"
                    operation.error_message = str(error)
                    operation.progress = {"message": "执行失败"}
                    workflow = await db.get(EditorWorkflow, operation.thread_id)
                    if workflow:
                        workflow.status = "failed"
                    await db.commit()


editor_operation_runner = EditorOperationRunner()
