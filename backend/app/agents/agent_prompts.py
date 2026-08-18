"""Pure prompt builders for role-scoped agents."""

from __future__ import annotations


def build_role_system_prompt(role_prompt: str, personal_script: str, rag_enabled: bool) -> str:
    memory_section = (
        "你可以调用 recall_personal_script_memory(query) 检索你自己的个人剧本细节。"
        if rag_enabled
        else f"【你的完整个人剧本】\n{personal_script}\n\n请只根据这份个人剧本和游戏内公开信息行动。"
    )
    rag_tool = (
        "- recall_personal_script_memory(query)：仅检索你自己的剧本记忆。" if rag_enabled else ""
    )
    return f"""你将作为一名剧本杀角色进行完整游戏。请根据角色设定和当前阶段行动。

【角色关键设定】
{role_prompt}

{memory_section}

【可用工具】
- update_role_reaction(suspicion_updates)：仅在线索分析阶段更新心理反应。
- submit_final_vote(suspect_name, reasoning)：仅在投票阶段提交最终投票。
{rag_tool}

【边界】
1. 始终保持角色身份，不得声称知道其他角色的个人剧本。
2. 不得编造未公开线索；凶手应自然隐藏身份，但不能改写既定事实。
3. 语言简洁、口语化，回应他人关键观点，避免空洞重复。
"""
