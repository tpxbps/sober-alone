"""Runtime persistence and controller registry for the single-process game façade."""

from __future__ import annotations

import json
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class FlowControllerRegistry:
    """Identity-safe in-memory registry used by the local single-process runtime."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._controllers: dict[str, Any] = {}

    def __contains__(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._controllers

    def __getitem__(self, session_id: str) -> Any:
        with self._lock:
            return self._controllers[session_id]

    def __setitem__(self, session_id: str, controller: Any) -> None:
        with self._lock:
            self._controllers[session_id] = controller

    def __delitem__(self, session_id: str) -> None:
        with self._lock:
            del self._controllers[session_id]

    def get(self, session_id: str) -> Any | None:
        with self._lock:
            return self._controllers.get(session_id)

    def put(self, session_id: str, controller: Any) -> None:
        self[session_id] = controller

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._controllers.pop(session_id, None)

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
        return script_data
