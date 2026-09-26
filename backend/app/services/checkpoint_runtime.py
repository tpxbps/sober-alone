"""Lifespan-owned durable LangGraph checkpointers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

_game_checkpointer: Any | None = None


def set_game_checkpointer(checkpointer: Any | None) -> None:
    global _game_checkpointer
    _game_checkpointer = checkpointer


def get_game_checkpointer() -> Any | None:
    return _game_checkpointer


async def delete_game_checkpoints(
    session_id: str, character_ids: Iterable[str] | None = None
) -> None:
    checkpointer = get_game_checkpointer()
    if checkpointer is None:
        return
    # Include isolated attempts, including orphaned attempts after a process restart.
    isolated = set()
    async for item in checkpointer.alist(None):
        thread = item.config.get("configurable", {}).get("thread_id", "")
        if thread.startswith(f"{session_id}_"):
            isolated.add(thread)
    # Each AI has a distinct thread id; SQLite deletion is prefix-unaware.
    # The per-character ids are removed by callers that still have the manager.
    thread_ids = isolated | {
        f"{session_id}_{character_id}" for character_id in (character_ids or [])
    }
    manager = None
    try:
        from app.agents.agent_manager import peek_agent_manager

        manager = peek_agent_manager(session_id)
    except Exception:
        pass
    if manager:
        for info in manager.agents.values():
            if info.agent:
                thread_ids.add(info.agent.thread_id)
    for thread_id in sorted(thread_ids):
        await checkpointer.adelete_thread(thread_id)
