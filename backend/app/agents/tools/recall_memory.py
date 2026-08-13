"""
recall_personal_script_memory tool
用于检索角色个人剧本中的相关具体细节
"""

from langchain.tools import ToolRuntime, tool
from langgraph.config import get_stream_writer
from pydantic import BaseModel, Field

from app.rag.retriever import get_retriever


class RecallInput(BaseModel):
    """剧本记忆检索的输入参数"""

    query: str = Field(
        description="需要检索的剧本内容关键词或问题，例如'与张三的关系'、'案发当晚我在做什么'"
    )


@tool(args_schema=RecallInput)
async def recall_personal_script_memory(query: str, runtime: ToolRuntime) -> str:
    """
    在任一发言阶段均可调用，但仅在必要时调用，用于检索角色个人剧本中的具体细节。

    当你需要回忆剧本中的细节、时间线、人物关系等信息时使用此工具。
    仅用于查询你自己的剧本细节。

    Args:
        query: 要检索的内容描述或问题

    Returns:
        str: 与查询相关的剧本内容片段
    """
    # 发送流式状态消息
    writer = get_stream_writer()
    writer("正在回忆具体细节...")

    state = runtime.state

    character_id = state.get("character_id", "")
    script_id = state.get("script_id", "")

    if not script_id or not character_id:
        return "无法检索记忆。"

    retriever = get_retriever()

    results = await retriever.retrieve(
        script_id=script_id, query=query, character_id=character_id, top_k=2
    )

    if not results:
        return "没有找到相关的剧本内容。"

    context_parts = []
    for i, result in enumerate(results):
        context_parts.append(f"[相关记忆 {i + 1}]\n{result['content']}")

    return "\n\n".join(context_parts)
