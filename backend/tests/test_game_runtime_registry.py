from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import GameSession, Script
from app.services.checkpoint_runtime import delete_game_checkpoints, set_game_checkpointer
from app.services.game_runtime import FlowControllerRegistry
from app.services.game_service import GameService


@pytest.mark.asyncio
async def test_registry_restores_once_and_remove_is_idempotent():
    registry = FlowControllerRegistry()
    restored = object()
    calls = 0

    async def restore():
        nonlocal calls
        calls += 1
        return restored

    assert await registry.get_or_restore("session", restore) is restored
    assert await registry.get_or_restore("session", restore) is restored
    assert calls == 1

    registry.remove("session")
    registry.remove("session")
    assert registry.get("session") is None


def test_registry_prunes_only_expired_process_objects():
    registry = FlowControllerRegistry()
    registry.put("stale", object())
    registry.put("active", object())
    registry._last_access["stale"] = datetime.now() - timedelta(hours=73)

    assert registry.prune_inactive(timedelta(hours=72)) == ["stale"]
    assert registry.get("stale") is None
    assert registry.get("active") is not None


@pytest.mark.asyncio
async def test_checkpoint_cleanup_uses_snapshot_character_ids_without_live_manager():
    class Checkpointer:
        def __init__(self):
            self.deleted: list[str] = []

        async def adelete_thread(self, thread_id):
            self.deleted.append(thread_id)

    checkpointer = Checkpointer()
    set_game_checkpointer(checkpointer)
    try:
        await delete_game_checkpoints("session", ["human", "ai-one", "ai-two"])
    finally:
        set_game_checkpointer(None)

    assert checkpointer.deleted == [
        "session_ai-one",
        "session_ai-two",
        "session_human",
    ]


@pytest.mark.asyncio
async def test_game_creation_failure_removes_incomplete_session(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    class BrokenAgentManager:
        async def initialize_agents(self, *_args, **_kwargs):
            raise RuntimeError("model initialization failed")

    async with factory() as session:
        session.add(Script(script_id="script", title="测试剧本"))
        await session.commit()
        service = GameService(session)

        async def load_script(_script_id):
            return {
                "script_id": "script",
                "characters": [
                    {"character_id": "human", "name": "真人"},
                    {"character_id": "ai", "name": "AI"},
                ],
                "game_full_process": [],
            }

        monkeypatch.setattr(service, "_get_script_data", load_script)
        monkeypatch.setattr(
            "app.services.game_service.get_agent_manager",
            lambda _session_id, _script_id: BrokenAgentManager(),
        )

        result = await service.create_game("script", "human")
        session_count = await session.scalar(select(func.count()).select_from(GameSession))

    assert result["success"] is False
    assert session_count == 0
    await engine.dispose()
