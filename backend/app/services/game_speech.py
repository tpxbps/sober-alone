"""SSE speech orchestration kept behind the GameService compatibility facade."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GameStage

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

    async def stream_ai(self, session_id: str, character_id: str):
        """Serialize one in-flight AI turn and reject stale duplicate requests."""

        from sqlalchemy import select

        from app.db.models import GameSession

        lock = session_lock(session_id)
        async with lock:
            if not hasattr(self.db, "expire_all"):
                async for event in self._stream_ai_locked(session_id, character_id):
                    yield event
                return
            self.db.expire_all()
            result = await self.db.execute(
                select(GameSession).where(GameSession.session_id == session_id)
            )
            session = result.scalar_one_or_none()
            if not session:
                yield encode_sse({"type": "error", "message": "游戏会话不存在或已结束"})
                return
            if session.pending_speech:
                from app.game.turn_state import finish_pending

                controller = await self._ensure_controller(session_id, self.db)
                await finish_pending(controller, self.db)
            if session.current_speaker != character_id:
                yield encode_sse({"type": "error", "message": "该发言请求已过期，当前发言者已变化"})
                return
            session.last_active_at = datetime.now()
            await self.db.commit()
            async for event in self._stream_ai_locked(session_id, character_id):
                yield event

    async def _stream_ai_locked(self, session_id: str, character_id: str):
        """
        处理AI玩家发言（流式）

        返回SSE格式的流式数据，支持多种事件类型:
        - token: LLM生成的文本片段（最终发言内容）
        - thinking: AI正在思考/使用工具（不暴露工具内容）
        - done: 流结束标记

        Args:
            session_id: 游戏会话ID
            character_id: 角色ID

        Yields:
            str: SSE格式的数据行
        """
        flow_controller = await self._ensure_controller(session_id, self.db)
        if not flow_controller:
            yield encode_sse({"type": "error", "message": "游戏会话不存在或已结束"})
            return

        # 生成AI发言
        full_content = ""
        is_thinking = False
        agent_error = False

        try:
            async for chunk in flow_controller.generate_ai_speech(character_id, self.db):
                # chunk 是 dict，包含 type 和相应字段
                if isinstance(chunk, dict):
                    chunk_type = chunk.get("type", "unknown")

                    if chunk_type == "token":
                        if is_thinking:
                            is_thinking = False

                        text = chunk.get("text", "")
                        full_content += text
                        # 发送文本token给前端
                        yield encode_sse({"type": "token", "text": text})

                    elif chunk_type == "progress":
                        status = chunk.get("status", "")
                        if status:
                            yield encode_sse({"type": "thinking", "message": status})
                            is_thinking = True

                    elif chunk_type == "error":
                        agent_error = True
                        logger.error(f"Agent error for {character_id}: {chunk.get('message', '')}")
        except Exception as e:
            agent_error = True
            logger.error(f"AI speech stream error: {e}")

        # AI发言流结束，通知前端进入反应处理阶段
        yield encode_sse({"type": "speech_done"})

        # 记录发言并确定下一位发言者
        # 当 agent 出错或内容为空时，用兜底消息代替，确保流程继续推进
        next_speaker_info = {}
        content_to_record = full_content
        if agent_error or not full_content:
            logger.warning(
                f"Agent {character_id} produced no content (error={agent_error}), inserting fallback record"
            )
            content_to_record = "（系统提示：AI角色出现未知错误，暂时无法正常发言。）"
            try:
                result = await flow_controller.process_speech(
                    character_id=character_id,
                    content=content_to_record,
                    is_human=False,
                    db_session=self.db,
                    skip_reactions=True,
                )
                next_speaker_info = {
                    "next_speaker_id": result.get("next_speaker"),
                    "next_speaker_name": result.get("next_speaker_name"),
                    "stage_complete": result.get("stage_complete", False),
                }
            except Exception as e:
                logger.error(f"process_speech failed after agent error: {e}")
                next_speaker_info = {
                    "error": str(e),
                }
        else:
            try:
                result = await flow_controller.process_speech(
                    character_id=character_id,
                    content=full_content,
                    is_human=False,
                    db_session=self.db,
                    consume_human_context=True,
                )
                next_speaker_info = {
                    "next_speaker_id": result.get("next_speaker"),
                    "next_speaker_name": result.get("next_speaker_name"),
                    "stage_complete": result.get("stage_complete", False),
                }
            except Exception as e:
                next_speaker_info = {
                    "error": str(e),
                }

        # 发送结束标记，包含下一位发言者信息
        yield encode_sse({"type": "done", **next_speaker_info})
