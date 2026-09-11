"""Transient streaming projection; checkpoints remain the committed source of truth."""

from __future__ import annotations

import time
import uuid
from contextvars import ContextVar
from copy import deepcopy

from sqlalchemy import select

from app.db.models import EditorOperation, EditorWorkflow
from app.db.session import AsyncSessionLocal
from app.script_editor.services.progress_bus import publish

current_runtime: ContextVar[OutlineRuntime | None] = ContextVar("outline_runtime", default=None)
live_runtimes: dict[str, OutlineRuntime] = {}


class OutlineRuntime:
    def __init__(
        self,
        thread_id: str,
        operation_id: str,
        progress: dict | None = None,
        operation_created_at: str = "",
    ):
        self.thread_id = thread_id
        self.operation_id = operation_id
        self.operation_created_at = operation_created_at or (progress or {}).get("outline", {}).get(
            "operation_created_at", ""
        )
        self.session: dict = {}
        self.live: dict | None = (progress or {}).get("outline", {}).get("live")
        self.seq = (progress or {}).get("outline", {}).get("seq", 0)
        self.saved_at = 0.0
        self.started_at = time.monotonic()
        self.calls = 0
        self.first_token_ms: int | None = None
        self.first_question_ms: int | None = None
        self.control: dict = {}
        self.error = ""
        self.answer: dict | None = None

    async def read_control(self) -> dict:
        async with AsyncSessionLocal() as db:
            workflow = await db.get(EditorWorkflow, self.thread_id)
            self.control = dict(workflow.outline_control or {}) if workflow else {}
        return self.control

    def snapshot(self) -> dict:
        return {
            "operation_id": self.operation_id,
            "operation_created_at": self.operation_created_at,
            "revision": self.session.get("revision", 1),
            "seq": self.seq,
            "session": deepcopy(self.session),
            "live": deepcopy(self.live),
            "control": dict(self.control),
            "error": self.error,
            "metrics": {
                "calls": self.calls,
                "first_token_ms": self.first_token_ms,
                "first_question_ms": self.first_question_ms,
            },
        }

    async def emit(self, kind: str = "outline_snapshot", **data) -> None:
        self.seq += 1
        payload = (
            self.snapshot()
            if kind != "outline_delta"
            else {
                "operation_id": self.operation_id,
                "operation_created_at": self.operation_created_at,
                "revision": self.session.get("revision", 1),
                "seq": self.seq,
                **data,
            }
        )
        publish(self.thread_id, kind, payload)
        if kind != "outline_delta" or time.monotonic() - self.saved_at >= 0.5:
            await self.save()

    async def save(self) -> None:
        async with AsyncSessionLocal() as db:
            operation = await db.get(EditorOperation, self.operation_id)
            if operation:
                operation.progress = {**(operation.progress or {}), "outline": self.snapshot()}
                await db.commit()
        self.saved_at = time.monotonic()

    async def begin(self, session: dict, status: str, segment_id: str = "") -> None:
        self.session = deepcopy(session)
        self.session["status"] = status
        self.error = ""
        await self.read_control()
        if segment_id:
            self.live = {"segment_id": segment_id, "attempt": str(uuid.uuid4()), "text": ""}
        else:
            self.live = None
        await self.emit()

    async def token(self, text: str) -> None:
        if not self.live:
            return
        if self.first_token_ms is None:
            self.first_token_ms = int((time.monotonic() - self.started_at) * 1000)
        offset = len(self.live["text"])
        self.live["text"] += text
        await self.emit(
            "outline_delta",
            segment_id=self.live["segment_id"],
            attempt=self.live["attempt"],
            offset=offset,
            text=text,
        )

    async def update(self, session: dict, kind: str = "outline_snapshot") -> None:
        self.session = deepcopy(session)
        self.live = None
        if session.get("pending_question") and self.first_question_ms is None:
            self.first_question_ms = int((time.monotonic() - self.started_at) * 1000)
        await self.emit(kind)


async def projection(thread_id: str, state_session: dict | None = None) -> dict | None:
    runtime = live_runtimes.get(thread_id)
    if runtime and runtime.session:
        result = runtime.snapshot()
    else:
        async with AsyncSessionLocal() as db:
            operations = list(
                await db.scalars(
                    select(EditorOperation)
                    .where(EditorOperation.thread_id == thread_id)
                    .order_by(EditorOperation.created_at.desc())
                    .limit(20)
                )
            )
            result = next(
                (
                    deepcopy(op.progress["outline"])
                    for op in operations
                    if (op.progress or {}).get("outline")
                ),
                None,
            )
    async with AsyncSessionLocal() as db:
        workflow = await db.get(EditorWorkflow, thread_id)
        control = dict(workflow.outline_control or {}) if workflow else {}
    if not result and state_session:
        result = {
            "session": deepcopy(state_session),
            "live": None,
            "seq": 0,
            "revision": state_session["revision"],
            "operation_id": "",
        }
    if result:
        if state_session and state_session.get("revision", 0) > result.get("revision", 0):
            result.update(
                session=deepcopy(state_session), live=None, revision=state_session["revision"]
            )
        result["control"] = control
    return result


async def workflow_response(service, thread_id: str) -> dict:
    """A queued/paused start is a real workflow even before the first graph checkpoint."""
    from app.script_editor.outline.contracts import new_session
    from app.script_editor.services.workflow_service import WorkflowNotFoundError

    try:
        return await service.get_state(thread_id)
    except WorkflowNotFoundError:
        async with AsyncSessionLocal() as db:
            workflow = await db.get(EditorWorkflow, thread_id)
            initial = await db.scalar(
                select(EditorOperation).where(
                    EditorOperation.thread_id == thread_id, EditorOperation.kind == "start"
                )
            )
            if not workflow or not initial or not workflow.outline_control:
                raise
            values = {
                **initial.request_payload,
                "outline_session": new_session(),
                "workflow_mode": "create",
            }
        return {
            "success": True,
            "thread_id": thread_id,
            "current_step": "generate_outline",
            "is_complete": False,
            "interrupt": None,
            "state": service.serialize_state(values),
        }
