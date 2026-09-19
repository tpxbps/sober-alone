from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from test_script_editing import completed_script
from test_state_reliability import game as base_game

from app.db.models import GameRecord, GameSession
from app.game.clue_media import public_presentation, upcoming_presentation_assets
from app.game.clues import normalize_clue_stages
from app.game.content_quality import content_fingerprint
from app.game.flow_controller import GameFlowController
from app.script_editor.editing import hydrate_completed_script, normalize_game_data
from app.services import game_service as module
from app.services.game_runtime import build_runtime_snapshot
from app.services.game_service import GameService

game = base_game


def stages():
    return normalize_clue_stages(
        [
            {
                "stage": 1,
                "overview": "公开材料",
                "free_discussion_notice": "开始讨论",
                "items": [
                    {
                        "id": "c01",
                        "summary": "纸条",
                        "content": "尚未核实的文字",
                        "media": {
                            "image_url": "/images/scripts/test/paper.webp",
                            "thumbnail_url": "/images/scripts/test/paper-small.webp",
                            "alt": "场景示意",
                        },
                    }
                ],
                "presentation": {
                    "version": 1,
                    "revision": "art-v1",
                    "template": "cinematic",
                    "title": "纸上的痕迹",
                    "shots": [
                        {"id": "paper", "title": "原件", "duration_ms": 3000, "clue_ids": ["c01"]}
                    ],
                },
            }
        ],
        script_id="s",
    )


def test_media_snapshot_and_text_fingerprint_are_independent():
    data = {"script_id": "s", "clue_stages": stages()}
    before = content_fingerprint(data)
    snapshot = build_runtime_snapshot(data)
    changed = deepcopy(data)
    changed["clue_stages"][0]["items"][0]["media"]["image_url"] = "/images/new.webp"
    changed["clue_stages"][0]["presentation"]["revision"] = "art-v2"
    assert content_fingerprint(changed) == before
    assert snapshot["clue_stages"][0]["presentation"]["revision"] == "art-v1"
    changed["clue_stages"][0]["items"][0]["content"] += "正文变更"
    normalized = normalize_clue_stages(changed["clue_stages"], script_id="s")
    assert normalized[0]["items"][0]["media"]["status"] == "needs_review"
    assert normalized[0]["presentation"]["status"] == "needs_review"
    assert snapshot["clue_stages"][0]["presentation"]["status"] == "ready"
    assert content_fingerprint(changed) != before


def test_continuous_presentation_survives_normalization_and_snapshot():
    data = stages()
    data[0]["presentation"]["version"] = 2
    normalized = normalize_clue_stages(data, script_id="s")
    snapshot = build_runtime_snapshot({"script_id": "s", "clue_stages": normalized})
    assert snapshot["clue_stages"][0]["presentation"]["version"] == 2
    assert snapshot["clue_stages"][0]["presentation"]["status"] == "ready"


@pytest.mark.parametrize("preset", ["warm-noir", "cold-occlusion"])
@pytest.mark.parametrize("composition", ["pan", "detail", "pair", "occlusion", "light"])
def test_visual_directions_survive_editor_and_snapshot(preset, composition):
    script, characters = completed_script()
    script.clue_stages = stages()
    before = content_fingerprint({"clue_stages": script.clue_stages})
    config = script.clue_stages[0]["presentation"]
    config.update(version=2, visual_preset=preset)
    config["shots"][0]["composition"] = composition
    state = hydrate_completed_script(script, characters, "")
    result = normalize_game_data(state)
    assert result.get("data_validation_errors") == []
    snapshot = build_runtime_snapshot(result)
    saved = snapshot["clue_stages"][0]["presentation"]
    assert saved["visual_preset"] == preset
    assert saved["shots"][0]["composition"] == composition
    assert content_fingerprint({"clue_stages": snapshot["clue_stages"]}) == before


@pytest.mark.parametrize("field,value", [("visual_preset", "custom-script"), ("composition", "url(javascript:run())")])
def test_visual_directions_reject_untrusted_styles(field, value):
    data = stages()
    config = data[0]["presentation"]
    target = config["shots"][0] if field == "composition" else config
    target[field] = value
    with pytest.raises(ValueError):
        normalize_clue_stages(data, script_id="s")


def test_editor_preserves_omitted_media_and_marks_changes_for_review():
    script, characters = completed_script()
    script.clue_stages = stages()
    state = hydrate_completed_script(script, characters, "")
    stage = state["game_data_sections"]["clue_stages"][0]
    del stage["presentation"]
    del stage["items"][0]["media"]
    stage["items"][0]["content"] = "修改了正文"
    result = normalize_game_data(state)
    assert result.get("data_validation_errors") == []
    result_stage = result["clue_stages"][0]
    assert result_stage["presentation"]["status"] == "needs_review"
    assert result_stage["items"][0]["media"]["status"] == "needs_review"


def test_reject_future_clues_and_executable_media():
    data = stages()
    data[0]["presentation"]["shots"][0]["clue_ids"] = ["c99"]
    with pytest.raises(ValueError, match="未公开"):
        normalize_clue_stages(data, script_id="s")
    data = stages()
    data[0]["items"][0]["media"]["image_url"] = "javascript:alert(1)"
    with pytest.raises(ValueError):
        normalize_clue_stages(data, script_id="s")


def test_corrupt_or_newer_presentation_can_restore_to_summary():
    data = stages()
    data[0]["presentation"]["version"] = 99
    with pytest.raises(ValueError):
        normalize_clue_stages(data, script_id="s")
    recovered = normalize_clue_stages(data, script_id="s", strict_media=False)
    assert recovered[0]["presentation"]["status"] == "unavailable"
    assert recovered[0]["items"][0]["content"] == data[0]["items"][0]["content"]


async def configure(db, old, monkeypatch, *, presentation=True):
    old.session.current_stage = "intro"
    old.session.current_round = 0
    old.session.speech_queue = []
    data = {
        "script_id": "s",
        "characters": old.characters,
        "clue_stages": stages(),
        "game_full_process": [
            {"type": "initial", "system_notice": "开场"},
            {
                "type": "advancement",
                "children": [{"system_notice": "材料"}, {"system_notice": "讨论"}],
            },
            {
                "type": "advancement",
                "children": [{"system_notice": "下一轮"}, {"system_notice": "讨论"}],
            },
        ],
    }
    data["clue_stages"].append(
        {
            "stage": 2,
            "overview": "后续",
            "items": [{"id": "c02", "summary": "未来", "content": "未公开"}],
        }
    )
    if not presentation:
        del data["clue_stages"][0]["presentation"]
    old.session.runtime_snapshot = build_runtime_snapshot(data)
    await db.commit()
    controller = GameFlowController(old.session, data, old.agent_manager)
    monkeypatch.setattr(module, "ensure_flow_controller", AsyncMock(return_value=controller))
    monkeypatch.setattr(module, "get_flow_controller", lambda _: controller)
    return controller, GameService(db)


@pytest.mark.asyncio
async def test_gate_blocks_all_speech_and_advance_until_idempotent_ack(game, monkeypatch):
    db, old = game
    controller, service = await configure(db, old, monkeypatch)
    result = await service.advance_stage("g")
    assert result["success"]
    state = result["clue_presentation"]
    assert state["status"] == "pending"
    assert [c["id"] for c in state["clues"]] == ["c01"]
    assert "未公开" not in str(state)
    assert controller.session.current_speaker is None
    assert controller.session.speech_queue == ["human", "a", "b"]
    assert len(list((await db.scalars(select(GameRecord))).all())) == 1
    controller.agent_manager.broadcast_speech = AsyncMock(side_effect=AssertionError("AI called"))
    controller.generate_ai_speech_stream = AsyncMock(side_effect=AssertionError("AI called"))
    assert not (await service.advance_stage("g"))["success"]
    assert not (await service.process_human_speech("g", "提前说话"))["success"]
    assert not (await controller.process_speech("human", "直接入口", is_human=True, db_session=db))[
        "success"
    ]
    for cid in ("a", "human"):
        events = [event async for event in service.process_ai_speech_stream("g", cid)]
        assert "clue_presentation_pending" in "".join(events)
    events = [event async for event in service.process_human_speech_stream("g", "提前说话")]
    assert "clue_presentation_pending" in "".join(events)
    assert controller.agent_manager.broadcast_speech.await_count == 0
    assert not (await service.acknowledge_clue_presentation("g", "expired"))["success"]
    # Restore a controller from the persisted session, just as a reload/restart does.
    restored = GameFlowController(
        await db.get(GameSession, "g"), controller.script_data, controller.agent_manager
    )
    assert public_presentation(restored.session, restored.clue_stages)["status"] == "pending"
    monkeypatch.setattr(service, "get_game_state", AsyncMock(return_value={"success": True}))
    await service.acknowledge_clue_presentation("g", state["presentation_id"])
    assert controller.session.current_speaker == "human"
    controller.session.current_speaker = "a"
    await db.commit()
    await service.acknowledge_clue_presentation("g", state["presentation_id"])
    assert controller.session.current_speaker == "a"  # A repeated ack must not restart the queue.
    assert controller.session.clue_presentation_state["status"] == "acknowledged"


@pytest.mark.asyncio
async def test_scripts_without_presentation_keep_existing_flow(game, monkeypatch):
    db, old = game
    controller, service = await configure(db, old, monkeypatch, presentation=False)
    result = await service.advance_stage("g")
    assert result["success"] and result["clue_presentation"] is None
    assert controller.session.current_speaker == "human"


@pytest.mark.asyncio
async def test_reveal_and_gate_roll_back_with_announcement(game, monkeypatch):
    db, old = game
    _, service = await configure(db, old, monkeypatch)
    monkeypatch.setattr(db, "commit", AsyncMock(side_effect=RuntimeError("write failed")))
    result = await service.advance_stage("g")
    assert not result["success"]
    db.expire_all()
    session = await db.get(GameSession, "g")
    assert session.current_stage == "intro" and session.current_round == 0
    assert not session.clue_presentation_state and not session.revealed_clues
    assert list((await db.scalars(select(GameRecord))).all()) == []


def test_prefetch_exposes_only_next_round_image_urls_from_snapshot():
    data = stages()
    second = deepcopy(data[0])
    second["stage"] = 2
    second["items"][0].update(id="c02", content="未公开正文")
    second["items"][0]["media"]["image_url"] = "/images/second.webp"
    second["presentation"]["shots"][0]["clue_ids"] = ["c01", "c02"]
    data.append(second)
    session = SimpleNamespace(
        current_stage="intro", revealed_clues=[], clue_presentation_state=None
    )
    assert upcoming_presentation_assets(session, data) == ["/images/scripts/test/paper.webp"]
    session.revealed_clues = data[0]["items"]
    session.current_stage = "clue_analysis"
    session.clue_presentation_state = {"status": "pending", "round": 1}
    assert upcoming_presentation_assets(session, data) == []
    session.clue_presentation_state["status"] = "acknowledged"
    assert upcoming_presentation_assets(session, data) == [
        "/images/scripts/test/paper.webp",
        "/images/second.webp",
    ]
    assert len(public_presentation(session, data)["reference_clues"]) == 1
    second["presentation"]["status"] = "needs_review"
    assert upcoming_presentation_assets(session, data) == []
    second["presentation"]["status"] = "ready"
    session.revealed_clues += second["items"]
    assert upcoming_presentation_assets(session, data) == []
    session.revealed_clues = []
    session.current_stage = "review"
    assert upcoming_presentation_assets(session, data) == []
