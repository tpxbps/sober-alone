"""
[暂时弃用] clear_irrelevant_history_messages Middleware
清理Agent历史记录中的中间思考消息
"""

from typing import Any

from langchain.agents.middleware import AgentState, after_agent
from langchain.messages import AIMessage
from langgraph.runtime import Runtime


@after_agent
def clear_irrelevant_history_messages(state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
    """
    清理Agent历史记录的中间件

    目的：
    1. 移除仅包含 tool_calls 的中间 AIMessage（思考过程）
    2. 仅保留最终生成的文本回复
    3. 保持上下文纯净，让Agent更专注于游戏对话

    使用场景：
    - Agent在发言前可能会调用多个工具（如检索记忆、更新状态）
    - 这些工具调用的中间AIMessage不应出现在下一次对话的上下文中
    - 只保留最终的发言AIMessage
    """
    messages = state.get("messages", [])
    if len(messages) <= 3:
        return None

    cleaned_messages = []
    for msg in messages:
        if isinstance(msg, AIMessage):
            content = (msg.content if isinstance(msg.content, str) else "").strip()
            tool_calls = getattr(msg, "tool_calls", None) or []

            # 如果消息只有 tool_calls 没有文本内容，说明是中间思考步骤，则过滤
            if tool_calls and not content:
                continue
            elif content:
                cleaned_messages.append(msg)
        else:
            cleaned_messages.append(msg)

    # 将cleaned_messages写回state
    return {"messages": cleaned_messages}
