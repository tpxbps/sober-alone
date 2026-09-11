"""Runtime persistence and controller registry for the single-process game façade."""

from __future__ import annotations

import json
import threading
from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.game.clues import CLUE_SCHEMA_VERSION, derive_game_process, normalize_clue_stages

RUNTIME_SNAPSHOT_FIELDS = (
    "script_id",
    "title",
    "overview",
    "description",
    "tags",
    "difficulty",
    "player_count",
    "estimated_duration",
    "game_full_process",
    "clue_stages",
    "clue_schema_version",
    "full_truth",
    "ending_config",
    "cover_image_url",
    "free_speech_limits",
    "characters",
)


def build_runtime_snapshot(
    script_data: dict[str, Any],
    llm_configs: dict[str, dict[str, str | None]] | None = None,
) -> dict[str, Any]:
    """Copy only game-facing data into an immutable session snapshot."""

    snapshot = {key: deepcopy(script_data.get(key)) for key in RUNTIME_SNAPSHOT_FIELDS}
    clue_stages = normalize_clue_stages(
        snapshot.get("clue_stages"),
        script_id=str(snapshot.get("script_id", "")),
        game_full_process=snapshot.get("game_full_process") or [],
    )
    snapshot["clue_stages"] = clue_stages
    snapshot["clue_schema_version"] = CLUE_SCHEMA_VERSION
    snapshot["game_full_process"] = derive_game_process(
        snapshot.get("game_full_process") or [], clue_stages
    )
    snapshot["llm_configs"] = deepcopy(llm_configs or {})
    return snapshot


class FlowControllerRegistry:
    """Identity-safe in-memory registry used by the local single-process runtime."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._controllers: dict[str, Any] = {}
        self._last_access: dict[str, datetime] = {}

    def __contains__(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._controllers

    def __getitem__(self, session_id: str) -> Any:
        with self._lock:
            self._last_access[session_id] = datetime.now()
            return self._controllers[session_id]

    def __setitem__(self, session_id: str, controller: Any) -> None:
        with self._lock:
            self._controllers[session_id] = controller
            self._last_access[session_id] = datetime.now()

    def __delitem__(self, session_id: str) -> None:
        with self._lock:
            del self._controllers[session_id]
            self._last_access.pop(session_id, None)

    def get(self, session_id: str) -> Any | None:
        with self._lock:
            controller = self._controllers.get(session_id)
            if controller is not None:
                self._last_access[session_id] = datetime.now()
            return controller

    def put(self, session_id: str, controller: Any) -> None:
        self[session_id] = controller

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._controllers.pop(session_id, None)
            self._last_access.pop(session_id, None)

    def prune_inactive(self, max_age: timedelta) -> list[str]:
        cutoff = datetime.now() - max_age
        with self._lock:
            expired = [sid for sid, touched in self._last_access.items() if touched < cutoff]
            for session_id in expired:
                self._controllers.pop(session_id, None)
                self._last_access.pop(session_id, None)
            return expired

    async def get_or_restore(
        self,
        session_id: str,
        restore: Callable[[], Awaitable[Any | None]],
    ) -> Any | None:
        controller = self.get(session_id)
        if controller is not None:
            return controller
        controller = await restore()
        if controller is not None:
            self.put(session_id, controller)
        return controller


class GameRuntimeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def load_script(self, script_id: str) -> dict[str, Any] | None:
        script_result = await self.session.execute(
            text("SELECT * FROM scripts WHERE script_id = :script_id"),
            {"script_id": script_id},
        )
        script_row = script_result.fetchone()
        if not script_row:
            return None

        character_result = await self.session.execute(
            text("SELECT * FROM characters WHERE script_id = :script_id"),
            {"script_id": script_id},
        )
        script_data = dict(script_row._mapping)
        script_data["characters"] = [dict(row._mapping) for row in character_result.fetchall()]
        if isinstance(script_data.get("game_full_process"), str):
            try:
                script_data["game_full_process"] = json.loads(script_data["game_full_process"])
            except json.JSONDecodeError:
                script_data["game_full_process"] = []
        for field, fallback in (
            ("clue_stages", []),
            ("free_speech_limits", []),
            ("ending_config", None),
        ):
            if isinstance(script_data.get(field), str):
                try:
                    script_data[field] = json.loads(script_data[field])
                except json.JSONDecodeError:
                    script_data[field] = fallback
        script_data["clue_stages"] = normalize_clue_stages(
            script_data.get("clue_stages"),
            script_id=script_id,
            game_full_process=script_data.get("game_full_process") or [],
        )
        return script_data

    async def load_session_script(self, game_session: Any) -> dict[str, Any] | None:
        snapshot = game_session.runtime_snapshot or {}
        if isinstance(snapshot, dict) and snapshot.get("script_id"):
            return deepcopy(snapshot)
        return await self.load_script(game_session.script_id)
