from copy import deepcopy
from types import SimpleNamespace

import pytest
from reliability_support import approve, valid_state

from app.script_editor.conversion import service
from app.script_editor.conversion.contracts import (
    ClueItemResult,
    ClueStageItem,
    ClueStagesResult,
    ScenesResult,
    ScriptMetadata,
    SingleCharacterResult,
)
from app.script_editor.editing import normalize_game_data
from app.script_editor.nodes.safety_check import (
    GENERIC_ERROR,
    SafetyResult,
    review_chunks,
    safety_approved,
    safety_check,
)
from app.script_editor.repositories.script_repository import ScriptRepository
from app.script_editor.services.workflow_service import ScriptEditorWorkflowService


def test_failure_interrupt_keeps_retry_action_in_api_response():
    value = {"step": "convert_to_game_data", "failed": True, "retry_step": "convert_to_game_data"}
    snapshot = SimpleNamespace(tasks=[SimpleNamespace(interrupts=[SimpleNamespace(value=value)])])
    result = ScriptEditorWorkflowService.extract_interrupt(snapshot)
    assert result["failed"] and result["retry_step"] == "convert_to_game_data"


@pytest.mark.asyncio
async def test_safety_covers_tail_short_text_and_new_clue_fields(monkeypatch):
    seen = []

    class Judge:
        def with_structured_output(self, *args, **kwargs):
            return self

        async def ainvoke(self, messages):
            text = messages[-1]["content"]
            seen.append(text)
            return (
                SafetyResult(status="FAIL", reason="尾部拒绝")
                if "TAIL_REJECT" in text
                else SafetyResult(status="PASS")
            )

    monkeypatch.setattr("app.core.llm_factory.create_llm", lambda **kwargs: Judge())
    state = {
        "game_data_sections": {
            "character_data": [{"character_script": "甲" * 7100 + "TAIL_REJECT"}],
            "clue_stages": [{"items": [{"content": "CLUE_MARKER"}]}],
            "description": "短文本",
        }
    }
    result = await safety_check(state)
    assert not result["safety_passed"] and "尾部拒绝" in result["safety_rejection_reason"]
    assert any("CLUE_MARKER" in text for text in seen)
    assert any("短文本" in text for text in seen)
    assert all(len(chunk["text"]) <= 6000 for chunk in review_chunks(state["game_data_sections"]))
    pieces = [
        chunk
        for chunk in review_chunks(state["game_data_sections"])
        if "character_script" in chunk["field"]
    ]
    assert pieces[1]["start"] == pieces[0]["start"] + len(pieces[0]["text"]) - 300
    assert pieces[-1]["text"].endswith("TAIL_REJECT")


@pytest.mark.asyncio
async def test_short_safety_checks_call_model_and_content_changes_invalidate_pass(monkeypatch):
    calls = []

    class Judge:
        def with_structured_output(self, *args, **kwargs):
            return self

        async def ainvoke(self, messages):
            calls.append(messages)
            return SafetyResult(status="PASS")

    monkeypatch.setattr("app.core.llm_factory.create_llm", lambda **kwargs: Judge())
    state = {"game_data_sections": {"description": "字"}}
    state.update(await safety_check(state))
    assert len(calls) == 1 and safety_approved(state)
    state["game_data_sections"]["description"] = "改"
    assert not safety_approved(state)
    state.update(await safety_check({"game_data_sections": {}}))
    assert not state["safety_passed"]


def test_explicit_empty_text_cannot_borrow_legacy_field_to_pass_validation():
    state = valid_state()
    state["game_data_sections"]["character_data"][0]["character_script"] = ""
    assert normalize_game_data(state)["data_validation_errors"]


@pytest.mark.asyncio
async def test_direct_save_requires_current_quality_and_safety_checks():
    state = valid_state()
    assert (await ScriptRepository.save_generated_script(state))["error_message"]
    approve(state)
    state["game_data_sections"]["character_data"][0]["character_script"] += "新增内容"
    assert (await ScriptRepository.save_generated_script(state))["error_message"]


def test_missing_scenes_never_publish_outline():
    with pytest.raises(ValueError):
        service._merge_game_process(None, None, 1, "标题", "真凶秘密", "s")


@pytest.mark.asyncio
async def test_conversion_retries_only_failed_tasks_and_preserves_successes(monkeypatch):
    counts = {"scenes": 0, "clues": 0, "metadata": 0, "characters": 0}

    async def no_sleep(*args):
        pass

    monkeypatch.setattr(service.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(service, "_get_structured_llm", lambda: None)

    async def scenes(*args):
        counts["scenes"] += 1
        if counts["scenes"] <= 3:
            return None
        return ScenesResult(
            opening_notice="公开开场",
            summary_notice="总结",
            vote_notice="投票",
            truth_reveal_notice="揭晓",
            full_truth="真相",
        )

    async def clues(*args):
        counts["clues"] += 1
        return ClueStagesResult(
            clue_stages=[
                ClueStageItem(
                    overview="线索",
                    items=[ClueItemResult(summary="痕迹", content="脚印")],
                    free_discussion_notice="讨论",
                )
            ],
            free_speech_limits=[2],
        )

    async def metadata(*args):
        counts["metadata"] += 1
        return ScriptMetadata(overview="公开概述", description="公开描述", tags="悬疑")

    async def character(_llm, _sid, char, *_args):
        counts["characters"] += 1
        return char["name"], SingleCharacterResult(
            name=char["name"],
            character_script="私人经历",
            system_prompt="角色提示",
            profile="简介",
            appearance="外貌",
            script_summary="摘要",
            step_voice_id="wenrounansheng",
        )

    for name, function in [
        ("_run_game_scenes", scenes),
        ("_run_game_clues", clues),
        ("_run_metadata", metadata),
        ("_run_character", character),
    ]:
        monkeypatch.setattr(service, name, function)
    state = valid_state()
    state["num_clue_rounds"] = 1
    state["final_draft"] = "终稿"
    first = await service.convert_to_game_data(deepcopy(state))
    assert first["error_message"] == GENERIC_ERROR and counts["scenes"] == 3
    assert "game_data_sections" not in first
    second = await service.convert_to_game_data({**state, **first})
    assert second["error_message"] == ""
    assert counts == {"scenes": 4, "clues": 1, "metadata": 1, "characters": 2}
    assert second["game_data_sections"]["opening"] == "公开开场"
