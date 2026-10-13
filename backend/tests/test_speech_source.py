"""Exercise source metadata through the real agent graph, without provider calls."""

import json

import httpx
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_stream_writer
from pydantic import Field

from app.agents import game_model_paths as paths


class ScriptedModel(BaseChatModel):
    summary: bool = False
    fail_once: bool = False
    calls: list = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "source-boundary-test"

    def bind_tools(self, tools, **kwargs):
        return self.bind(tools=tools, **kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="摘要秘密"))])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        if self.fail_once:
            self.fail_once = False
            raise httpx.ReadError("synthetic transport failure before first token")
        if self.summary:
            yield ChatGenerationChunk(message=AIMessageChunk(content="摘要秘密"))
        elif not any(isinstance(message, ToolMessage) for message in messages[-2:]):
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": "recall_public_clues",
                            "args": json.dumps({"clue_id": "c01"}),
                            "id": "lookup",
                            "index": 0,
                        }
                    ],
                )
            )
        else:
            for text in ["门禁记录", "不能证明离开。", "[c01]"]:
                yield ChatGenerationChunk(message=AIMessageChunk(content=text))


@pytest.mark.asyncio
@pytest.mark.parametrize("retry", [False, True])
async def test_real_graph_summary_tool_progress_and_checkpoint_keep_role_text(monkeypatch, retry):
    @tool
    def recall_public_clues(clue_id: str) -> str:
        """Read a public clue."""
        get_stream_writer()({"message": "正在核对线索"})
        return "门禁不能证明离开"

    monkeypatch.setattr(paths, "get_tools", lambda **_: [recall_public_clues])
    monkeypatch.setattr(paths, "SUMMARY_TRIGGER_TOKENS", 1)
    role = ScriptedModel(fail_once=retry)
    summary, saver = ScriptedModel(summary=True), InMemorySaver()
    config = {"configurable": {"thread_id": "source-test"}}
    history = []
    for i in range(15):
        history.extend([HumanMessage(content=f"问题{i}"), AIMessage(content=f"回答{i}")])
    state = {
        "messages": [*history, HumanMessage(content="核对线索")],
        "current_stage": "clue_analysis",
        "public_clues": [{"id": "c01", "summary": "门禁", "content": "门禁记录", "stage": 1}],
    }
    # Rebuilding against the same saver exercises the restored graph too.
    for attempt in range(2):
        agent = paths.build_role_agent(
            role,
            summary,
            system_prompt="角色发言",
            rag_enabled=False,
            checkpointer=saver,
            middleware=[],
        )
        if retry and attempt == 0:
            with pytest.raises(httpx.ReadError):
                async for _ in agent.astream(
                    state,
                    {"configurable": {"thread_id": "failed-isolated-attempt"}},
                    stream_mode=["messages", "custom"],
                ):
                    pass
            assert len(role.calls) == 1  # no hidden middleware retry
        events = [
            event
            async for event in agent.astream(
                state if attempt == 0 else {"messages": [HumanMessage(content="再次核对")]},
                config,
                stream_mode=["messages", "custom"],
            )
        ]
        messages = [data for mode, data in events if mode == "messages"]
        nodes = {meta["langgraph_node"] for _, meta in messages}
        assert "model" in nodes
        assert "SummarizationMiddleware.before_model" in nodes
        assert any("摘要秘密" in token.text for token, _ in messages)
        visible = [
            text for token, meta in messages for text in paths.visible_role_speech_text(token, meta)
        ]
        assert visible == ["门禁记录", "不能证明离开。", "[c01]"]
        assert any(mode == "custom" for mode, _ in events)
        checkpoint = await agent.aget_state(config)
        assert any("摘要秘密" in msg.text for msg in checkpoint.values["messages"])
        assert any(isinstance(msg, ToolMessage) for msg in checkpoint.values["messages"])
    assert len(role.calls) == 4 + int(retry)


@pytest.mark.parametrize(
    "metadata",
    [{}, {"langgraph_node": "tools"}, {"langgraph_node": "SummarizationMiddleware.before_model"}],
)
def test_unattributed_or_internal_text_is_not_public(metadata):
    assert paths.visible_role_speech_text(AIMessageChunk(content="内部文本"), metadata) == []
