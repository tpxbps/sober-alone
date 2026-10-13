"""Durable single-process turns. HTTP connections subscribe; they never own execution."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import nullcontext
from datetime import datetime

from sqlalchemy import select

from app.agents.speech_attempt import SpeechAttempt, speech_attempt_scope
from app.core.inference import InferenceRecoveryError, retryable_gateway_error
from app.core.rate_limits import retry_delay_seconds
from app.db.models import GameRecord, GameSession, GameTurn
from app.db.session import AsyncSessionLocal
from app.game.citation_stream import CitationStreamFilter
from app.game.clue_media import presentation_pending
from app.game.clues import parse_clue_citations, stage_public_clues
from app.game.turn_state import finish_pending, process_turn
from app.services.turn_errors import turn_error_message

logger = logging.getLogger(__name__)
RUNNING = ("queued", "speaking", "committing", "reacting")
GENERATION_SECONDS = 300
TERMINAL = ("completed", "failed", "blocked", "cancelled")


class TurnConflict(Exception):
    """A stale command asks its caller to reconcile, not to fail the model turn."""


class EmptySpeechError(Exception):
    pass


def active_turn_query(session_id):
    return (
        select(GameTurn)
        .where(
            GameTurn.session_id == session_id,
            GameTurn.status.not_in(("completed", "cancelled")),
        )
        .order_by(GameTurn.created_at.desc())
        .limit(1)
    )


class GameTurnRunner:
    def __init__(self, factory=AsyncSessionLocal, ensure_controller=None):
        self.factory = factory
        self.ensure_controller = ensure_controller
        self.tasks: dict[str, asyncio.Task] = {}
        self.admissions: set[asyncio.Task] = set()
        self.locks: dict[str, asyncio.Lock] = {}
        self.changed: dict[str, asyncio.Event] = {}
        # Private deployments install ownership/funding scopes here. Only opaque
        # session identity is persisted; credentials remain outside game state.
        self.execution_context = lambda _session_id: nullcontext()
        self.recovery_handler = None

    def command_lock(self, session_id):
        return self.locks.setdefault(session_id, asyncio.Lock())

    def notify(self, turn_id):
        event = self.changed.pop(turn_id, None)
        if event:
            event.set()

    async def accept(self, *args, **kwargs):
        # A disconnected subscriber cannot interrupt commit-to-worker handoff.
        task = asyncio.create_task(self.start(*args, **kwargs))
        self.admissions.add(task)

        def finished(done):
            self.admissions.discard(done)
            if not done.cancelled():
                done.exception()

        task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def start(
        self, session_id, speaker_id, kind, content="", *, request_id=None, expected_revision=None
    ):
        request_id = request_id or str(uuid.uuid4())
        async with self.command_lock(session_id), self.factory() as db:
            previous = await db.get(GameTurn, request_id)
            if previous:
                if (
                    previous.session_id != session_id
                    or previous.kind != kind
                    or (speaker_id and previous.speaker_id != speaker_id)
                    or (kind == "human" and previous.content != content)
                ):
                    raise TurnConflict()
                return previous.snapshot()
            session = await db.get(GameSession, session_id)
            if (
                not session
                or session.status == "finished"
                or session.current_stage in ("vote", "review", "completed")
            ):
                raise TurnConflict()
            active = await db.scalar(active_turn_query(session_id))
            if active:
                # Two tabs requesting the same AI slot attach to one operation.
                if kind == "ai" and active.kind == kind and active.speaker_id == speaker_id:
                    return active.snapshot()
                raise TurnConflict()
            if presentation_pending(session):
                raise TurnConflict()
            if session.pending_speech:
                raise TurnConflict()
            if expected_revision is not None and expected_revision != session.state_revision:
                raise TurnConflict()
            if kind == "human":
                speaker_id = session.human_character_id
                if (
                    session.current_stage != "free_discussion"
                    and session.current_speaker != speaker_id
                ):
                    raise TurnConflict()
            elif session.current_speaker != speaker_id or speaker_id == session.human_character_id:
                raise TurnConflict()
            from app.db.models import PlayerState

            player = await db.scalar(
                select(PlayerState).where(
                    PlayerState.session_id == session_id,
                    PlayerState.character_id == speaker_id,
                )
            )
            if player and (
                (session.current_stage == "free_discussion" and player.remaining_speech_count <= 0)
                or (session.current_stage != "free_discussion" and player.has_spoken_this_round)
            ):
                raise TurnConflict()
            session.state_revision = (session.state_revision or 0) + 1
            session.last_active_at = datetime.now()
            turn = GameTurn(
                turn_id=request_id,
                session_id=session_id,
                speaker_id=speaker_id,
                kind=kind,
                stage=session.current_stage,
                content=content,
                state_revision=session.state_revision,
            )
            db.add(turn)
            await db.commit()
            snapshot = turn.snapshot()
        self.schedule(request_id, session_id)
        return snapshot

    def schedule(self, turn_id, session_id):
        if turn_id in self.tasks and not self.tasks[turn_id].done():
            return
        task = asyncio.create_task(self.run(turn_id, session_id), name=f"game-turn:{turn_id}")
        self.tasks[turn_id] = task

        def finished(completed):
            if self.tasks.get(turn_id) is completed:
                self.tasks.pop(turn_id, None)
            if not completed.cancelled() and completed.exception():
                logger.error(
                    "Turn runner failed turn=%s error=%s",
                    turn_id,
                    type(completed.exception()).__name__,
                )

        task.add_done_callback(finished)

    async def publish(self, db, turn, **changes):
        for key, value in changes.items():
            setattr(turn, key, value)
        turn.seq += 1
        turn.updated_at = datetime.now()
        await db.commit()
        self.notify(turn.turn_id)

    async def controller(self, session_id, db):
        if self.ensure_controller:
            controller = await self.ensure_controller(session_id, db)
        else:
            from app.services.game_service import ensure_flow_controller

            controller = await ensure_flow_controller(session_id, db, resume_pending=False)
        if not controller:
            raise TurnConflict()
        controller.session = await db.get(GameSession, session_id)
        return controller

    async def generate(self, db, turn, controller, attempt):
        """Flush bounded batches even if the provider pauses after a final token."""
        queue = asyncio.Queue(maxsize=64)
        end = object()

        async def produce():
            # Keep the generator and its contextvars in one task. Inference tools
            # use a different session from the snapshot writer.
            try:
                with speech_attempt_scope(attempt):
                    await produce_scoped()
            except Exception as error:
                await queue.put(error)
            finally:
                if not asyncio.current_task().cancelling():
                    await queue.put(end)

        async def produce_scoped():
            async with self.factory() as inference_db:
                async for chunk in controller.generate_ai_speech(
                    turn.speaker_id,
                    inference_db,
                    checkpoint_id=turn.input_checkpoint_id,
                ):
                    attempt.check()
                    await queue.put(chunk)

        producer = asyncio.create_task(produce())
        citation_filter = CitationStreamFilter(
            stage_public_clues(
                controller.session.current_stage,
                controller.session.revealed_clues or [],
            )
        )
        content = ""
        dirty = False
        first = True
        first_visible_ms = None
        failure = None
        flushed_at = time.monotonic()
        pending = asyncio.create_task(queue.get())
        try:
            while True:
                ready, _ = await asyncio.wait({pending}, timeout=0.05 if dirty else None)
                if ready:
                    chunk = pending.result()
                    if chunk is end:
                        break
                    if isinstance(chunk, Exception):
                        raise chunk
                    pending = asyncio.create_task(queue.get())
                    if chunk.get("type") == "token":
                        text = citation_filter.feed(chunk.get("text", ""))
                        if text:
                            content += text
                            turn.content = content
                            turn.thinking_tip = ""
                            turn.clue_refs = parse_clue_citations(
                                content, citation_filter.clues, strip_unknown=True
                            )[1]
                            dirty = True
                    elif chunk.get("type") == "progress" and not content:
                        await self.publish(db, turn, thinking_tip=chunk.get("status", ""))
                    elif chunk.get("type") == "error":
                        raise RuntimeError("Role generation could not complete")
                if dirty and (first or not ready or time.monotonic() - flushed_at >= 0.05):
                    await self.publish(db, turn)
                    if first:
                        first_visible_ms = round((time.monotonic() - attempt.started) * 1000, 1)
                        logger.info(
                            "Turn first text turn=%s attempt=%s", turn.turn_id, turn.attempt
                        )
                    first, dirty, flushed_at = False, False, time.monotonic()
            content += citation_filter.finish()
            if not content.strip():
                raise EmptySpeechError()
            await self.publish(
                db,
                turn,
                content=content,
                status="committing",
                generation_done=True,
                attempt_state={
                    "generation_id": attempt.generation_id,
                    "attempt_id": attempt.attempt_id,
                    "thread_id": attempt.thread_id,
                    "previous_thread_id": attempt.previous_thread_id,
                    "observation_ids": list(attempt.observation_ids),
                    "role_updates": [
                        v.model_dump() if hasattr(v, "model_dump") else v
                        for v in attempt.role_updates
                    ],
                },
                thinking_tip="",
            )
            logger.info("Turn text done turn=%s attempt=%s", turn.turn_id, turn.attempt)
        except BaseException as error:
            failure = type(error).__name__
            raise
        finally:
            from app.services.speech_telemetry import report_speech_metric

            report_speech_metric(
                "attempt_finished",
                turn.session_id,
                {
                    **controller.session.speech_generation,
                    "attempt": turn.attempt,
                },
                duration_ms=round((time.monotonic() - attempt.started) * 1000, 1),
                first_event_ms=attempt.first_event_ms,
                first_visible_ms=first_visible_ms,
                reason=failure,
            )
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            if not producer.done():
                attempt.active = False
            from app.services.speech_generation import stop_task

            await stop_task(producer)

    async def run(self, turn_id, session_id):
        from app.services.game_speech import session_lock

        draft = None
        attempt = None
        try:
            with self.execution_context(session_id):
                async with session_lock(session_id), self.factory() as db:
                    turn = await db.get(GameTurn, turn_id)
                    if not turn or turn.status not in RUNNING:
                        return
                    controller = await self.controller(session_id, db)
                    if not turn.record_id:
                        if turn.kind == "ai" and not turn.generation_done:
                            agent = controller.agent_manager.get_agent(turn.speaker_id)
                            agent.thread_id = (controller.session.player_threads or {}).get(
                                turn.speaker_id
                            ) or agent.thread_id
                            if not turn.input_checkpoint_id:
                                checkpoint_id = await agent.capture_speech_checkpoint()
                                await self.publish(db, turn, input_checkpoint_id=checkpoint_id)
                            retry_deadline = time.monotonic() + 180
                            for retry in range(3):
                                attempt = SpeechAttempt(
                                    turn.turn_id, f"{turn.turn_id}-{turn.attempt}"
                                )
                                controller.session.speech_generation = {
                                    "generation_id": turn.turn_id,
                                    "attempt_id": attempt.attempt_id,
                                    "character_id": turn.speaker_id,
                                    "stage": turn.stage,
                                    "round": controller.session.current_round,
                                    "status": "generating",
                                }
                                await self.publish(
                                    db,
                                    turn,
                                    status="speaking",
                                    content="",
                                    clue_refs=[],
                                    thinking_tip="",
                                )
                                try:
                                    async with asyncio.timeout(GENERATION_SECONDS):
                                        await self.generate(db, turn, controller, attempt)
                                    break
                                except Exception as error:
                                    attempt.active = False
                                    delay = retry_delay_seconds(
                                        error, remaining_seconds=retry_deadline - time.monotonic()
                                    )
                                    if (
                                        delay is None
                                        or retry == 2
                                        or not (
                                            isinstance(error, EmptySpeechError)
                                            or retryable_gateway_error(error)
                                        )
                                    ):
                                        draft = turn.content
                                        raise
                                    await self.publish(db, turn, attempt=turn.attempt + 1)
                                    await asyncio.sleep(delay)
                        if turn.kind == "ai" and turn.attempt_state and attempt is None:
                            saved = turn.attempt_state
                            attempt = SpeechAttempt(saved["generation_id"], saved["attempt_id"])
                            attempt.thread_id = saved.get("thread_id")
                            attempt.previous_thread_id = saved.get("previous_thread_id")
                            attempt.observation_ids = set(saved.get("observation_ids", []))
                            attempt.role_updates = saved.get("role_updates", [])
                        result = await process_turn(
                            controller,
                            turn.speaker_id,
                            turn.content,
                            is_human=turn.kind == "human",
                            db_session=db,
                            consume_human_context=turn.kind == "ai",
                            speech_attempt=attempt,
                            turn_id=turn_id,
                            defer_reactions=True,
                        )
                        if not result.get("success"):
                            raise RuntimeError("Speech commit could not complete")
                        self.notify(turn_id)
                        logger.info("Turn committed turn=%s record=%s", turn_id, turn.record_id)
                    await finish_pending(controller, db)
                    await self.publish(
                        db, turn, status="completed", error_code="", error_message=""
                    )
                    logger.info("Turn completed turn=%s", turn_id)
        except InferenceRecoveryError as error:
            await self.fail(
                turn_id, "blocked", error.action, "模型账户需要处理，处理后可继续本轮", draft
            )
            if self.recovery_handler:
                await self.recovery_handler(session_id, error)
        except asyncio.CancelledError:
            # Shutdown and credential revocation leave recoverable work. Explicit
            # abandon marks cancelled after awaiting this cleanup.
            await self.fail(turn_id, "failed", "interrupted", "本轮执行已中断，可重试继续", draft)
            raise
        except Exception as error:
            logger.warning("Turn failed turn=%s error=%s", turn_id, type(error).__name__)
            code, message = turn_error_message(
                error, empty_output=isinstance(error, EmptySpeechError)
            )
            await self.fail(turn_id, "failed", code, message, draft)

        finally:
            if attempt:
                attempt.active = False

    async def fail(self, turn_id, status, code, message, draft=None):
        async with self.factory() as db:
            turn = await db.get(GameTurn, turn_id)
            if turn and turn.status not in ("completed", "cancelled"):
                changes = dict(
                    status=status, error_code=code, error_message=message, thinking_tip=""
                )
                if draft is not None and not turn.record_id:
                    changes["content"] = draft
                await self.publish(db, turn, **changes)

    async def retry(self, session_id, turn_id, expected_attempt):
        task = self.tasks.get(turn_id)
        if task:
            # A terminal snapshot can arrive a moment before its worker exits.
            async with self.factory() as db:
                turn = await db.get(GameTurn, turn_id)
                terminal = turn and turn.status in TERMINAL
            if terminal:
                await asyncio.gather(asyncio.shield(task), return_exceptions=True)
        async with self.command_lock(session_id), self.factory() as db:
            turn = await db.get(GameTurn, turn_id)
            if not turn or turn.session_id != session_id:
                raise TurnConflict()
            session = await db.get(GameSession, session_id)
            if not session or session.status == "finished":
                raise TurnConflict()
            if (
                turn.status in RUNNING
                or turn.status == "completed"
                or turn.attempt != expected_attempt
            ):
                return turn.snapshot()
            if turn.status not in ("failed", "blocked"):
                raise TurnConflict()
            await self.publish(
                db,
                turn,
                status="reacting"
                if turn.record_id
                else "committing"
                if turn.generation_done
                else "queued",
                attempt=turn.attempt + 1,
                error_code="",
                error_message="",
            )
            snapshot = turn.snapshot()
        self.schedule(turn_id, session_id)
        return snapshot

    async def snapshot(self, session_id, turn_id):
        async with self.factory() as db:
            turn = await db.get(GameTurn, turn_id)
            if not turn or turn.session_id != session_id:
                raise TurnConflict()
            data = turn.snapshot()
            record = await db.get(GameRecord, turn.record_id) if turn.record_id else None
            return data, record.to_display_dict() if record else None

    async def events(self, session_id, turn_id, after_seq=-1):
        from app.services.game_service import GameService
        from app.services.game_speech import encode_sse

        cursor = -1  # Every connection starts with an authoritative snapshot.
        logger.info("Turn subscribe turn=%s after_seq=%s", turn_id, after_seq)
        while True:
            event = self.changed.setdefault(turn_id, asyncio.Event())
            turn, record = await self.snapshot(session_id, turn_id)
            if turn["seq"] > cursor:
                frame = {"type": "turn_snapshot", "turn": turn, "record": record}
                if turn["status"] == "completed":
                    async with self.factory() as db:
                        frame["state"] = await GameService(db).get_game_state(
                            session_id, resume_pending=False
                        )
                    frame["type"] = "done"
                elif turn["status"] == "committing":
                    frame["type"] = "speech_done"
                elif turn["status"] == "reacting":
                    frame["type"] = "speech_recorded"
                yield encode_sse(frame)
                cursor = turn["seq"]
            if turn["status"] in TERMINAL:
                self.changed.pop(turn_id, None)
                return
            try:
                await asyncio.wait_for(event.wait(), timeout=10)
            except TimeoutError:
                yield ": heartbeat\n\n"

    async def recover(self, session_id=None):
        """Adopt old pending speeches; never regenerate an interrupted model call."""
        async with self.factory() as db:
            query = select(GameSession).where(GameSession.status != "finished")
            if session_id:
                query = query.where(GameSession.session_id == session_id)
            sessions = list(await db.scalars(query))
            scheduled = []
            for session in sessions:
                active = await db.scalar(active_turn_query(session.session_id))
                if active and (session_id is not None or active.turn_id in self.tasks):
                    continue
                generation = session.speech_generation or {}
                if (
                    not active
                    and not session.pending_speech
                    and generation.get("status")
                    in {"failed", "generating", "streaming", "retrying", "committing"}
                ):
                    active = GameTurn(
                        turn_id=generation.get("generation_id") or str(uuid.uuid4()),
                        session_id=session.session_id,
                        speaker_id=generation.get("character_id") or session.current_speaker,
                        kind="ai",
                        stage=session.current_stage,
                        status="failed",
                        content=generation.get("partial_content", ""),
                        state_revision=session.state_revision,
                        error_code="interrupted",
                        error_message="上一轮发言未完成，可重试继续",
                    )
                    db.add(active)
                if session.pending_speech and not active:
                    record = await db.get(GameRecord, session.pending_speech["record_id"])
                    if not record:
                        continue
                    active = GameTurn(
                        turn_id=record.turn_id or str(uuid.uuid4()),
                        session_id=session.session_id,
                        speaker_id=record.speaker_character_id,
                        kind="human"
                        if record.speaker_character_id == session.human_character_id
                        else "ai",
                        stage=record.stage,
                        status="reacting",
                        content=record.raw_content,
                        record_id=record.id,
                        clue_refs=record.clue_refs or [],
                        state_revision=session.state_revision,
                    )
                    db.add(active)
                    record.turn_id = active.turn_id
                if (
                    not active
                    or active.status == "blocked"
                    or (
                        active.status == "failed"
                        and not (
                            (active.record_id or active.generation_done)
                            and active.error_code == "interrupted"
                        )
                    )
                ):
                    continue
                if active.record_id or active.generation_done:
                    active.status = "reacting" if active.record_id else "committing"
                    scheduled.append((active.turn_id, session.session_id))
                else:
                    active.status = "failed"
                    active.error_code = "interrupted"
                    active.error_message = "服务重启中断了本轮发言，可重试继续"
                active.seq = (active.seq or 0) + 1
            await db.commit()
        for turn_id, sid in scheduled:
            self.schedule(turn_id, sid)

    async def cancel_session(self, session_id):
        async with self.command_lock(session_id):
            async with self.factory() as db:
                session = await db.get(GameSession, session_id)
                if not session:
                    return
                session.status = "finished"
                session.finished_at = datetime.now()
                await db.commit()
                turns = list(await db.scalars(active_turn_query(session_id)))
            for turn in turns:
                task = self.tasks.get(turn.turn_id)
                if task:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                await self.fail(turn.turn_id, "cancelled", "", "")
            async with self.factory() as db:
                session = await db.get(GameSession, session_id)
                session.pending_speech = {}
                session.current_speaker = None
                session.state_revision += 1
                await db.commit()

    async def shutdown(self):
        await asyncio.gather(*list(self.admissions), return_exceptions=True)
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()


game_turn_runner = GameTurnRunner()
