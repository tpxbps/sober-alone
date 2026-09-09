import asyncio
import importlib
from types import SimpleNamespace

import pytest
from langchain.messages import AIMessageChunk
from langchain_core.exceptions import OutputParserException

from app.agents.agent_manager import AgentManager
from app.agents.agent_player import AgentPlayer, StreamToken
from app.agents.agent_prompts import build_role_system_prompt
from app.agents.reaction import REACTION_MODEL_TIMEOUT_SECONDS, SpeechReactionPayload
from app.agents.tools import get_tools
from app.core.config import settings
from app.rag.retriever import ChromaRetriever


def test_non_rag_prompt_contains_only_supplied_personal_script():
    prompt = build_role_system_prompt("角色设定", "只属于甲的秘密", rag_enabled=False)

    assert "只属于甲的秘密" in prompt
    assert "recall_personal_script_memory" not in prompt


def test_role_prompt_requires_markdown_and_tools_before_visible_speech():
    prompt = build_role_system_prompt("角色设定", "个人剧本", rag_enabled=True)

    assert "最终发言默认使用简洁 Markdown" in prompt
    assert "应先完成全部工具调用并等待结果" in prompt
    assert "不应以牺牲流式输出为代价" in prompt
    assert "逐个点评场上所有玩家" in prompt
    assert "绝不能在正文中说“c01 显示”" in prompt
    assert "不要在标签两侧添加反引号" in prompt


def test_rag_tool_registration_is_capability_driven():
    without_rag = {tool.name for tool in get_tools(rag_enabled=False)}
    with_rag = {tool.name for tool in get_tools(rag_enabled=True)}

    assert "recall_personal_script_memory" not in without_rag
    assert "recall_personal_script_memory" in with_rag


def test_retriever_rejects_cross_character_results():
    class Collection:
        def query(self, **_kwargs):
            return {
                "documents": [["甲的内容", "乙的秘密"]],
                "metadatas": [[{"character_id": "char-a"}, {"character_id": "char-b"}]],
                "distances": [[0.1, 0.2]],
            }

    class Client:
        def get_collection(self, _name):
            return Collection()

    retriever = object.__new__(ChromaRetriever)
    retriever.client = Client()
    retriever._create_embeddings = lambda _texts: [[0.0]]

    result = asyncio.run(retriever.retrieve("script", "query", character_id="char-a", top_k=2))

    assert [item["content"] for item in result] == ["甲的内容"]


def test_reaction_tool_schema_uses_explicit_arrays_and_normalizes_to_game_maps():
    schema = SpeechReactionPayload.model_json_schema()
    assert schema["properties"]["suspicion_changes"]["type"] == "array"
    assert schema["properties"]["suspected_by_changes"]["type"] == "array"

    reaction = SpeechReactionPayload.model_validate(
        {
            "suspicion_changes": [{"target": "许棠", "score": 1.2, "reason": "时间线矛盾"}],
            "suspected_by_changes": [
                {
                    "suspecter": "陆鸣",
                    "score": "0.4",
                    "reason": "质疑我的证词",
                    "need_response": True,
                }
            ],
            "main_perspective": "陆鸣指出许棠的时间线矛盾。",
        }
    ).to_reaction()

    assert reaction.my_suspicion_graph["许棠"].score == 1.0
    assert reaction.my_suspected_by["陆鸣"].score == 0.4
    assert reaction.my_suspected_by["陆鸣"].need_response is True


@pytest.mark.asyncio
async def test_missing_chroma_collection_is_a_quiet_capability_check():
    class MissingClient:
        def get_collection(self, _name):
            raise RuntimeError("missing")

    retriever = object.__new__(ChromaRetriever)
    retriever.client = MissingClient()

    assert await retriever.collection_exists("sample") is False


@pytest.mark.parametrize(
    "model, provider, method",
    [
        ("deepseek-v4-flash", "deepseek", "json_schema"),
        ("glm-5.3-flash", "zhipuai", "json_mode"),
    ],
)
def test_reaction_model_uses_the_same_provider_format_as_health_probe(
    monkeypatch, model, provider, method
):
    captured = {}

    class Model:
        def with_structured_output(self, schema, **kwargs):
            captured["schema"] = schema
            captured["structured_kwargs"] = kwargs
            return object()

    def fake_create_llm(**kwargs):
        captured["model_kwargs"] = kwargs
        return Model()

    monkeypatch.setattr("app.agents.game_model_paths.create_llm", fake_create_llm)

    player = object.__new__(AgentPlayer)
    player.llm_model = model
    player.llm_provider = provider
    player.system_prompt = "角色设定"
    player.personal_script = "个人剧本"
    player._init_model = lambda: Model()
    player._create_reaction_agent()

    assert captured["schema"] is SpeechReactionPayload
    assert captured["model_kwargs"]["model"] == model
    assert captured["model_kwargs"]["timeout"] == REACTION_MODEL_TIMEOUT_SECONDS
    assert captured["model_kwargs"]["max_retries"] == 1
    assert captured["structured_kwargs"] == {"method": method}


@pytest.mark.asyncio
async def test_agent_manager_disables_rag_when_script_collection_is_missing(monkeypatch):
    captured = []

    class Retriever:
        async def collection_exists(self, script_id):
            assert script_id == "sample"
            return False

    class FakePlayer:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr("app.rag.retriever.get_retriever", lambda: Retriever())
    monkeypatch.setattr("app.agents.agent_manager.AgentPlayer", FakePlayer)
    monkeypatch.setattr("app.agents.agent_manager.settings.ZHIPUAI_API_KEY", "z")
    monkeypatch.setattr(
        type(settings),
        "get_api_key",
        lambda _settings, _provider: "key",
    )

    manager = AgentManager("session", "sample")
    await manager.initialize_agents(
        [
            {"character_id": "human", "name": "陆鸣"},
            {"character_id": "ai", "name": "姜芮", "character_script": "秘密"},
        ],
        human_character_id="human",
    )

    assert captured[0]["rag_enabled"] is False


@pytest.mark.asyncio
async def test_reaction_schema_failure_gets_one_targeted_repair_attempt():
    class StructuredReaction:
        def __init__(self):
            self.calls = 0
            self.prompts = []

        async def ainvoke(self, messages):
            self.calls += 1
            self.prompts.append(messages[-1].content)
            if self.calls == 1:
                raise OutputParserException("invalid tool arguments")
            return SpeechReactionPayload(
                suspicion_changes=[{"target": "许棠", "score": 0.6, "reason": "时间线不一致"}],
                main_perspective="陆鸣质疑许棠的时间线。",
            )

    structured = StructuredReaction()
    player = object.__new__(AgentPlayer)
    player.character_name = "陈朔"
    player.character_id = "ai"
    player.reaction_llm_model = "mimo-v2.5"
    player._reaction_structured = structured
    player._reaction_system_prompt = "系统提示"

    result = await player.react_to_speech("陆鸣", "我怀疑许棠隐瞒了时间线。")

    assert structured.calls == 2
    assert "格式纠正" in structured.prompts[1]
    assert result.my_suspicion_graph["许棠"].score == 0.6


@pytest.mark.asyncio
async def test_clue_recall_reads_only_server_side_revealed_clues(monkeypatch):
    module = importlib.import_module("app.agents.tools.recall_clues")

    class Result:
        @staticmethod
        def scalar_one_or_none():
            return SimpleNamespace(
                revealed_clues=[
                    {
                        "id": "c01",
                        "summary": "门锁",
                        "content": "门锁没有撬动痕迹。",
                    }
                ]
            )

    class Session:
        async def execute(self, _query):
            return Result()

    monkeypatch.setattr(module, "get_db_session", lambda: Session())
    monkeypatch.setattr(module, "get_stream_writer", lambda: lambda _message: None)

    result = await module.recall_public_clues.coroutine(
        clue_ids=["c01", "c99"],
        query="",
        runtime=SimpleNamespace(state={"session_id": "session"}),
    )

    assert "c01" in result
    assert "门锁没有撬动痕迹" in result
    assert "c99" not in result


@pytest.mark.asyncio
async def test_visible_speech_remains_incremental_even_when_tool_order_is_imperfect():
    continue_stream = asyncio.Event()

    class FakeAgent:
        async def astream(self, *_args, **_kwargs):
            yield (
                "messages",
                (AIMessageChunk(content="先说半句"), {"langgraph_node": "model"}),
            )
            await continue_stream.wait()
            yield (
                "messages",
                (
                    AIMessageChunk(
                        content="",
                        tool_call_chunks=[
                            {
                                "name": "recall_public_clues",
                                "args": "{}",
                                "id": "call-1",
                                "index": 0,
                            }
                        ],
                        chunk_position="last",
                    ),
                    {"langgraph_node": "model"},
                ),
            )
            yield (
                "messages",
                (
                    AIMessageChunk(content="**完整结论**", chunk_position="last"),
                    {"langgraph_node": "model"},
                ),
            )

    async def no_knowledge(_game_state):
        return ""

    player = object.__new__(AgentPlayer)
    player._agent = FakeAgent()
    player.thread_id = "session_ai"
    player.session_id = "session"
    player.script_id = "script"
    player.character_id = "ai"
    player.character_name = "姜芮"
    player._build_knowledge_context = no_knowledge

    stream = player.speak({}, "free_discussion")
    first_chunk = await asyncio.wait_for(anext(stream), timeout=0.1)
    assert isinstance(first_chunk, StreamToken)
    assert first_chunk.text == "先说半句"

    continue_stream.set()
    chunks = [first_chunk, *[chunk async for chunk in stream]]

    assert [chunk.text for chunk in chunks if isinstance(chunk, StreamToken)] == [
        "先说半句",
        "**完整结论**",
    ]


def test_reaction_preserves_provider_string_array_facts():
    payload = SpeechReactionPayload.model_validate(
        {"main_perspective": ["1. 广播是自动播放。", "2. 请核对门禁。"]}
    )
    assert payload.to_reaction().main_perspective == "1. 广播是自动播放。\n2. 请核对门禁。"


def test_reaction_rejects_nontext_fact_arrays():
    with pytest.raises(ValueError):
        SpeechReactionPayload.model_validate({"main_perspective": [{"fact": "门禁"}]})
