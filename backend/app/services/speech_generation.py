"""Application deadlines are measured against visible speech, not network packets."""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from contextlib import aclosing
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.speech_attempt import SpeechAttempt, speech_attempt_scope
from app.core.inference import (
    InferenceRecoveryError,
    raise_for_inference_recovery,
    retryable_gateway_error,
)
from app.db.models import GameSession
from app.game.citation_stream import CitationStreamFilter
from app.game.citation_syntax import tokenize
from app.game.clues import stage_public_clues
from app.services.speech_telemetry import report_speech_metric

FIRST_VISIBLE_SECONDS = 45.0
VISIBLE_IDLE_SECONDS = 30.0
GENERATION_SECONDS = 120.0
HEARTBEAT_SECONDS = 5.0
CANCEL_SECONDS = 2.0
MAX_ATTEMPTS = 2
logger = logging.getLogger(__name__)
# The application supports one process. Persistent state handles process restarts.
active_generations: dict[str, str] = {}
_draining: set[asyncio.Task] = set()


class SpeechDeadline(TimeoutError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def public_generation(session):
    value = dict(getattr(session, "speech_generation", None) or {})
    if not value:
        return None
    if value.get("status") in {"generating", "streaming", "retrying"} and active_generations.get(
        session.session_id
    ) != value.get("generation_id"):
        value.update(status="failed", reason="interrupted")
        session.speech_generation = value
    return value


def generation_event(session):
    return {"type": "speech_status", "generation": public_generation(session)}


async def save_generation(db, session, **updates):
    session.speech_generation = {**(session.speech_generation or {}), **updates}
    await db.commit()


def _observe_task(task):
    _draining.discard(task)
    if not task.cancelled():
        task.exception()


async def stop_task(task):
    if task.done():
        _observe_task(task)
        return
    task.cancel()
    done, _ = await asyncio.wait({task}, timeout=CANCEL_SECONDS)
    if not done:
        # An uncooperative provider cannot hold the UI hostage. Its isolated
        # checkpoint and inactive context cannot become an accepted game turn.
        _draining.add(task)
        task.add_done_callback(_observe_task)
    else:
        _observe_task(task)


async def _produce(controller, character_id, bind, queue, attempt):
    with speech_attempt_scope(attempt):
        async with AsyncSession(bind=bind, expire_on_commit=False) as db:
            try:
                async with aclosing(controller.generate_ai_speech(character_id, db)) as stream:
                    async for chunk in stream:
                        attempt.check()
                        await queue.put(chunk)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                await queue.put(error)
            else:
                await queue.put(None)


async def _mark_disconnected(bind, session_id, generation_id, partial):
    async with AsyncSession(bind=bind, expire_on_commit=False) as db:
        session = await db.get(GameSession, session_id)
        value = session.speech_generation if session else None
        if (
            value
            and value.get("generation_id") == generation_id
            and value.get("status") in {"generating", "streaming", "retrying"}
        ):
            await save_generation(
                db, session, status="failed", reason="disconnected", partial_content=partial
            )


async def discard_checkpoint(attempt, bind, session_id, producer=None):
    if not attempt or not attempt.checkpointer:
        return

    # Wait for scratch writes to stop before deleting them. Never delete the
    # accepted pointer, and never delay the player's failure controls for cleanup.
    async def clean():
        if producer and not producer.done():
            await asyncio.gather(producer, return_exceptions=True)
        try:
            async with AsyncSession(bind=bind, expire_on_commit=False) as db:
                session = await db.get(GameSession, session_id)
                accepted = session and attempt.thread_id in (session.player_threads or {}).values()
            thread = attempt.previous_thread_id if accepted else attempt.thread_id
            if thread:
                await attempt.checkpointer.adelete_thread(thread)
        except Exception:
            logger.warning("Could not clean a role checkpoint", exc_info=False)

    task = asyncio.create_task(clean())
    _draining.add(task)
    task.add_done_callback(_observe_task)


async def bounded_generation(controller, character_id, db):
    session = controller.session
    generation_id = str(uuid.uuid4())
    active_generations[session.session_id] = generation_id
    started = time.monotonic()
    deadline = started + GENERATION_SECONDS
    now = datetime.now(UTC)
    session.speech_generation = {
        "generation_id": generation_id,
        "character_id": character_id,
        "stage": session.current_stage,
        "round": session.current_round,
        "status": "generating",
        "attempt": 0,
        "attempt_id": "",
        "started_at": now.isoformat(),
        "deadline_at": (now + timedelta(seconds=GENERATION_SECONDS)).isoformat(),
        "partial_content": "",
        "reason": None,
        "attempts": [],
    }
    full_content = ""
    attempt = None
    task = None
    try:
        await db.commit()
        for number in range(1, MAX_ATTEMPTS + 1):
            attempt = SpeechAttempt(generation_id, str(uuid.uuid4()))
            await save_generation(
                db,
                session,
                attempt=number,
                attempt_id=attempt.attempt_id,
                status="generating",
                reason=None,
                attempt_started_at=datetime.now(UTC).isoformat(),
            )
            yield generation_event(session)
            queue = asyncio.Queue(maxsize=64)
            task = asyncio.create_task(_produce(controller, character_id, db.bind, queue, attempt))
            citation_filter = CitationStreamFilter(
                stage_public_clues(session.current_stage, session.revealed_clues or [])
            )
            first_visible_ms = None
            raw_content = ""
            visible_deadline = attempt.started + FIRST_VISIBLE_SECONDS
            heartbeat_at = time.monotonic() + HEARTBEAT_SECONDS
            failure = None
            try:
                while True:
                    now_mono = time.monotonic()
                    if now_mono >= deadline:
                        raise SpeechDeadline("generation_timeout")
                    if now_mono >= visible_deadline:
                        raise SpeechDeadline(
                            "first_visible_timeout"
                            if first_visible_ms is None
                            else "visible_idle_timeout"
                        )
                    if now_mono >= heartbeat_at:
                        yield {"type": "heartbeat", "generation_id": generation_id}
                        heartbeat_at = now_mono + HEARTBEAT_SECONDS
                    wait = min(deadline, visible_deadline, heartbeat_at) - time.monotonic()
                    try:
                        chunk = await asyncio.wait_for(queue.get(), timeout=max(0.001, wait))
                    except TimeoutError:
                        continue
                    if isinstance(chunk, Exception):
                        raise chunk
                    if chunk is None:
                        text = citation_filter.finish()
                        if text.strip() and first_visible_ms is None:
                            first_visible_ms = round((time.monotonic() - attempt.started) * 1000, 1)
                        if text:
                            full_content += text
                            yield {"type": "token", "text": text}
                        if not full_content.strip():
                            raise SpeechDeadline("empty_output")
                        break
                    if chunk.get("type") == "error":
                        raise RuntimeError("role_generation_error")
                    if chunk.get("type") == "progress":
                        yield {"type": "thinking", "message": chunk.get("status", "")}
                    if chunk.get("type") == "token":
                        raw_content += chunk.get("text", "")
                        text = citation_filter.feed(chunk.get("text", ""))
                        full_content += text
                        if text.strip():
                            visible_deadline = time.monotonic() + VISIBLE_IDLE_SECONDS
                            if first_visible_ms is None:
                                first_visible_ms = round(
                                    (time.monotonic() - attempt.started) * 1000, 1
                                )
                                await save_generation(
                                    db,
                                    session,
                                    status="streaming",
                                    first_visible_ms=first_visible_ms,
                                )
                                yield generation_event(session)
                        if text:
                            yield {"type": "token", "text": text}
            except Exception as error:
                try:
                    raise_for_inference_recovery(error)
                except InferenceRecoveryError as recovery:
                    failure = recovery
                else:
                    failure = error
            if failure:
                attempt.active = False
            await stop_task(task)
            if failure:
                await discard_checkpoint(attempt, db.bind, session.session_id, task)
            task = None
            elapsed_ms = round((time.monotonic() - attempt.started) * 1000, 1)
            code = getattr(failure, "code", type(failure).__name__) if failure else None
            if isinstance(failure, InferenceRecoveryError):
                code = "account_recovery"
            attempts = [
                *(session.speech_generation.get("attempts") or []),
                {
                    "attempt_id": attempt.attempt_id,
                    "duration_ms": elapsed_ms,
                    "first_event_ms": attempt.first_event_ms,
                    "first_visible_ms": first_visible_ms,
                    "reason": code,
                },
            ]
            await save_generation(
                db,
                session,
                attempts=attempts,
                duration_ms=round((time.monotonic() - started) * 1000, 1),
            )
            tokens = [token for token in tokenize(raw_content) if token.ids]
            allowed_ids = {
                clue["id"]
                for clue in stage_public_clues(session.current_stage, session.revealed_clues or [])
            }
            report_speech_metric(
                "attempt_finished",
                session.session_id,
                session.speech_generation,
                **attempts[-1],
                cycle_duration_ms=session.speech_generation["duration_ms"],
                direct_refs=sum(token.label is None for token in tokens),
                associated_refs=sum(token.label is not None for token in tokens),
                unknown_refs=sum(
                    any(id not in allowed_ids for id in token.ids) for token in tokens
                ),
            )
            logger.info(
                "Role generation attempt session=%s attempt=%s duration_ms=%s first_visible_ms=%s reason=%s",
                session.session_id,
                attempt.attempt_id,
                elapsed_ms,
                first_visible_ms,
                code,
            )
            if not failure:
                yield {"type": "generation_ready", "content": full_content, "attempt": attempt}
                return
            retry = (
                not full_content.strip()
                and number < MAX_ATTEMPTS
                and time.monotonic() + 1.5 < deadline
                and (isinstance(failure, SpeechDeadline) or retryable_gateway_error(failure))
            )
            if retry:
                await save_generation(db, session, status="retrying", reason=code)
                yield generation_event(session)
                await asyncio.sleep(random.uniform(0.5, 1.5))
                full_content = ""
            else:
                await save_generation(
                    db,
                    session,
                    status="failed",
                    reason=code,
                    partial_content=full_content,
                    duration_ms=round((time.monotonic() - started) * 1000, 1),
                )
                yield generation_event(session)
                if isinstance(failure, InferenceRecoveryError):
                    raise failure
                return
    finally:
        if attempt:
            attempt.active = False
        if task:
            await stop_task(task)
        await discard_checkpoint(attempt, db.bind, session.session_id, task)
        if active_generations.get(session.session_id) == generation_id:
            active_generations.pop(session.session_id, None)
        # A disconnect, generator close or process-level cancellation must leave
        # an explicit failed state. A completed record is never overwritten.
        cleanup = asyncio.create_task(
            _mark_disconnected(db.bind, session.session_id, generation_id, full_content)
        )
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            _draining.add(cleanup)
            cleanup.add_done_callback(_observe_task)
            raise


async def heartbeat_while(awaitable):
    task = asyncio.create_task(awaitable)
    try:
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=HEARTBEAT_SECONDS)
            if not done:
                yield {"type": "heartbeat"}
        yield {"type": "result", "result": task.result()}
    finally:
        if not task.done():
            await stop_task(task)
