"""Serialized outline commands and replay-safe background execution."""

from __future__ import annotations

import asyncio
from copy import deepcopy

from langgraph.types import Command
from sqlalchemy import select

from app.db.models import EditorOperation, EditorWorkflow
from app.db.session import AsyncSessionLocal
from app.script_editor.outline.contracts import OutlineAction, OutlineConflict
from app.script_editor.outline.runtime import current_runtime, live_runtimes, projection
from app.script_editor.services.progress_bus import publish
from app.script_editor.services.workflow_service import ScriptEditorWorkflowService


async def decision_checkpoint(service, thread_id: str, request: OutlineAction):
    for snapshot in await service._history(service.config(thread_id)):
        session = snapshot.values.get("outline_session") or {}
        question = session.get("pending_question") or {}
        checkpoint_id = snapshot.config["configurable"].get("checkpoint_id")
        if (
            question.get("id") == request.question_id
            and session.get("revision") == request.expected_revision
            and "outline_wait" in snapshot.next
            and (not request.checkpoint_id or request.checkpoint_id == checkpoint_id)
        ):
            return snapshot
    raise OutlineConflict("该决策点不属于当前版本，请刷新后重试")


def validate_choice(question: dict, request: OutlineAction) -> None:
    if request.option_id and request.option_id not in {o["id"] for o in question["options"]}:
        raise OutlineConflict("所选方向已经失效，请刷新问题")
    if not request.option_id and not request.other_text.strip():
        raise ValueError("请选择方向或输入其他想法")


async def queue_action(runner, thread_id: str, request: OutlineAction, owner_key_hash: str):
    async with runner.command_lock(thread_id):
        await runner.authorize(thread_id, owner_key_hash)
        async with AsyncSessionLocal() as db:
            previous = await db.scalar(
                select(EditorOperation).where(
                    EditorOperation.thread_id == thread_id,
                    EditorOperation.operation_id == request.request_id,
                )
            )
            if previous:
                return runner._accepted(previous)
        service = ScriptEditorWorkflowService()
        snapshot = await service._get_snapshot(service.config(thread_id))
        session = snapshot.values.get("outline_session") or {}
        async with AsyncSessionLocal() as db:
            workflow = await db.get(EditorWorkflow, thread_id)
            control = dict(workflow.outline_control or {})
            if control.get("revision", 1) != request.expected_revision:
                raise OutlineConflict("大纲版本已变化，请刷新后重试")
            if not control or (snapshot.values and not session):
                raise OutlineConflict("该流程使用旧版大纲，请使用原审阅操作")
            if snapshot.values.get("current_step") not in {
                None,
                "",
                "init",
                "generate_outline",
                "review_outline",
            }:
                raise OutlineConflict("已进入后续创作阶段，不能修改共创决策")
            active = await db.scalar(
                select(EditorOperation).where(
                    EditorOperation.thread_id == thread_id,
                    EditorOperation.status.in_(("queued", "running")),
                )
            )
            if active and request.action not in {"pause", "stop_questions"}:
                raise OutlineConflict("当前操作尚未结束，请先暂停再修改")
            if request.action == "answer":
                question = session.get("pending_question") or {}
                if question.get("id") != request.question_id:
                    raise OutlineConflict("该问题已回答或已失效，请刷新")
                validate_choice(question, request)
            if request.action == "rewrite":
                if active:
                    raise OutlineConflict("请先暂停创作")
                target = await decision_checkpoint(service, thread_id, request)
                validate_choice(target.values["outline_session"]["pending_question"], request)
            if request.action == "pause":
                control["paused"] = True
                workflow.status = "paused"
                if active:
                    active.status = "paused"
            elif request.action == "stop_questions":
                control["questions_stopped"] = True
            else:
                control["paused"] = False
            if request.action == "rewrite":
                control["revision"] = request.expected_revision + 1
            workflow.outline_control = control
            immediate = request.action == "pause" or (
                request.action == "stop_questions" and (active is not None or control.get("paused"))
            )
            operation = EditorOperation(
                operation_id=request.request_id,
                thread_id=thread_id,
                kind="outline",
                target_step="outline_wait",
                request_payload=request.model_dump(),
                status="complete" if immediate else "queued",
                progress={"message": "已接受共创操作"},
            )
            db.add(operation)
            if not immediate:
                workflow.status = "running"
            await db.commit()
            active_id = active.operation_id if active else None
            accepted = runner._accepted(operation)
        live = live_runtimes.get(thread_id)
        captured = live.snapshot() if live and live.session else None
        if live:
            live.control = control
        if request.action == "pause" and active_id:
            task = runner._tasks.get(active_id)
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        if immediate:
            state = await service._get_snapshot(service.config(thread_id))
            projected = captured or await projection(thread_id, state.values.get("outline_session"))
            if projected:
                projected["control"] = control
                async with AsyncSessionLocal() as db:
                    saved = await db.get(EditorOperation, request.request_id)
                    saved.progress = {
                        "message": "已暂停" if control.get("paused") else "已停止提问",
                        "outline": projected,
                    }
                    await db.commit()
                publish(thread_id, "outline_snapshot", projected)
        else:
            runner._schedule(operation.operation_id)
        return accepted


async def execute_action(service, thread_id: str, payload: dict) -> dict:
    request = OutlineAction.model_validate(payload)
    config = service.config(thread_id)
    snapshot = await service._get_snapshot(config)
    session = snapshot.values.get("outline_session") or {}
    if not snapshot.values:
        from app.api.schemas.script_editor import StartWorkflowRequest

        async with AsyncSessionLocal() as db:
            initial = await db.scalar(
                select(EditorOperation).where(
                    EditorOperation.thread_id == thread_id, EditorOperation.kind == "start"
                )
            )
            workflow = await db.get(EditorWorkflow, thread_id)
            if not initial or not workflow:
                raise OutlineConflict("初始创作请求不存在")
            return await service.start(
                StartWorkflowRequest.model_validate(initial.request_payload),
                workflow.owner_key_hash,
                thread_id,
            )
    if request.action == "rewrite" and session.get("revision") == request.expected_revision:
        target = await decision_checkpoint(service, thread_id, request)
        restored = deepcopy(target.values["outline_session"])
        restored.update(
            revision=request.expected_revision + 1, status="awaiting_answer", repairs=0, check=None
        )
        runtime = current_runtime.get()
        if runtime:
            restored["questions_stopped"] = (await runtime.read_control()).get(
                "questions_stopped", False
            )
        # update_state creates a new branch of checkpoints; previous history is untouched.
        await service.graph.aupdate_state(
            target.config,
            {
                "outline_session": restored,
                "outline": target.values.get("outline", ""),
                "script_title": target.values.get("script_title", ""),
            },
            as_node="outline_director",
        )
        snapshot = await service._get_snapshot(config)
        session = snapshot.values["outline_session"]
    consumed = request.request_id in session.get("consumed_requests", [])
    question = session.get("pending_question")
    if request.action in {"answer", "rewrite"} and not consumed:
        if not question or question["id"] != request.question_id:
            raise OutlineConflict("回答目标已变化，拒绝重放旧回答")
        answer = {**request.model_dump(), "source": "user"}
        if current_runtime.get():
            current_runtime.get().answer = answer
        await service.graph.ainvoke(Command(resume=answer), config)
    elif snapshot.next and not service.extract_interrupt(snapshot):
        await service.graph.ainvoke(None, config)
    elif request.action in {"retry", "continue"} and not question and snapshot.next:
        await service.graph.ainvoke(None, config)
    return service._live_response(thread_id, await service._get_snapshot(config))


async def finish_automatic_answers(service, thread_id: str, result: dict) -> dict:
    """Close the race where stop_questions arrives just before interrupt commits."""
    runtime = current_runtime.get()
    while runtime:
        control = await runtime.read_control()
        question = (result.get("state", {}).get("outline_session") or {}).get("pending_question")
        if not question or not control.get("questions_stopped") or control.get("paused"):
            break
        await service.graph.ainvoke(
            Command(
                resume={
                    "question_id": question["id"],
                    "option_id": question["recommended_option_id"],
                    "source": "ai",
                }
            ),
            service.config(thread_id),
        )
        result = service._live_response(
            thread_id, await service._get_snapshot(service.config(thread_id))
        )
    return result


async def emit_final(runtime, session: dict | None, error: str = "") -> None:
    if session:
        runtime.session = deepcopy(session)
    runtime.error = error
    if not error:
        runtime.live = None
    await runtime.read_control()
    await runtime.emit("outline_error" if error else "outline_snapshot")
    live_runtimes.pop(runtime.thread_id, None)


async def sync_review_fork(service, thread_id: str, result: dict) -> dict:
    """Give a restored outline review a new version without reviving old controls."""
    session = result.get("state", {}).get("outline_session")
    if not session or result.get("current_step") != "review_outline":
        return result
    import uuid

    from app.script_editor.outline.runtime import OutlineRuntime

    async with AsyncSessionLocal() as db:
        workflow = await db.get(EditorWorkflow, thread_id)
        control = dict(workflow.outline_control or {})
        control.update(revision=control.get("revision", session["revision"]) + 1, paused=False)
        restored = deepcopy(session)
        restored.update(
            revision=control["revision"], questions_stopped=control.get("questions_stopped", False)
        )
        await service.graph.aupdate_state(
            service.config(thread_id), {"outline_session": restored}, as_node="outline_check"
        )
        await service.graph.ainvoke(None, service.config(thread_id))
        workflow.outline_control = control
        workflow.status = "idle"
        workflow.current_step = "review_outline"
        operation_id = str(uuid.uuid4())
        db.add(
            EditorOperation(
                operation_id=operation_id,
                thread_id=thread_id,
                kind="outline",
                target_step="review_outline",
                status="complete",
                request_payload={"action": "phase_restore"},
                progress={},
            )
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        operation = await db.get(EditorOperation, operation_id)
        created_at = operation.created_at.isoformat()
    runtime = OutlineRuntime(thread_id, operation_id, operation_created_at=created_at)
    await runtime.read_control()
    await runtime.update(restored)
    return await service.get_state(thread_id)
