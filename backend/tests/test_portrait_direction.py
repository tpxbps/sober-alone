import asyncio
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from app.core.inference import InferenceRecoveryError
from app.script_editor.asset_generation import service as assets
from app.script_editor.conversion import public_material
from app.script_editor.editing import asset_dependencies, prepare_asset_plan
from app.script_editor.services import image_gen
from app.script_editor.services import portrait_direction as art
from app.script_editor.services.progress_registry import asset_progress_registry as registry


def story():
    return {
        "script_title": "午后花房",
        "game_data_sections": {
            "overview": "现代植物园中的一次午后聚会。",
            "description": "夏日午后，众人在玻璃花房会合，阳光透过玻璃落在木桌和绿植上。",
            "opening": "花房的门开着，客人已经到齐。",
            "full_truth": "SECRET_TRUTH",
            "character_data": [{"character_script": "SECRET_PERSONAL_SCRIPT"}],
        },
        "final_draft": "SECRET_FINAL_DRAFT",
        "characters": [
            {
                "character_id": "a",
                "name": "林岚",
                "gender": "女",
                "age": 48,
                "occupation": "园艺师",
                "appearance": "方脸、宽下颌、短卷发，肩背结实，穿棉麻工作衫。",
            },
            {
                "character_id": "b",
                "name": "陈芷",
                "gender": "女",
                "age": 26,
                "occupation": "访客",
                "appearance": "长脸、窄下颌、直发低马尾，体态修长，穿细棉衬衫。",
            },
        ],
    }


@pytest.fixture
def direction_model(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.config.LOCAL_DATA_DIR", tmp_path)
    monkeypatch.setattr(art, "create_editor_llm", lambda **_: object())

    async def generate(_llm, _schema, _system, material, **_kwargs):
        await asyncio.sleep(0)
        return art.PortraitDirection(
            background=material["description"],
            lighting="午后的自然柔光从玻璃顶棚照入。",
            palette="木色、植物绿与自然肤色。",
            rendering="细腻的水彩插画，纸张肌理轻柔。",
        )

    model = AsyncMock(side_effect=generate)
    monkeypatch.setattr(art, "invoke_structured", model)
    return model


@pytest.mark.asyncio
async def test_one_direction_survives_concurrency_restart_and_character_edits(direction_model):
    state = story()
    first, concurrent = await asyncio.gather(
        art.get_portrait_direction("story", state), art.get_portrait_direction("story", state)
    )
    assert first == concurrent
    assert direction_model.await_count == 1
    material = direction_model.call_args.args[3]
    assert "SECRET" not in json.dumps(material)

    # Drop all process-local state; the persisted brief is sufficient for a retry.
    art._locks.clear()
    state["characters"][0]["appearance"] = "更新后的外貌"
    state["final_draft"] += "变更私人终稿"
    assert await art.get_portrait_direction("story", state) == first
    assert direction_model.await_count == 1

    state["game_data_sections"]["description"] = "旧火车站的冬夜，候车厅只有暖黄吊灯。"
    changed = await art.get_portrait_direction("story", state)
    assert "旧火车站" in changed and changed != first
    assert direction_model.await_count == 2
    assert await art.get_portrait_direction("another-story", story()) != changed


@pytest.mark.asyncio
async def test_unavailable_text_model_uses_durable_context_fallback(direction_model):
    direction_model.side_effect = ValueError("text model unavailable")
    first = await art.get_portrait_direction("fallback", story())
    assert "玻璃花房" in first and "SECRET" not in first
    assert await art.get_portrait_direction("fallback", story()) == first
    assert direction_model.await_count == 1
    path = art.settings.image_dir / "scripts/fallback/portrait_direction.json"
    assert json.loads(path.read_text(encoding="utf-8"))["source"] == "public-context-fallback"


@pytest.mark.asyncio
async def test_legacy_empty_context_does_not_require_text_generation(direction_model):
    direction = await art.get_portrait_direction("legacy", {})
    assert "中性背景" in direction
    assert direction_model.await_count == 0


@pytest.mark.asyncio
async def test_account_recovery_does_not_publish_a_different_fallback(direction_model):
    direction_model.side_effect = InferenceRecoveryError("api_key_quota")
    with pytest.raises(InferenceRecoveryError, match="api_key_quota"):
        await art.get_portrait_direction("account-paused", story())
    assert not (art.settings.image_dir / "scripts/account-paused/portrait_direction.json").exists()


@pytest.mark.asyncio
async def test_corrupt_cache_is_repaired_before_image_dispatch(direction_model):
    root = art.settings.image_dir / "scripts/corrupt"
    root.mkdir(parents=True)
    (root / "portrait_direction.json").write_text("{broken", encoding="utf-8")
    assert "玻璃花房" in await art.get_portrait_direction("corrupt", story())
    assert direction_model.await_count == 1
    cached = json.loads((root / "portrait_direction.json").read_text(encoding="utf-8"))
    assert art.PortraitDirection.model_validate(cached["direction"])


@pytest.mark.asyncio
async def test_initial_batch_and_single_character_retry_use_identical_image_prompt(
    direction_model, tmp_path, monkeypatch
):
    state = story()
    sid = "batch-retry"
    prompts = []

    async def capture(prompt, path, size):
        prompts.append((prompt, path.name, size))
        return False  # Leave the tasks retryable without creating synthetic images.

    monkeypatch.setattr(image_gen, "IMAGE_ROOT", tmp_path / "images/scripts")
    monkeypatch.setattr(image_gen, "_generate_image", capture)
    registry.init(
        sid,
        [{"tasks": [{"id": i, "status": "pending"} for i in ("cover", "avatar_a", "avatar_b")]}],
    )
    try:
        await assets._run_images(
            sid, state, state["characters"], {"cover", "avatar_a", "avatar_b"}, False
        )
        shared = await art.get_portrait_direction(sid, state)
        assert len(prompts) == 3
        assert all(shared in prompt for prompt, _, _ in prompts)
        original = next(prompt for prompt, name, _ in prompts if name == "a.png")
        assert state["characters"][0]["appearance"] in original
        assert state["characters"][1]["appearance"] not in original
        assert "48岁" in original and "园艺师" in original
        assert all(
            "偏暗冷色调" not in prompt and "SECRET" not in prompt for prompt, _, _ in prompts
        )
        assert "中央30%" in next(prompt for prompt, name, _ in prompts if name == "cover.png")

        await assets.AssetGenerationService().retry(sid, "avatar_a", state)
        assert prompts[-1][0] == original
        assert direction_model.await_count == 1

        # Selected-role regeneration changes identity details, not the shared art.
        state["characters"][0]["appearance"] = "方脸、齐耳短发，穿深色棉麻工作衫。"
        await assets._run_images(sid, state, state["characters"], {"avatar_a"}, True)
        assert shared in prompts[-1][0] and prompts[-1][0] != original
        assert direction_model.await_count == 1
    finally:
        registry.reset(sid)


@pytest.mark.asyncio
async def test_persist_failure_marks_images_failed_instead_of_leaving_pending(monkeypatch):
    sid = "unwritable-direction"
    monkeypatch.setattr(assets, "get_portrait_direction", AsyncMock(side_effect=OSError()))
    registry.init(sid, [{"tasks": [{"id": "avatar_a", "status": "pending"}]}])
    try:
        await assets._run_images(sid, story(), story()["characters"], {"avatar_a"}, False)
        assert registry.snapshot(sid)["phases"][0]["tasks"][0]["status"] == "failed"
    finally:
        registry.reset(sid)


def test_scene_edits_select_whole_image_set_but_identity_edits_select_one(monkeypatch):
    state = story()
    state["script_id"] = "story"
    state["original_snapshot"] = {"asset_dependencies": asset_dependencies(state)}
    monkeypatch.setattr("app.script_editor.editing._artifact_missing", lambda *_: False)
    monkeypatch.setattr(type(art.settings), "get_api_key", lambda *_: "configured")

    identity_edit = deepcopy(state)
    identity_edit["characters"][0]["age"] = 60
    plan = prepare_asset_plan(identity_edit)["asset_plan"]
    assert {item["id"] for item in plan if item["default_selected"]} == {"avatar_a"}

    for field in ("overview", "description", "opening"):
        scene_edit = deepcopy(state)
        scene_edit["game_data_sections"][field] = "更新后的公开场景"
        plan = prepare_asset_plan(scene_edit)["asset_plan"]
        assert {item["id"] for item in plan if item["default_selected"]} == {
            "cover",
            "avatar_a",
            "avatar_b",
        }

    private_edit = deepcopy(state)
    private_edit["game_data_sections"]["full_truth"] = "修改真相"
    assert asset_dependencies(private_edit) == asset_dependencies(state)


@pytest.mark.asyncio
async def test_appearance_writer_sees_whole_cast_but_only_returns_its_batch(monkeypatch):
    characters = [
        {
            "character_id": str(i),
            "name": f"角色{i}",
            "gender": "女",
            "age": 20 + i * 5,
            "occupation": "访客",
            "character_script": "SECRET_PERSONAL_SCRIPT",
        }
        for i in range(6)
    ]
    seen = []

    async def generate(_llm, schema, _prompt, material, *, validate):
        seen.append(material)
        result = schema.model_validate(
            {
                "characters": [
                    {
                        "character_id": c["character_id"],
                        "profile": "公开简介",
                        "appearance": "人物细节",
                    }
                    for c in material["角色"]
                ]
            }
        )
        validate(result)
        return result

    monkeypatch.setattr(public_material, "invoke", generate)
    monkeypatch.setattr(public_material, "audience_material", lambda _: {"材料": ["公开场景"]})
    result = await public_material.public_character(
        None, {"disclosure_plan": {"characters": characters}}, characters[-1], "角色设计"
    )
    assert result.character_id == "5"
    assert [c["character_id"] for c in seen[0]["角色"]] == ["4", "5"]
    assert len(seen[0]["全剧公开角色"]) == 6
    assert "SECRET" not in json.dumps(seen[0])
