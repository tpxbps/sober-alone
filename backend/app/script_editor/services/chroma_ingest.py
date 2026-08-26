"""
ChromaDB Ingestion Service — 将角色剧本向量化存入 ChromaDB
"""

import logging

import chromadb
from chromadb.config import Settings as ChromaSettings
from zhipuai import ZhipuAI

from app.core.config import settings

logger = logging.getLogger(__name__)

# 文本分块大小
CHUNK_SIZE = 500
CHUNK_OVERLAP = 100


def ingest_script(
    script_id: str,
    characters: list[dict],
    character_scripts: dict[str, str],
):
    """
    将剧本的角色个人剧本向量化并存入 ChromaDB

    Args:
        script_id: 剧本ID
        characters: 角色列表
        character_scripts: {角色名: 个人剧本文本}
    """
    by_name = {item.get("name"): item for item in characters}
    for name, script_text in character_scripts.items():
        character = by_name.get(name)
        if not character or not character.get("character_id"):
            raise ValueError(f"Missing stable character_id for {name}")
        ingest_character(script_id, character, script_text)


def ingest_character(script_id: str, character: dict, script_text: str) -> None:
    """Atomically replace only one character's vector documents."""
    character_id = str(character.get("character_id", ""))
    name = str(character.get("name", ""))
    if not character_id:
        raise ValueError("character_id is required")

    client = chromadb.PersistentClient(
        path=settings.CHROMA_PERSIST_DIR,
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    collection = client.get_or_create_collection(
        name=f"script_{script_id.replace('-', '_')}",
        metadata={"script_id": script_id},
    )
    chunks = _chunk_text(script_text, CHUNK_SIZE, CHUNK_OVERLAP) if script_text else []
    embeddings = []
    if chunks:
        zhipu_client = ZhipuAI(api_key=settings.ZHIPUAI_API_KEY)
        for batch_start in range(0, len(chunks), 20):
            response = zhipu_client.embeddings.create(
                model="embedding-3",
                input=chunks[batch_start : batch_start + 20],
                dimensions=1024,
            )
            embeddings.extend(item.embedding for item in response.data)
        if len(embeddings) != len(chunks):
            raise RuntimeError("Embedding provider returned an incomplete batch")

    # Do not remove the last good vectors until the replacement is ready.
    collection.delete(where={"character_id": character_id})
    if chunks:
        collection.add(
            ids=[f"{character_id}_chunk_{index}" for index in range(len(chunks))],
            documents=chunks,
            metadatas=[
                {
                    "character_id": character_id,
                    "character_name": name,
                    "chunk_index": index,
                    "total_chunks": len(chunks),
                }
                for index in range(len(chunks))
            ],
            embeddings=embeddings,
        )
    logger.info("Ingested %s chunks for %s/%s", len(chunks), script_id, character_id)


async def ingest_character_async(script_id: str, character: dict, script_text: str) -> None:
    import asyncio

    await asyncio.to_thread(ingest_character, script_id, character, script_text)


async def ingest_script_async(
    script_id: str,
    characters: list[dict],
    character_scripts: dict[str, str],
):
    """Async wrapper — runs ingest_script in a thread pool to avoid blocking the event loop."""
    import asyncio

    await asyncio.to_thread(
        ingest_script,
        script_id,
        characters,
        character_scripts,
    )


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """将文本按段落和大小分块"""
    chunks = []

    # 先按段落分割
    paragraphs = text.split("\n\n")

    current_chunk = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current_chunk) + len(para) + 2 <= chunk_size:
            current_chunk += ("\n\n" if current_chunk else "") + para
        else:
            if current_chunk:
                chunks.append(current_chunk)
            # 如果单个段落超过 chunk_size，进一步切分
            if len(para) > chunk_size:
                for j in range(0, len(para), chunk_size - overlap):
                    chunks.append(para[j : j + chunk_size])
                current_chunk = ""
            else:
                current_chunk = para

    if current_chunk:
        chunks.append(current_chunk)

    return chunks if chunks else [text[:chunk_size]]
