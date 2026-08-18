from pathlib import Path

import chromadb
import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes.script_editor import delete_script
from app.core.config import settings
from app.db.base import Base
from app.db.models import Character, GameRecord, GameSession, PlayerState, Script
from app.script_editor.services.progress_registry import asset_progress_registry


@pytest.mark.asyncio
async def test_script_delete_cascades_runtime_and_files(tmp_path: Path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'delete.db').as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            Script(
                script_id="delete-me",
                title="delete",
                game_full_process=[],
                free_speech_limits=[],
            )
        )
        session.add(Character(character_id="character", script_id="delete-me", name="角色"))
        session.add(GameSession(session_id="session", script_id="delete-me"))
        await session.flush()
        session.add(PlayerState(session_id="session", character_id="character"))
        session.add(GameRecord(session_id="session", raw_content="record"))
        await session.commit()

        audio_dir = tmp_path / "audio" / "scripts" / "delete-me"
        image_dir = tmp_path / "images" / "scripts" / "delete-me"
        audio_dir.mkdir(parents=True)
        image_dir.mkdir(parents=True)
        (audio_dir / "voice.wav").write_bytes(b"test")
        (image_dir / "cover.png").write_bytes(b"test")
        monkeypatch.setattr(type(settings), "audio_dir", property(lambda _self: tmp_path / "audio"))
        monkeypatch.setattr(
            type(settings), "image_dir", property(lambda _self: tmp_path / "images")
        )
        monkeypatch.setattr(
            chromadb,
            "PersistentClient",
            lambda **_kwargs: type(
                "Client", (), {"delete_collection": lambda _self, _name: None}
            )(),
        )

        asset_progress_registry.register_thread("delete-me", "thread")
        asset_progress_registry.init("delete-me", [])
        result = await delete_script("delete-me", session)

        assert result["success"] is True
        for model in (Script, Character, GameSession, PlayerState, GameRecord):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
        assert not audio_dir.exists()
        assert not image_dir.exists()
        assert asset_progress_registry.snapshot("delete-me") is None

    await engine.dispose()
