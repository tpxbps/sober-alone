import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field
from test_state_reliability import game as base_game

from app.agents.agent_prompts import build_role_system_prompt
from app.agents.game_model_paths import build_role_agent
from app.game.citation_stream import CitationStreamFilter
from app.game.clues import parse_clue_citations

game = base_game

CLUES = [{"id": "c07", "summary": "门锁", "content": "门锁没有撬动痕迹", "stage": 1}]


class CaptureModel(BaseChatModel):
    calls: list = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "offline-boundary-test"

    def bind_tools(self, tools, **kwargs):
        return self.bind(tools=tools, **kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append((messages, kwargs.get("tools", [])))
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="我会如实介绍自己。"))]
        )


@pytest.mark.asyncio
async def test_actual_model_payload_is_stage_scoped_even_after_checkpoint_restore():
    model = CaptureModel()
    prompt = build_role_system_prompt("我是馆长", "我知道钥匙由我保管", False)
    saver = InMemorySaver()
    agent = build_role_agent(
        model, model, system_prompt=prompt, rag_enabled=False, checkpointer=saver, middleware=[]
    )
    config = {"configurable": {"thread_id": "stage-test"}}
    state = {
        "messages": [HumanMessage(content="请自我介绍。过去的无效标签 [c01]。")],
        "current_stage": "intro",
        "public_clues": CLUES,
    }
    await agent.ainvoke(state, config)
    messages, tools = model.calls[-1]
    combined = "\n".join(str(message.content) for message in messages)
    assert "钥匙由我保管" in combined
    assert "c01" not in combined
    assert "c07" not in combined
    assert "门锁没有撬动痕迹" not in combined
    assert "recall_public_clues" not in combined
    assert tools == []

    # Rebuild the agent using its existing checkpoint; policy is evaluated afresh.
    agent = build_role_agent(
        model, model, system_prompt=prompt, rag_enabled=False, checkpointer=saver, middleware=[]
    )
    await agent.ainvoke(
        {
            "messages": [HumanMessage(content="现在分析已经公开的证据。")],
            "current_stage": "clue_analysis",
            "public_clues": [
                *CLUES,
                {"id": "c08", "summary": "窗台", "content": "窗台有泥土", "stage": 1},
            ],
        },
        config,
    )
    messages, tools = model.calls[-1]
    combined = "\n".join(str(message.content) for message in messages)
    assert "[c07]" in combined and "门锁没有撬动痕迹" in combined
    assert "例如，直接点名" in combined
    assert "[你自己的完整推理][c07,c08]" in combined
    assert "[门锁没有撬动痕迹][c07]" in combined
    assert {tool.name for tool in tools} == {"recall_public_clues", "update_role_reaction"}
    assert "[c01]" not in combined


@pytest.mark.parametrize(
    "content,expected",
    [
        ("普通正文立即可见。", "普通正文立即可见。"),
        ("甲[c99]乙[c07]丙", "甲乙[c07]丙"),
        ("甲`[c99]`乙`[c07]`丙", "甲乙[c07]丙"),
        ("甲[门锁](#clue-ref-c99)乙", "甲门锁乙"),
        ("甲[门锁](#clue-ref-c07)乙", "甲[c07]乙"),
        (
            "c99 says no; c07 says yes. abc01test C01A芯片",
            " says no; [c07] says yes. abc01test C01A芯片",
        ),
        (
            "中文\n\n**强调** [普通链接](https://example.test) 尾声",
            "中文\n\n**强调** [普通链接](https://example.test) 尾声",
        ),
        ("甲[clue-aaaaaaaaaaaa]乙", "甲乙"),
        ("甲[c", "甲[c"),
    ],
)
def test_stream_filter_is_independent_of_token_boundaries(content, expected):
    for split in range(len(content) + 1):
        stream = CitationStreamFilter(CLUES)
        result = stream.feed(content[:split]) + stream.feed(content[split:]) + stream.finish()
        assert result == expected, (split, result)
    stream = CitationStreamFilter(CLUES)
    result = "".join(stream.feed(char) for char in content) + stream.finish()
    assert result == expected


def test_stream_filter_does_not_hold_prose_or_unbounded_brackets():
    stream = CitationStreamFilter([])
    assert stream.feed("直接输出正文。") == "直接输出正文。"
    result = stream.feed("[" + "普通文字" * stream.MAX_PENDING)
    assert result
    assert len(stream.pending) < stream.MAX_PENDING


@pytest.mark.asyncio
async def test_intro_sse_and_persisted_content_use_the_same_empty_permission_set(turns):
    import asyncio

    from app.db.models import GameSession

    async with turns.factory() as db:
        session = await db.get(GameSession, "game")
        session.revealed_clues = CLUES
        await db.commit()
    turns.chunks = ["我是馆长。[c07]", "我负责保管钥匙。"]
    turns.text_gate.set()
    turns.reaction_gate.set()
    await turns.runner.start("game", "ai", "ai", request_id="scope")
    async with asyncio.timeout(5):
        while True:
            turn, record = await turns.runner.snapshot("game", "scope")
            if turn["status"] == "completed":
                break
            await asyncio.sleep(0.01)
    assert turn["content"] == "我是馆长。我负责保管钥匙。"
    assert record["content"] == turn["content"]
    assert record["clue_refs"] == []


def test_human_untrusted_tags_remain_text_without_reference_permission():
    content = "我记下了 [c99] 和 [某物](#clue-ref-c88)。"
    text, refs, unknown = parse_clue_citations(content, [], strip_unknown=False)
    assert text == content
    assert refs == []
    assert set(unknown) == {"c99", "c88"}
