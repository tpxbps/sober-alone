from pathlib import Path

import chromadb
import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes.script_editor import delete_script
from app.api.routes.script_editor_routes.scripts import claim_legacy_ownership
from app.api.schemas.script_editor import LegacyOwnershipClaimRequest
from app.core.config import settings
from app.db.base import Base
from app.db.models import Character, GameRecord, GameSession, PlayerState, Script
from app.script_editor.ownership import hash_author_key
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
                owner_key_hash=hash_author_key("test-author-key-0000000000000000"),
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
        result = await delete_script(
            "delete-me",
            session,
            hash_author_key("test-author-key-0000000000000000"),
        )

        assert result["success"] is True
        for model in (Script, Character, GameSession, PlayerState, GameRecord):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
        assert not audio_dir.exists()
        assert not image_dir.exists()
        assert asset_progress_registry.snapshot("delete-me") is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_script_recovery_is_explicit_guarded_and_one_time(
    tmp_path: Path, monkeypatch
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'claim.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.exec_driver_sql("ALTER TABLE scripts ADD COLUMN owner_uuid VARCHAR(36)")

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    legacy_id = "11111111-1111-4111-8111-111111111111"
    new_owner_hash = hash_author_key("new-author-key-00000000000000000000")
    async with session_factory() as session:
        script = Script(
            script_id="legacy-owned",
            title="legacy",
            game_full_process=[],
            free_speech_limits=[],
        )
        session.add(script)
        await session.flush()
        await session.execute(
            text("UPDATE scripts SET owner_uuid = :owner_uuid WHERE script_id = :script_id"),
            {"owner_uuid": legacy_id, "script_id": script.script_id},
        )
        await session.commit()

        monkeypatch.setattr(settings, "ALLOW_LEGACY_OWNER_CLAIM", False)
        with pytest.raises(HTTPException) as exc_info:
            await claim_legacy_ownership(
                LegacyOwnershipClaimRequest(legacy_owner_uuids=[legacy_id]),
                session,
                new_owner_hash,
            )
        assert exc_info.value.status_code == 403

        monkeypatch.setattr(settings, "ALLOW_LEGACY_OWNER_CLAIM", True)
        first = await claim_legacy_ownership(
            LegacyOwnershipClaimRequest(legacy_owner_uuids=[legacy_id]),
            session,
            new_owner_hash,
        )
        await session.refresh(script)
        assert first == {"success": True, "claimed_count": 1, "matched_count": 1}
        assert script.owner_key_hash == new_owner_hash
        assert legacy_id not in str(first)

        repeated = await claim_legacy_ownership(
            LegacyOwnershipClaimRequest(legacy_owner_uuids=[legacy_id]),
            session,
            new_owner_hash,
        )
        assert repeated == {"success": True, "claimed_count": 0, "matched_count": 1}

    await engine.dispose()
