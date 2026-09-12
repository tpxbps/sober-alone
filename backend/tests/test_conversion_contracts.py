import pytest

from app.script_editor.conversion.contracts import (
    ClueItemResult,
    ClueStageItem,
    ClueStagesResult,
    ScenesResult,
)
from app.script_editor.conversion.service import _merge_game_process


def test_conversion_merge_preserves_round_task_shape_and_limits():
    clues = ClueStagesResult(
        clue_stages=[
            ClueStageItem(
                overview="第一轮总述",
                items=[ClueItemResult(summary="现场痕迹", content="第一轮线索")],
                free_discussion_notice="第一轮讨论",
            ),
            ClueStageItem(
                overview="第二轮总述",
                items=[ClueItemResult(summary="证人证言", content="第二轮线索")],
                free_discussion_notice="第二轮讨论",
            ),
        ],
        free_speech_limits=[0, 9],
    )

    process, limits, full_truth, truth_notice, clue_stages = _merge_game_process(
        clues,
        ScenesResult(
            opening_notice="公开开场",
            summary_notice="总结",
            vote_notice="投票",
            truth_reveal_notice="真相揭晓",
            full_truth="真相",
        ),
        num_rounds=2,
        script_title="零点来电",
        outline="广播站旧址的最后一夜。",
        script_id="script-test",
    )

    assert [stage["type"] for stage in process] == [
        "initial",
        "advancement",
        "advancement",
        "vote",
        "review",
    ]
    assert limits == [1, 3]
    assert "第一轮总述" in process[1]["children"][0]["system_notice"]
    assert "第一轮线索" in process[1]["children"][0]["system_notice"]
    assert clue_stages[0]["items"][0]["id"] == "c01"
    assert full_truth == "真相"
    assert truth_notice == "真相揭晓"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "manual",
    [
        None,
        {
            "mode": "multiple",
            "culprit_character_id": "a",
            "branches": [{"when": "tie", "title": "平票", "text": "人工填写的后续"}],
        },
    ],
)
async def test_conversion_defaults_single_and_preserves_manual_endings(monkeypatch, manual):
    from app.script_editor.conversion import service
    from app.script_editor.conversion.contracts import ScriptMetadata, SingleCharacterResult

    async def clues(*_):
        return ClueStagesResult(
            clue_stages=[ClueStageItem(items=[ClueItemResult(summary="痕迹", content="证据")])]
        )

    async def scenes(*_):
        return ScenesResult(
            opening_notice="开场",
            summary_notice="总结",
            vote_notice="投票",
            full_truth="固定案件真相",
            truth_reveal_notice="揭晓正文",
        )

    async def metadata(*_):
        return ScriptMetadata(overview="概述", description="详情")

    async def character(*_):
        return "甲", SingleCharacterResult(
            name="甲", character_script="个人剧本", system_prompt="人物设定"
        )

    monkeypatch.setattr(service, "_get_structured_llm", lambda: None)
    monkeypatch.setattr(service, "_run_game_clues", clues)
    monkeypatch.setattr(service, "_run_game_scenes", scenes)
    monkeypatch.setattr(service, "_run_metadata", metadata)
    monkeypatch.setattr(service, "_run_character", character)
    result = await service.convert_to_game_data(
        {
            "script_id": "ending-conversion",
            "num_clue_rounds": 1,
            "player_count": 1,
            "ending_mode": "multiple",
            "characters": [{"character_id": "a", "name": "甲"}],
            "game_data_sections": {"ending_config": manual},
        }
    )
    assert result["ending_config"] == manual
    assert result["game_data_sections"]["ending_config"] == manual
    assert "ending_branches" not in ScenesResult.model_fields


def test_creation_prompts_do_not_advertise_optional_runtime_endings():
    from app.game.content_quality import GAMEPLAY_CONTRACT
    from app.script_editor.prompts.defaults import DEFAULT_PROMPTS
    from app.script_editor.prompts.templates import get_prompt

    assert "四种结果展示不同后续结局" in GAMEPLAY_CONTRACT
    for step in DEFAULT_PROMPTS:
        assert "可选择单结局" not in get_prompt(step, {})
        old_saved = {
            "ending_mode": "multiple",
            "prompts": {step: GAMEPLAY_CONTRACT + "\n保留自定义故事要求"},
        }
        prompt = get_prompt(step, old_saved)
        assert "四种结果展示不同后续结局" not in prompt
        assert "保留自定义故事要求" in prompt
        assert "单一结局" in prompt
