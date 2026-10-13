"""SSE speech orchestration kept behind the GameService compatibility facade."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

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

    async def stream_human(self, session_id: str, content: str, **command):
        async for event in self._start(session_id, None, "human", content, **command):
            yield event

    async def stream_ai(self, session_id: str, character_id: str, **command):
        async for event in self._start(session_id, character_id, "ai", "", **command):
            yield event

    async def _start(self, session_id, speaker_id, kind, content, **command):
        from app.services.game_service import GameService
        from app.services.game_turns import TurnConflict, game_turn_runner

        try:
            turn = await game_turn_runner.accept(session_id, speaker_id, kind, content, **command)
            async for event in game_turn_runner.events(session_id, turn["turn_id"]):
                yield event
        except TurnConflict:
            state = await GameService(self.db).get_game_state(session_id)
            yield encode_sse({"type": "resync", "state": state})
