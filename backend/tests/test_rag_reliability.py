from types import SimpleNamespace

import pytest

from app.rag.retriever import ChromaRetriever
from app.rag.revision import script_digest


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["missing", "legacy", "partial", "mixed", "complete"])
async def test_readiness_requires_one_complete_role_and_content_version(variant):
    digest = script_digest("个人剧本")
    values = [
        {
            "character_id": "a",
            "content_digest": digest,
            "ingest_version": "v",
            "chunk_index": i,
            "total_chunks": 2,
        }
        for i in range(2)
    ]
    if variant == "missing":
        values = []
    elif variant == "legacy":
        values[0].pop("content_digest")
    elif variant == "partial":
        values = values[:1]
    elif variant == "mixed":
        values[1]["ingest_version"] = "other"
    collection = SimpleNamespace(get=lambda **kwargs: {"metadatas": values})
    retriever = ChromaRetriever.__new__(ChromaRetriever)
    retriever.client = SimpleNamespace(get_collection=lambda *_args: collection)
    assert await retriever.character_index_ready("s", "a", digest) is (variant == "complete")


@pytest.mark.asyncio
async def test_retrieval_failure_returns_own_session_snapshot(monkeypatch):
    from app.agents.tools import recall_memory

    monkeypatch.setattr(recall_memory, "get_stream_writer", lambda: lambda *_args: None)

    def unavailable():
        raise RuntimeError("offline")

    monkeypatch.setattr(recall_memory, "get_retriever", unavailable)
    value = await recall_memory.recall_personal_script_memory.coroutine(
        "细节",
        runtime=SimpleNamespace(
            state={"script_id": "s", "character_id": "a", "personal_script": "本局旧版个人原文"}
        ),
    )
    assert "本局旧版个人原文" in value
