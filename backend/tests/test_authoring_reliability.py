import json
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
    SafetyBatchResult,
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
            return SafetyBatchResult(
                results=[
                    {
                        "id": item["id"],
                        "status": "FAIL" if "TAIL_REJECT" in item["text"] else "PASS",
                        "reason": "尾部拒绝" if "TAIL_REJECT" in item["text"] else "",
                    }
                    for item in json.loads(text)["items"]
                ]
            )

    monkeypatch.setattr("app.script_editor.llm.create_llm", lambda **kwargs: Judge())
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
            return SafetyBatchResult(
                results=[
                    {"id": item["id"], "status": "PASS"}
                    for item in json.loads(messages[-1]["content"])["items"]
                ]
            )

    monkeypatch.setattr("app.script_editor.llm.create_llm", lambda **kwargs: Judge())
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
@pytest.mark.parametrize("restart", [False, True])
async def test_conversion_retries_only_failed_tasks_and_preserves_successes(monkeypatch, restart):
    counts = {"scenes": 0, "clues": 0, "metadata": 0, "characters": 0}

    async def no_sleep(*args):
        pass

    monkeypatch.setattr(service.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(service, "_get_structured_llm", lambda: None)

    async def plan(_llm, state):
        return {"characters": state["characters"], "facts": []}

    monkeypatch.setattr(service, "extract_plan", plan)

    async def scenes(*args):
        counts["scenes"] += 1
        if counts["scenes"] <= 1:
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
    assert first["workflow_error"]["scope"] == "task" and counts["scenes"] == 1
    assert "未知错误" not in first["error_message"]
    assert "game_data_sections" not in first
    from app.script_editor.outline.runtime import current_runtime

    runtime = SimpleNamespace(
        convert_cache=first["convert_cache"],
        queue_progress=lambda *_: None,
        drain_progress=no_sleep,
    )
    token = current_runtime.set(runtime) if restart else None
    try:
        second = await service.convert_to_game_data(state if restart else {**state, **first})
    finally:
        if token is not None:
            current_runtime.reset(token)
    assert second["error_message"] == ""
    assert counts == {"scenes": 2, "clues": 1, "metadata": 1, "characters": 2}
    assert second["game_data_sections"]["opening"] == "公开开场"


@pytest.mark.parametrize("notice", [None, "", "   "])
def test_generated_clue_discussion_is_executable_when_notice_omitted(notice):
    payload = {"items": [{"summary": "窗边划痕", "content": "窗边留有一道划痕。"}]}
    if notice is not None:
        payload["free_discussion_notice"] = notice
    clues = ClueStagesResult(clue_stages=[ClueStageItem.model_validate(payload)])
    process, _, _, _, stages = service._merge_game_process(
        clues, ScenesResult(opening_notice="开场"), 1, "标题", "大纲", "test-script"
    )
    assert stages[0]["free_discussion_notice"] == "请结合已公开的线索自由讨论。"
    assert process[1]["children"][1]["system_notice"] == stages[0]["free_discussion_notice"]
