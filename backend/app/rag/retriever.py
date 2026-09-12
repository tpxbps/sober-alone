"""
RAG Retriever - ChromaDB向量检索器
用于角色剧本记忆的语义检索
"""

import asyncio
import logging
from typing import Any, cast

import chromadb
from chromadb.config import Settings as ChromaSettings
from zhipuai import ZhipuAI

from app.core.config import settings

logger = logging.getLogger(__name__)


class ChromaRetriever:
    """
    ChromaDB向量检索器

    用于从预处理好的ChromaDB向量数据库中检索角色剧本内容。
    向量数据库存储在 data/chroma/ 目录下。
    """

    def __init__(self, persist_dir: str = ""):
        """
        初始化检索器

        Args:
            persist_dir: ChromaDB持久化目录，默认使用配置中的路径
        """
        self.persist_dir = persist_dir or settings.CHROMA_PERSIST_DIR
        self.client = chromadb.PersistentClient(
            path=self.persist_dir, settings=ChromaSettings(anonymized_telemetry=False)
        )
        self.zhipu_client = ZhipuAI(api_key=settings.ZHIPUAI_API_KEY)
        self.embedding_model = "embedding-3"

    def _get_collection_name(self, script_id: str) -> str:
        """
        生成集合名称

        Args:
            script_id: 剧本ID

        Returns:
            str: 集合名称
        """
        # 预处理时，将UUID中的横线替换为了下划线，以符合ChromaDB命名规范
        return f"script_{script_id.replace('-', '_')}"

    def _create_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        创建文本嵌入向量

        Args:
            texts: 文本列表

        Returns:
            List[List[float]]: 嵌入向量列表
        """
        response = self.zhipu_client.embeddings.create(
            model=self.embedding_model, input=texts, dimensions=1024
        )
        return [item.embedding for item in response.data]

    async def collection_exists(self, script_id: str) -> bool:
        """Check script-level RAG availability without creating an embedding request."""
        collection_name = self._get_collection_name(script_id)
        try:
            await asyncio.to_thread(self.client.get_collection, collection_name)
            return True
        except Exception:
            return False

    async def character_index_ready(self, script_id: str, character_id: str, digest: str) -> bool:
        return bool(await self._complete_batch(script_id, character_id, digest))

    async def _complete_batch(self, script_id: str, character_id: str, digest: str) -> str | None:
        try:
            collection = await asyncio.to_thread(
                self.client.get_collection, self._get_collection_name(script_id)
            )
            data = await asyncio.to_thread(
                collection.get,
                where={"$and": [{"character_id": character_id}, {"content_digest": digest}]},
                include=["metadatas"],
            )
            batches = {}
            for item in data.get("metadatas") or []:
                if (
                    item
                    and item.get("character_id") == character_id
                    and item.get("content_digest") == digest
                ):
                    batches.setdefault(item.get("ingest_version"), []).append(item)
            for version, items in batches.items():
                if (
                    version
                    and len(items) == items[0].get("total_chunks", 0) > 0
                    and {item.get("chunk_index") for item in items} == set(range(len(items)))
                    and all(item.get("total_chunks") == len(items) for item in items)
                ):
                    return version
            return None
        except Exception:
            return None

    async def retrieve(
        self,
        script_id: str,
        query: str,
        character_id: str | None = None,
        top_k: int = 3,
        content_digest: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        检索相关内容

        Args:
            script_id: 剧本ID
            query: 查询文本
            character_id: 角色ID (可选，用于过滤特定角色的内容)
            top_k: 返回结果数量

        Returns:
            List[Dict]: 检索结果列表，每个元素包含 content, metadata, distance
        """
        collection_name = self._get_collection_name(script_id)

        try:
            collection = await asyncio.to_thread(self.client.get_collection, collection_name)
        except Exception as e:
            logger.debug(
                "Chroma collection unavailable: %s (%s)", collection_name, type(e).__name__
            )
            return []

        batch = None
        if content_digest:
            batch = (
                await self._complete_batch(script_id, character_id, content_digest)
                if character_id
                else None
            )
            if not batch:
                return []

        # 生成查询向量（同步 HTTP 调用 → 移到线程池）
        query_embeddings = await asyncio.to_thread(self._create_embeddings, [query])

        # 构建过滤条件
        where_filter = None
        if character_id:
            where_filter = {"character_id": character_id}
            if content_digest:
                where_filter = {
                    "$and": [
                        where_filter,
                        {"content_digest": content_digest},
                        {"ingest_version": batch},
                    ]
                }

        # 执行检索（同步 ChromaDB 磁盘 I/O → 移到线程池）
        results = await asyncio.to_thread(
            collection.query,
            query_embeddings=cast(Any, query_embeddings),
            n_results=top_k,
            where=cast(Any, where_filter),
            include=["documents", "metadatas", "distances"],
        )

        # 格式化结果
        formatted_results = []
        if results["documents"] and results["documents"][0]:
            for i in range(len(results["documents"][0])):
                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                # Defense in depth: a malformed or stale index must never leak a
                # different character's private script into this role.
                if character_id and metadata.get("character_id") != character_id:
                    continue
                if content_digest and metadata.get("content_digest") != content_digest:
                    continue
                if batch and metadata.get("ingest_version") != batch:
                    continue
                formatted_results.append(
                    {
                        "content": results["documents"][0][i],
                        "metadata": metadata,
                        "distance": results["distances"][0][i] if results["distances"] else 0.0,
                    }
                )

        return formatted_results


# 全局实例
_retriever_instance: ChromaRetriever | None = None


def get_retriever() -> ChromaRetriever:
    """获取全局检索器实例"""
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = ChromaRetriever()
    return _retriever_instance
