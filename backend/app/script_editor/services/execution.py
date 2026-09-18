"""Observable node execution and content-bound, replay-safe generation metadata."""

from __future__ import annotations

import hashlib
import inspect
import json
from datetime import datetime, timezone

from langchain_core.runnables import RunnableConfig

from app.script_editor.state import ScriptGenState

PROMPT_VERSION = "workshop-v4.2"
GENERATION_REVIEW = {
    "generate_outline": "review_outline",
    "generate_first_draft": "review_first_draft",
    "review_by_llm": "review_report",
    "generate_final_draft": "review_final",
    "convert_to_game_data": "review_game_data",
}


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def creative_context(state: dict, step: str) -> str:
    """Never reintroduce discarded outline branches into downstream writing."""
    session = state.get("outline_session") or {}
    facts = session.get("canon", [])
    text = "\n\n【作者已确认的有效要求】\n" + json.dumps(facts, ensure_ascii=False) if facts else ""
    refinement = state.get("refinement") or {}
    if refinement.get("target") == GENERATION_REVIEW.get(step):
        field = {
            "review_outline": "outline",
            "review_first_draft": "first_draft",
            "review_report": "review_opinion",
            "review_final": "final_draft",
            "review_game_data": "game_data_sections",
        }[refinement["target"]]
        text += "\n\n【本次改进方向】\n" + refinement.get("feedback", "")
        text += "\n【当前作者编辑稿：保留未要求修改的内容】\n" + json.dumps(
            state.get(field, ""), ensure_ascii=False
        )
    return text


def observe_model(response, *, validation: str = "", schema: str = "") -> None:
    """Record provider-reported identity and usage, without retaining raw transport data."""
    from app.script_editor.outline.runtime import current_runtime

    runtime = current_runtime.get()
    metadata = getattr(response, "response_metadata", {}) or {}
    model = metadata.get("model_name") or metadata.get("model")
    if runtime and model:
        runtime.model_responses.append(
            {
                "model": model,
                "usage": getattr(response, "usage_metadata", None),
                "finish_reason": metadata.get("finish_reason"),
                "validation": validation,
                "schema": schema,
            }
        )


async def report_stage(step: str, *, finished: bool = False, outcome: str = "running"):
    from app.db.models import EditorOperation, EditorWorkflow
    from app.db.session import AsyncSessionLocal
    from app.script_editor.outline.runtime import current_runtime, finish_database_access
    from app.script_editor.services.progress_bus import publish

    runtime = current_runtime.get()
    if not runtime:
        return
    runtime.stage = step
    await runtime.drain_progress()

    async def save():
        async with AsyncSessionLocal() as db:
            operation = await db.get(EditorOperation, runtime.operation_id)
            workflow = await db.get(EditorWorkflow, runtime.thread_id)
            if not operation or operation.status == "paused":
                return
            runtime.progress_seq += 1
            event = {
                "operation_id": runtime.operation_id,
                "seq": runtime.progress_seq,
                "current_step": step,
                "finished": finished,
                "outcome": outcome,
            }
            operation.progress = {
                **(operation.progress or {}),
                "workflow": event,
                "event_seq": runtime.progress_seq,
            }
            if workflow:
                workflow.current_step = step
            await db.commit()
            publish(runtime.thread_id, "workflow_progress", event)

    async with runtime.storage_lock:
        await finish_database_access(save())


def observable_node(name, fn):
    async def run(state: ScriptGenState, config: RunnableConfig):
        from app.script_editor.outline.runtime import current_runtime

        runtime = current_runtime.get()
        model_start = len(runtime.model_responses) if runtime else 0
        await report_stage("generate_outline" if name.startswith("outline_") else name)
        result = (
            fn(state, config=config) if "config" in inspect.signature(fn).parameters else fn(state)
        )
        if inspect.isawaitable(result):
            result = await result
        if name == "save_to_database" and result.get("error_message"):
            result["retry_step"] = name
        if (
            name in GENERATION_REVIEW
            or name in {"outline_director", "outline_apply", "outline_finalize"}
        ) and not result.get("error_message"):
            from app.script_editor.llm import MODEL
            from app.script_editor.outline.runtime import current_runtime

            runtime = current_runtime.get()
            refinement = state.get("refinement") or {}
            counts = dict(state.get("refinement_counts") or {})
            consumed = list(state.get("completed_refinements") or [])
            request_id = refinement.get("request_id")
            if (
                request_id
                and refinement.get("target") == GENERATION_REVIEW.get(name)
                and request_id not in consumed
            ):
                counts[refinement["target"]] = counts.get(refinement["target"], 0) + 1
                consumed.append(request_id)
            audit = list(state.get("generation_audit") or [])
            audit.append(
                {
                    "step": name,
                    "operation_id": runtime.operation_id if runtime else "",
                    "prompt_version": PROMPT_VERSION,
                    "reported_models": runtime.model_responses[model_start:] if runtime else [],
                    "input_checkpoint_id": config.get("configurable", {}).get("checkpoint_id")
                    or (runtime.input_checkpoint_id if runtime else None),
                    "model": MODEL,
                    "input_hash": digest(
                        {
                            k: state.get(k)
                            for k in (
                                "user_idea",
                                "outline_session",
                                "game_data_sections",
                                "review_opinion",
                                "human_review",
                                "outline",
                                "first_draft",
                                "final_draft",
                                "prompts",
                                "refinement",
                            )
                        }
                    ),
                    "output_hash": digest(result),
                    "feedback": refinement.get("feedback", "")
                    if refinement.get("target") == GENERATION_REVIEW.get(name)
                    else (state.get("outline_session") or {})
                    .get("pending_input", {})
                    .get("other_text", "")
                    if name == "outline_apply"
                    else "",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            result = {
                **result,
                "refinement_counts": counts,
                "completed_refinements": consumed,
                "generation_audit": audit,
            }
        return result

    return run
