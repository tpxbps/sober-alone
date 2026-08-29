from app.script_editor.conversion.contracts import ClueItemResult, ClueStageItem, ClueStagesResult
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
        None,
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
    assert full_truth == ""
    assert truth_notice == "游戏结束！揭晓真相..."
