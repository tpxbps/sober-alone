from types import SimpleNamespace

import pytest

from app.game.flow_controller import GameFlowController
from app.services.voting import VotingService


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["summary", "vote"])
@pytest.mark.parametrize("objective", ["请选出持卡者。", "请指认凶手。"])
async def test_vote_objective_reaches_agent_without_truth(stage, objective):
    controller = object.__new__(GameFlowController)
    controller.session = SimpleNamespace(current_stage=stage, current_round=0, revealed_clues=[])
    controller.clue_stages = []
    controller.current_process_index = 0
    controller.game_process = [
        {
            "type": "vote",
            "children": [
                {"system_notice": "请总结你的判断。"},
                {"system_notice": objective},
            ],
        },
        {"type": "review", "system_notice": "秘密答案"},
    ]
    context = await controller._build_speech_context("player")
    assert objective in context
    assert "秘密答案" not in context
    assert ("请总结你的判断。" in context) == (stage == "summary")


def test_unanimous_result_reports_choice_not_guilt():
    votes = {"a": {"suspect_id": "b", "suspect_name": "持卡人", "reasoning": "读卡记录"}}
    result = VotingService.summarize(votes)
    message = VotingService().build_review_message(result, {"full_truth": "死者自尽。"})
    assert "大家一致投票给「持卡人」" in message
    assert "为凶手" not in message
    assert "死者自尽。" in message
