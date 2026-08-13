import asyncio

from app.agents.agent_prompts import build_role_system_prompt
from app.agents.tools import get_tools
from app.rag.retriever import ChromaRetriever


def test_non_rag_prompt_contains_only_supplied_personal_script():
    prompt = build_role_system_prompt("角色设定", "只属于甲的秘密", rag_enabled=False)

    assert "只属于甲的秘密" in prompt
    assert "recall_personal_script_memory" not in prompt


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
