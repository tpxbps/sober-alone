import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Character, Script
from app.script_editor.asset_generation import service as asset_service
from app.script_editor.nodes import save
from app.script_editor.repositories.script_repository import ScriptRepository
from app.script_editor.services.progress_registry import asset_progress_registry


@pytest.mark.asyncio
async def test_optional_asset_tasks_are_skipped_without_keys(monkeypatch):
    monkeypatch.setattr(save.settings, "ZHIPUAI_API_KEY", None)
    monkeypatch.setattr(save.settings, "DOUBAO_API_KEY", None)
    monkeypatch.setattr(save.settings, "MIMO_API_KEY", None)
    script_id = "test-no-assets"

    await save.generate_assets(
        {
            "script_id": script_id,
            "characters": [{"character_id": "char-a", "name": "甲"}],
            "game_full_process": [{"type": "initial"}, {"type": "review"}],
        }
    )
    progress = save.get_asset_progress(script_id)

    assert progress is not None
    assert progress["isComplete"] is True
    tasks = [task for phase in progress["phases"] for task in phase["tasks"]]
    assert tasks
    assert {task["status"] for task in tasks} == {"skipped"}
    assert all(task.get("reason") for task in tasks)


@pytest.mark.asyncio
async def test_script_repository_saves_script_and_characters_atomically(tmp_path, monkeypatch):
    database = tmp_path / "generated.db"
    database_url = f"sqlite+aiosqlite:///{database.as_posix()}"
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(save.settings, "DATABASE_URL", database_url)
    from app.script_editor.repositories import script_repository

    monkeypatch.setattr(script_repository.settings, "DATABASE_URL", database_url)

    await ScriptRepository.save_generated_script(
        {
            "script_id": "generated-script",
            "script_title": "生成剧本",
            "player_count": 1,
            "difficulty": 1,
            "num_clue_rounds": 1,
            "characters": [
                {
                    "character_id": "generated-character",
                    "name": "林岚",
                    "gender": "女",
                    "age": 28,
                    "occupation": "气象观察员",
                }
            ],
            "game_data_sections": {
                "game_flow": [],
                "full_truth": "真相",
                "free_speech_limits": [1],
                "character_scripts": {"林岚": "个人剧本"},
                "character_data": [
                    {
                        "name": "林岚",
                        "profile": "简介",
                        "appearance": "外貌",
                        "system_prompt": "提示",
                    }
                ],
            },
        }
    )

    async with session_factory() as session:
        script = await session.scalar(select(Script))
        character = await session.scalar(select(Character))
        assert script is not None and script.title == "生成剧本"
        assert character is not None and character.script_id == script.script_id
        assert character.character_script == "个人剧本"

    await engine.dispose()


@pytest.mark.asyncio
async def test_retry_missing_avatar_target_fails_instead_of_completing():
    script_id = "test-missing-avatar"
    asset_progress_registry.init(
        script_id,
        [
            {
                "id": "image",
                "label": "图片",
                "tech": "test",
                "tasks": [{"id": "avatar_missing", "label": "缺失角色", "status": "failed"}],
            }
        ],
    )

    result = await asset_service.AssetGenerationService().retry(
        script_id,
        "avatar_missing",
        {"characters": []},
    )
    progress = save.get_asset_progress(script_id)
    matching = [
        task
        for phase in (progress or {}).get("phases", [])
        for task in phase.get("tasks", [])
        if task["id"] == "avatar_missing"
    ]

    assert result.ok is False
    assert result.error == "角色不存在"
    assert matching[0]["status"] == "failed"
    assert matching[0]["reason"] == "角色不存在"
