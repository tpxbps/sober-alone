import json
from types import SimpleNamespace

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from app.agents.agent_prompts import build_role_system_prompt
from app.agents.game_model_paths import build_role_agent
from app.game.citation_stream import CitationStreamFilter
from app.game.clues import parse_clue_citations
from app.services.game_speech import GameSpeechService

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
            "public_clues": CLUES,
        },
        config,
    )
    messages, tools = model.calls[-1]
    combined = "\n".join(str(message.content) for message in messages)
    assert "[c07]" in combined and "门锁没有撬动痕迹" in combined
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
            "c99 says no; c07 says yes. abc01test C01芯片",
            " says no; [c07] says yes. abc01test C01芯片",
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
    result = stream.feed("[" + "普通文字" * 200)
    assert result
    assert len(stream.pending) < stream.MAX_PENDING


@pytest.mark.asyncio
async def test_intro_sse_and_persisted_content_use_the_same_empty_permission_set():
    stored = []

    class Controller:
        session = SimpleNamespace(current_stage="intro", revealed_clues=CLUES)

        async def generate_ai_speech(self, *_args):
            for text in ["我是馆长。", "[c", "07]", "我负责保管钥匙。"]:
                yield {"type": "token", "text": text}

        async def process_speech(self, **kwargs):
            stored.append(kwargs["content"])
            return {"next_speaker": "human"}

    async def ensure(*_args):
        return Controller()

    frames = [
        json.loads(frame.removeprefix("data: "))
        async for frame in GameSpeechService(object(), ensure).stream_ai("scope", "ai")
    ]
    text = "".join(frame["text"] for frame in frames if frame["type"] == "token")
    assert text == "我是馆长。我负责保管钥匙。"
    assert stored == [text]
    assert [frame["type"] for frame in frames][-2:] == ["speech_done", "done"]


def test_human_untrusted_tags_remain_text_without_reference_permission():
    content = "我记下了 [c99] 和 [某物](#clue-ref-c88)。"
    text, refs, unknown = parse_clue_citations(content, [], strip_unknown=False)
    assert text == content
    assert refs == []
    assert set(unknown) == {"c99", "c88"}
