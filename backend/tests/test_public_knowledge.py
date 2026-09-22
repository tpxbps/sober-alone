from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from test_stage_boundaries import CaptureModel

from app.agents.agent_prompts import build_role_system_prompt
from app.agents.game_model_paths import build_role_agent
from app.agents.reaction import build_reaction_analysis_prompt
from app.db.models import GameSession
from app.game.clues import public_round_overviews
from app.game.flow_controller import GameFlowController
from app.services.voting import VotingService

STAGES = [
    {"stage": 1, "overview": "第一轮现场检查", "items": []},
    {"stage": 2, "overview": "重击后3至4小时死亡", "items": []},
    {"stage": 3, "overview": "尚未公布的检查", "items": []},
]


@pytest.mark.parametrize(
    "stage,round_num,expected",
    [
        ("intro", 2, []),
        ("clue_analysis", 1, [1]),
        ("free_discussion", 2, [1, 2]),
        ("summary", 2, [1, 2]),
        ("vote", 2, [1, 2]),
    ],
)
def test_overview_disclosure_uses_stage_and_round_without_requiring_items(
    stage, round_num, expected
):
    result = public_round_overviews(STAGES, stage, round_num)
    assert [item["stage"] for item in result] == expected
    assert "尚未公布" not in str(result)


@pytest.mark.parametrize("stage,round_num", [("summary", 3), ("vote", 3), ("review", 4)])
def test_tail_stage_counter_does_not_publish_an_orphan_future_round(stage, round_num):
    process = [{"type": t} for t in ("initial", "advancement", "advancement", "vote", "review")]
    result = public_round_overviews(STAGES, stage, round_num, game_process=process)
    assert [item["stage"] for item in result] == [1, 2]


@pytest.mark.asyncio
async def test_restored_controller_supplies_snapshot_overviews_to_speech_and_reaction():
    session = GameSession(
        session_id="s",
        script_id="p",
        current_stage="free_discussion",
        current_round=2,
        revealed_clues=[],
    )
    stages = [dict(s, items=[{"content": "本轮条目"}]) for s in STAGES]
    flow = GameFlowController(session, {"clue_stages": stages}, object())
    context = await flow._build_speech_context("a")
    assert "重击后3至4小时死亡" in context
    assert "尚未公布" not in context
    reaction = build_reaction_analysis_prompt(
        "甲",
        "乙",
        "我的推测",
        public_round_overviews=public_round_overviews(
            flow.clue_stages, session.current_stage, session.current_round
        ),
    )
    assert "重击后3至4小时死亡" in reaction
    assert "尚未公布" not in reaction


@pytest.mark.asyncio
async def test_actual_model_receives_overviews_with_no_items_and_after_agent_restore():
    model = CaptureModel()
    saver = InMemorySaver()
    kwargs = dict(
        system_prompt=build_role_system_prompt("甲", "自己的记忆", False),
        rag_enabled=False,
        checkpointer=saver,
        middleware=[],
    )
    config = {"configurable": {"thread_id": "overview-boundary"}}
    agent = build_role_agent(model, model, **kwargs)
    await agent.ainvoke(
        {
            "messages": [HumanMessage(content="自我介绍")],
            "current_stage": "intro",
            "public_round_overviews": STAGES,
        },
        config,
    )
    assert "重击后" not in str(model.calls[-1])
    agent = build_role_agent(model, model, **kwargs)
    for stage in ["clue_analysis", "free_discussion", "summary", "vote"]:
        await agent.ainvoke(
            {
                "messages": [HumanMessage(content="现在发言")],
                "current_stage": stage,
                "public_clues": [],
                "public_round_overviews": public_round_overviews(STAGES, stage, 2),
            },
            config,
        )
        messages, _ = model.calls[-1]
        system = messages[0].content
        assert "重击后3至4小时死亡" in system
        assert "尚未公布" not in str(messages)
        assert "借用不相关条目" in system


@pytest.mark.asyncio
async def test_vote_dispatch_explicitly_includes_latest_public_knowledge():
    captured = []

    class Agent:
        async def speak(self, state, stage):
            captured.append(state)
            yield None

    class DB:
        async def execute(self, _statement):
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    controller = SimpleNamespace(
        session=SimpleNamespace(
            session_id="s",
            script_id="p",
            current_round=2,
            revealed_clues=[{"id": "c01", "content": "公开条目"}],
        ),
        clue_stages=STAGES,
        characters=[{"character_id": "a", "name": "甲"}],
        agent_manager=SimpleNamespace(get_character_name=lambda _: "甲"),
    )
    await VotingService(DB()).collect_single_ai_vote(controller, "a", Agent())
    assert captured[0]["public_clues"][0]["id"] == "c01"
    assert [item["stage"] for item in captured[0]["public_round_overviews"]] == [1, 2]
