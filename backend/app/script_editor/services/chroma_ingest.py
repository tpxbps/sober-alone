"""
ChromaDB Ingestion Service — 将角色剧本向量化存入 ChromaDB
"""

import logging
import uuid

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
    # 初始化 ChromaDB 客户端
    client = chromadb.PersistentClient(
        path=settings.CHROMA_PERSIST_DIR,
        settings=ChromaSettings(anonymized_telemetry=False),
    )

    # 初始化 ZhipuAI 客户端
    zhipu_client = ZhipuAI(api_key=settings.ZHIPUAI_API_KEY)
    embedding_model = "embedding-3"

    # 生成集合名称
    collection_name = f"script_{script_id.replace('-', '_')}"

    # 删除已有集合（如果存在）以避免重复
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass

    # 创建新集合
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"script_id": script_id},
    )

    # 构建角色名 -> character_id 映射
    name_to_id = {c.get("name"): c.get("character_id", str(uuid.uuid4())) for c in characters}

    # 处理每个角色的个人剧本
    all_ids = []
    all_documents = []
    all_metadatas = []
    all_embeddings = []

    for name, script_text in character_scripts.items():
        char_id = name_to_id.get(name, str(uuid.uuid4()))
        if not script_text:
            continue

        # 分块
        chunks = _chunk_text(script_text, CHUNK_SIZE, CHUNK_OVERLAP)

        for i, chunk in enumerate(chunks):
            doc_id = f"{char_id}_chunk_{i}"
            all_ids.append(doc_id)
            all_documents.append(chunk)
            all_metadatas.append(
                {
                    "character_id": char_id,
                    "character_name": name,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                }
            )

    if not all_documents:
        logger.warning(f"No documents to ingest for script {script_id}")
        return

    # 批量生成 embeddings
    batch_size = 20
    for batch_start in range(0, len(all_documents), batch_size):
        batch_end = min(batch_start + batch_size, len(all_documents))
        batch_texts = all_documents[batch_start:batch_end]

        try:
            response = zhipu_client.embeddings.create(
                model=embedding_model,
                input=batch_texts,
                dimensions=1024,
            )
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)
        except Exception as e:
            logger.error(f"Embedding generation failed for batch starting at {batch_start}: {e}")
            return

    # 存入 ChromaDB
    try:
        collection.add(
            ids=all_ids,
            documents=all_documents,
            metadatas=all_metadatas,
            embeddings=all_embeddings,
        )
        logger.info(f"Ingested {len(all_ids)} chunks for script {script_id}")
    except Exception as e:
        logger.error(f"ChromaDB ingestion failed: {e}")


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
