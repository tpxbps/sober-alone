"""SSE speech orchestration kept behind the GameService compatibility facade."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import aclosing
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GameStage
from app.game.clue_media import presentation_pending

logger = logging.getLogger(__name__)
_ai_speech_locks: dict[str, asyncio.Lock] = {}


def session_lock(session_id: str) -> asyncio.Lock:
    return _ai_speech_locks.setdefault(session_id, asyncio.Lock())


def release_speech_lock(session_id: str) -> None:
    lock = _ai_speech_locks.get(session_id)
    if lock is not None and not lock.locked():
        _ai_speech_locks.pop(session_id, None)


EnsureController = Callable[[str, AsyncSession], Awaitable[Any | None]]


def encode_sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


class GameSpeechService:
    def __init__(self, db_session: AsyncSession, ensure_controller: EnsureController):
        self.db = db_session
        self._ensure_controller = ensure_controller

    async def stream_human(self, session_id: str, content: str):
        """Serialize human and AI writes for one session."""
        lock = session_lock(session_id)
        async with lock:
            async for event in self._stream_human_locked(session_id, content):
                yield event

    async def _stream_human_locked(self, session_id: str, content: str):
        """
        处理真人玩家发言（流式SSE）

        记录发言并触发AI反应，返回SSE格式流式数据。
        """
        flow_controller = await self._ensure_controller(session_id, self.db)
        if not flow_controller:
            yield encode_sse({"type": "error", "message": "游戏会话不存在或已结束"})
            return

        if getattr(flow_controller.session, "pending_speech", None):
            from app.game.turn_state import finish_pending

            await finish_pending(flow_controller, self.db)
        human_character_id = flow_controller.session.human_character_id
        if (getattr(flow_controller.session, "speech_generation", None) or {}).get(
            "status"
        ) == "failed":
            yield encode_sse({"type": "error", "message": "请先重试或跳过未完成的发言"})
            return
        if presentation_pending(flow_controller.session):
            yield encode_sse(
                {
                    "type": "error",
                    "code": "clue_presentation_pending",
                    "message": "请先查看线索并确认继续推理",
                }
            )
            return
        current_speaker = flow_controller.session.current_speaker
        current_stage = flow_controller.session.current_stage

        # 自由发言阶段允许真人随时发言（调度器不将真人纳入轮次）
        # 其他阶段（intro/summary等）需要轮到真人才能发言
        if (
            current_stage != GameStage.FREE_DISCUSSION.value
            and current_speaker != human_character_id
        ):
            speaker_name = flow_controller.agent_manager.get_character_name(current_speaker)
            yield encode_sse({"type": "error", "message": f"当前是{speaker_name}的发言回合"})
            return

        # 记录真人发言
        flow_controller.session.last_active_at = datetime.now()
        yield encode_sse({"type": "speech_recorded", "message": "发言已记录"})

        result = await flow_controller.process_speech(
            character_id=human_character_id,
            content=content,
            is_human=True,
            db_session=self.db,
        )

        if not result.get("success"):
            yield encode_sse({"type": "error", "message": result.get("error", "处理失败")})
            return

        # 触发AI反应
        reactions = result.get("reactions", [])
        if reactions:
            yield encode_sse({"type": "thinking", "message": "其他玩家正在反应..."})
            for reaction in reactions:
                char_name = flow_controller.agent_manager.get_character_name(
                    reaction.get("character_id", "")
                )
                yield encode_sse(
                    {
                        "type": "reaction",
                        "character_name": char_name,
                        "content": reaction.get("content", ""),
                    }
                )
            yield encode_sse({"type": "reactions_done"})

        yield encode_sse(
            {
                "type": "done",
                "next_speaker_id": result.get("next_speaker"),
                "next_speaker_name": result.get("next_speaker_name", ""),
            }
        )

    async def stream_ai(
        self,
        session_id: str,
        character_id: str,
        *,
        retry_generation_id: str | None = None,
        expected_generation_id: str | None = None,
    ):
        """Serialize one in-flight AI turn and reject stale duplicate requests."""

        from sqlalchemy import select

        from app.db.models import GameSession
        from app.services.speech_generation import (
            active_generations,
            generation_event,
            public_generation,
        )

        lock = session_lock(session_id)
        if session_id in active_generations or lock.locked():
            yield encode_sse(
                {
                    "type": "error",
                    "code": "speech_in_progress",
                    "message": "该角色正在发言，请重新读取当前状态",
                }
            )
            return
        async with lock:
            self.db.expire_all()
            result = await self.db.execute(
                select(GameSession).where(GameSession.session_id == session_id)
            )
            session = result.scalar_one_or_none()
            if not session:
                yield encode_sse({"type": "error", "message": "游戏会话不存在或已结束"})
                return
            generation = public_generation(session) or {}
            if expected_generation_id and expected_generation_id != generation.get("generation_id"):
                yield encode_sse(
                    {"type": "error", "code": "stale_speech", "message": "该发言请求已过期"}
                )
                return
            if retry_generation_id:
                if (
                    generation.get("generation_id") != retry_generation_id
                    or generation.get("status") != "failed"
                ):
                    yield encode_sse(
                        {"type": "error", "code": "stale_speech", "message": "该发言请求已过期"}
                    )
                    return
            elif generation.get("status") == "failed":
                yield encode_sse(generation_event(session))
                return
            if session.pending_speech:
                from app.game.turn_state import finish_pending

                controller = await self._ensure_controller(session_id, self.db)
                await finish_pending(controller, self.db)
            if presentation_pending(session):
                yield encode_sse(
                    {
                        "type": "error",
                        "code": "clue_presentation_pending",
                        "message": "请先查看线索并确认继续推理",
                    }
                )
                return
            if session.current_speaker != character_id:
                yield encode_sse({"type": "error", "message": "该发言请求已过期，当前发言者已变化"})
                return
            session.last_active_at = datetime.now()
            await self.db.commit()
            async with aclosing(self._stream_ai_locked(session_id, character_id)) as stream:
                async for event in stream:
                    yield event

    async def _stream_ai_locked(self, session_id: str, character_id: str):
        from contextlib import aclosing

        from app.services.speech_generation import bounded_generation, heartbeat_while

        controller = await self._ensure_controller(session_id, self.db)
        if not controller:
            yield encode_sse({"type": "error", "message": "游戏会话不存在或已结束"})
            return
        async with aclosing(bounded_generation(controller, character_id, self.db)) as stream:
            async for event in stream:
                if event["type"] != "generation_ready":
                    yield encode_sse(event)
                    continue
                result = None
                async with aclosing(
                    heartbeat_while(
                        controller.process_speech(
                            character_id=character_id,
                            content=event["content"],
                            is_human=False,
                            db_session=self.db,
                            consume_human_context=True,
                            speech_attempt=event["attempt"],
                        )
                    )
                ) as commit:
                    async for item in commit:
                        if item["type"] == "result":
                            result = item["result"]
                        else:
                            yield encode_sse(item)
                if not result or not result.get("success"):
                    yield encode_sse(
                        {"type": "error", "message": "发言未能提交，请重新读取当前状态"}
                    )
                    return
                yield encode_sse({"type": "speech_done"})
                yield encode_sse(
                    {
                        "type": "done",
                        "next_speaker_id": result.get("next_speaker"),
                        "next_speaker_name": result.get("next_speaker_name"),
                        "stage_complete": result.get("stage_complete", False),
                    }
                )

    async def skip_ai(self, session_id: str, generation_id: str):
        from app.agents.speech_attempt import SpeechAttempt
        from app.services.speech_generation import public_generation

        async with session_lock(session_id):
            self.db.expire_all()
            controller = await self._ensure_controller(session_id, self.db)
            if not controller:
                return {"success": False, "error": "游戏会话不存在"}
            generation = public_generation(controller.session) or {}
            if (
                generation.get("generation_id") != generation_id
                or generation.get("status") != "failed"
            ):
                return {"success": False, "error": "该发言请求已过期"}
            character_id = generation["character_id"]
            name = controller.agent_manager.get_character_name(character_id)
            attempt = SpeechAttempt(generation_id, generation["attempt_id"])
            return await controller.process_speech(
                character_id,
                f"系统提示：已跳过{name}的本次发言。",
                db_session=self.db,
                skip_reactions=True,
                skipped=True,
                speech_attempt=attempt,
            )
