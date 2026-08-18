"""
Agent Tools package
AI角色扮演智能体的工具集

工具说明:
- recall_personal_script_memory: 所有阶段可用，检索剧本记忆
- update_role_reaction: 仅 clue_analysis 阶段可用
- submit_final_vote: 仅 vote 阶段可用

"""

from app.agents.tools.reaction import update_role_reaction
from app.agents.tools.recall_memory import RecallInput, recall_personal_script_memory
from app.agents.tools.vote import VoteInput, submit_final_vote

# 所有LangChain工具的列表 (供 create_agent 使用)
ALL_TOOLS = [
    recall_personal_script_memory,
    update_role_reaction,
    submit_final_vote,
]


def get_tools(*, rag_enabled: bool) -> list:
    tools = [update_role_reaction, submit_final_vote]
    if rag_enabled:
        tools.insert(0, recall_personal_script_memory)
    return tools


__all__ = [
    # Agent Tools (装饰器定义的工具)
    "recall_personal_script_memory",
    "update_role_reaction",
    "submit_final_vote",
    # Input schemas
    "RecallInput",
    "VoteInput",
    # Tool collections
    "ALL_TOOLS",
    "get_tools",
]
