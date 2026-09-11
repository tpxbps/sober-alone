from copy import deepcopy
from datetime import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.base import Base
from app.db.models import Character, GameSession, Script
from app.script_editor import editing
from app.script_editor.editing import (
    hydrate_completed_script,
    normalize_game_data,
    prepare_asset_plan,
)
from app.script_editor.ownership import hash_author_key, owner_hash_matches
from app.script_editor.repositories.script_repository import ScriptRepository
from app.script_editor.services.workflow_service import (
    ScriptEditorWorkflowService,
    WorkflowAuthorizationError,
)


def completed_script():
    script = Script(
        script_id="script-1",
        title="旧标题",
        overview="概述",
        description="描述",
        tags="悬疑",
        difficulty=2,
        player_count=2,
        game_full_process=[
            {"type": "initial", "stage_title": "开场", "system_notice": "欢迎"},
            {
                "type": "advancement",
                "children": [
                    {"stage_title": "线索", "system_notice": "线索正文"},
                    {"stage_title": "讨论", "system_notice": "开始讨论"},
                ],
            },
            {
                "type": "vote",
                "children": [
                    {"stage_title": "总结", "system_notice": "请总结"},
                    {"stage_title": "投票", "system_notice": "请投票"},
                ],
            },
            {"type": "review", "stage_title": "真相", "system_notice": "揭晓"},
        ],
        full_truth="完整真相",
        free_speech_limits=[2],
        owner_key_hash=hash_author_key("author-key-000000000000000000000"),
    )
    characters = [
        Character(
            script_id="script-1",
            character_id="c1",
            name="林岚",
            gender="女",
            age=28,
            occupation="记者",
            character_script="秘密一",
            profile="简介一",
            appearance="黑色风衣",
            system_prompt="保持冷静",
            voice_id="voice-1",
        ),
        Character(
            script_id="script-1",
            character_id="c2",
            name="周沉",
            gender="男",
            age=31,
            occupation="医生",
            character_script="秘密二",
            profile="简介二",
            appearance="白衬衫",
            system_prompt="谨慎辩护",
        ),
    ]
    return script, characters


def test_owner_hash_is_private_and_constant_time_comparable():
    digest = hash_author_key("author-key-000000000000000000000")
    assert len(digest) == 64
    assert owner_hash_matches(digest, digest)
    assert not owner_hash_matches(digest, hash_author_key("another-key-00000000000000000000"))
    assert not owner_hash_matches(None, digest)


def test_completed_script_hydrates_real_persisted_fields_and_stable_ids():
    script, characters = completed_script()
    state = hydrate_completed_script(script, characters, script.owner_key_hash or "")

    assert state["workflow_mode"] == "edit"
    assert state["game_data_sections"]["title"] == "旧标题"
    assert state["game_data_sections"]["character_data"][0]["character_id"] == "c1"
    assert state["game_data_sections"]["character_data"][0]["step_voice_id"] == "voice-1"
    assert "outline" not in state
    assert state["final_draft"] == ""


def test_normalization_uses_character_id_when_role_is_renamed():
    script, characters = completed_script()
    state = hydrate_completed_script(script, characters, script.owner_key_hash or "")
    sections = deepcopy(state["game_data_sections"])
    sections["title"] = "新标题"
    sections["character_data"][0]["name"] = "林晚"
    sections["character_data"][0]["character_script"] = "更新后的秘密"
    state["game_data_sections"] = sections

    result = normalize_game_data(state)

    assert result["data_validation_errors"] == []
    assert result["characters"][0]["character_id"] == "c1"
    assert result["characters"][0]["name"] == "林晚"
    assert result["character_scripts"] == {"林晚": "更新后的秘密", "周沉": "秘密二"}


def test_normalization_rejects_structural_edits_with_locatable_errors():
    script, characters = completed_script()
    state = hydrate_completed_script(script, characters, script.owner_key_hash or "")
    sections = deepcopy(state["game_data_sections"])
    sections["character_data"].pop()
    sections["game_flow"].pop()
    state["game_data_sections"] = sections

    result = normalize_game_data(state)

    assert any("不能增删角色" in message for message in result["data_validation_errors"])
    assert any("不能增删轮次" in message for message in result["data_validation_errors"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("difficulty", "invalid"),
        ("game_flow", ["invalid"]),
        ("character_data", [None]),
        ("clue_stages", [{"items": "invalid"}]),
    ],
)
def test_malformed_structure_returns_validation_errors(field, value):
    script, characters = completed_script()
    state = hydrate_completed_script(script, characters, script.owner_key_hash or "")
    state["game_data_sections"][field] = value
    assert normalize_game_data(state)["data_validation_errors"]


def test_asset_plan_selects_only_changed_dependencies(monkeypatch):
    script, characters = completed_script()
    state = hydrate_completed_script(script, characters, script.owner_key_hash or "")
    sections = deepcopy(state["game_data_sections"])
    sections["character_data"][0]["character_script"] = "更新后的秘密"
    sections["clue_stages"][0]["items"][0]["content"] = "更新后的线索"
    state["game_data_sections"] = sections
    state.update(normalize_game_data(state))

    monkeypatch.setattr(editing, "_artifact_missing", lambda _script_id, _task_id: False)
    monkeypatch.setattr(settings, "ZHIPUAI_API_KEY", "test")
    monkeypatch.setattr(settings, "DOUBAO_API_KEY", "test")
    monkeypatch.setattr(settings, "MIMO_API_KEY", "test")

    plan = {item["id"]: item for item in prepare_asset_plan(state)["asset_plan"]}
    assert plan["vector_c1"]["changed"] is True
    assert plan["vector_c1"]["default_selected"] is True
    assert plan["tts_c1"]["changed"] is True
    assert plan["tts_sys_1_0"]["changed"] is True
    assert plan["cover"]["default_selected"] is False
    assert plan["vector_c2"]["default_selected"] is False


def test_asset_plan_disables_empty_character_tts_and_omits_empty_system_message(
    monkeypatch,
):
    script, characters = completed_script()
    state = hydrate_completed_script(script, characters, script.owner_key_hash or "")
    sections = deepcopy(state["game_data_sections"])
    sections["character_data"][0]["character_script"] = ""
    sections["clue_stages"][0]["free_discussion_notice"] = ""
    state["game_data_sections"] = sections
    state.update(normalize_game_data(state))

    monkeypatch.setattr(editing, "_artifact_missing", lambda _script_id, _task_id: True)
    monkeypatch.setattr(settings, "MIMO_API_KEY", "test")
    plan = {item["id"]: item for item in prepare_asset_plan(state)["asset_plan"]}

    assert "tts_sys_1_1" not in plan
    assert plan["tts_c1"]["available"] is False
    assert plan["tts_c1"]["unavailable_reason"] == "角色个人剧本为空"


@pytest.mark.asyncio
async def test_edit_workflow_starts_directly_at_structured_review():
    script, characters = completed_script()
    service = ScriptEditorWorkflowService()
    response = await service.start_edit(script, characters, script.owner_key_hash or "")

    assert response["current_step"] == "review_game_data"
    assert response["interrupt"]["workflow_mode"] == "edit"
    assert response["state"]["workflow_mode"] == "edit"
    assert response["state"]["outline"] == ""

    with pytest.raises(WorkflowAuthorizationError):
        await service.start_edit(
            script,
            characters,
            hash_author_key("wrong-author-key-000000000000000000"),
        )


@pytest.mark.asyncio
async def test_edit_save_updates_in_place_and_preserves_sessions_and_resources(
    tmp_path, monkeypatch
):
    database = tmp_path / "edit.db"
    database_url = f"sqlite+aiosqlite:///{database.as_posix()}"
    monkeypatch.setattr(settings, "DATABASE_URL", database_url)
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    created_at = datetime(2025, 1, 1)
    script, characters = completed_script()
    script.created_at = created_at
    script.cover_image_url = "/images/old-cover.png"
    characters[0].avatar_url = "/images/old-avatar.png"
    async with factory() as session:
        session.add(script)
        session.add_all(characters)
        session.add(GameSession(session_id="existing-game", script_id="script-1"))
        await session.commit()

    state = hydrate_completed_script(script, characters, script.owner_key_hash or "")
    state["game_data_sections"]["title"] = "原位更新标题"
    state["game_data_sections"]["ending_config"] = {
        "mode": "multiple",
        "culprit_character_id": "c1",
        "branches": [
            {"when": outcome, "title": outcome, "text": f"{outcome}的结局正文"}
            for outcome in ("correct", "incorrect", "tie", "no_votes")
        ],
    }
    state.update(normalize_game_data(state))
    result = await ScriptRepository.save_generated_script(state)
    assert result["error_message"] == ""

    from app.script_editor.nodes.quality_check import quality_fingerprint

    state["quality_report"] = {"content_fingerprint": quality_fingerprint(state)}
    state["script_title"] = "与已审查结构化内容不一致的缓存标题"
    rejected = await ScriptRepository.save_generated_script(state)
    assert "实际保存内容与质量报告不一致" in rejected["error_message"]

    async with factory() as session:
        persisted = await session.scalar(select(Script).where(Script.script_id == "script-1"))
        persisted_character = await session.scalar(
            select(Character).where(Character.character_id == "c1")
        )
        session_count = await session.scalar(select(func.count()).select_from(GameSession))
        assert persisted is not None
        assert persisted.title == "原位更新标题"
        assert persisted.ending_config == state["game_data_sections"]["ending_config"]
        assert persisted.created_at == created_at
        assert persisted.cover_image_url == "/images/old-cover.png"
        assert persisted_character is not None
        assert persisted_character.avatar_url == "/images/old-avatar.png"
        assert session_count == 1

    await engine.dispose()


def test_invalid_ending_returns_to_data_review_and_branch_edit_invalidates_quality(monkeypatch):
    from app.game.content_quality import CAPABILITY_VERSION
    from app.script_editor.nodes.quality_check import (
        QUALITY_CHECK_VERSION,
        quality_approved,
        quality_fingerprint,
    )

    script, characters = completed_script()
    state = hydrate_completed_script(script, characters, script.owner_key_hash or "")
    config = {
        "mode": "multiple",
        "culprit_character_id": "c1",
        "branches": [
            {"when": outcome, "title": outcome, "text": f"{outcome}正文"}
            for outcome in ("correct", "incorrect", "tie", "no_votes")
        ],
    }
    state["game_data_sections"]["ending_config"] = config
    state.update(normalize_game_data(state))
    assert state["data_validation_errors"] == []
    state["quality_report"] = {
        "report_id": "r",
        "status": "passed",
        "capability_version": CAPABILITY_VERSION,
        "check_version": QUALITY_CHECK_VERSION,
        "content_fingerprint": quality_fingerprint(state),
    }
    assert quality_approved(state)
    state["game_data_sections"]["ending_config"]["branches"][0]["text"] = "新的结局"
    assert not quality_approved(state)
    monkeypatch.setattr(editing, "_artifact_missing", lambda *_: False)
    plan = prepare_asset_plan(state)["asset_plan"]
    ending_tasks = [t for t in plan if t["id"].startswith("tts_ending_")]
    assert len(ending_tasks) == 4 and all(t["available"] and t["changed"] for t in ending_tasks)
    state["game_data_sections"]["ending_config"]["branches"].pop()
    result = normalize_game_data(state)
    assert result["_review_action"] == "invalid"
    assert any("结局配置" in e for e in result["data_validation_errors"])
