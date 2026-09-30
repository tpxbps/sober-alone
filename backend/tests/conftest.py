"""Deterministic game turns with a real database and explicitly gated inference."""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Character, GameSession, PlayerState, Script
from app.game.flow_controller import GameFlowController
from app.services.game_turns import GameTurnRunner


@pytest.fixture
async def turns(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'turns.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    names = {"ai": "甲", "human": "真人", "ai2": "乙"}
    characters = [{"character_id": cid, "name": name} for cid, name in names.items()]
    async with factory() as db:
        db.add(Script(script_id="script", title="测试", game_full_process=[]))
        db.add_all(Character(script_id="script", **character) for character in characters)
        db.add(
            GameSession(
                session_id="game",
                script_id="script",
                human_character_id="human",
                status="in_progress",
                current_stage="intro",
                current_speaker="ai",
                speech_queue=["ai", "human", "ai2"],
                runtime_snapshot={
                    "script_id": "script",
                    "title": "测试",
                    "characters": characters,
                    "game_full_process": [],
                },
            )
        )
        await db.flush()
        db.add_all(
            PlayerState(session_id="game", character_id=cid, remaining_speech_count=2)
            for cid in names
        )
        await db.commit()
    harness = SimpleNamespace(
        factory=factory,
        text_gate=asyncio.Event(),
        reaction_gate=asyncio.Event(),
        calls=0,
        checkpoints=[],
        controllers=[],
        error=None,
        chunks=["第一句。", "第二句。"],
    )

    async def capture():
        return "before-speech"

    async def broadcast(**_kwargs):
        await harness.reaction_gate.wait()
        return {}

    async def ensure(session_id, db):
        manager = SimpleNamespace(
            get_character_name=lambda cid: names.get(cid, ""),
            broadcast_speech=broadcast,
            get_agent=lambda _cid: SimpleNamespace(
                capture_speech_checkpoint=capture, thread_id="test-role"
            ),
        )
        controller = GameFlowController(
            await db.get(GameSession, session_id), {"characters": characters}, manager
        )

        async def generate(_cid, _db, *, checkpoint_id=None):
            if getattr(harness, "generator", None):
                async for chunk in harness.generator():
                    yield chunk
                return
            harness.calls += 1
            harness.checkpoints.append(checkpoint_id)
            yield {"type": "token", "text": harness.chunks[0]}
            await harness.text_gate.wait()
            if harness.error:
                raise harness.error
            yield {"type": "token", "text": harness.chunks[1]}

        controller.generate_ai_speech = generate
        harness.controllers.append(controller)
        return controller

    runner = GameTurnRunner(factory, ensure)
    harness.runner = runner
    monkeypatch.setattr("app.services.game_turns.game_turn_runner", runner)
    yield harness
    await runner.shutdown()
    await engine.dispose()
