"""
review_by_llm node — 独立 LLM 审稿（自动步骤，无需用户确认）
"""

from app.script_editor.nodes.utils import call_llm
from app.script_editor.prompts.templates import get_prompt
from app.script_editor.state import STEP_REVIEW_BY_LLM, ScriptGenState


async def review_by_llm(state: ScriptGenState) -> dict:
    """使用同一模型但审稿人角色，对大纲+初稿进行审稿"""
    system_prompt = get_prompt("review", state)

    # 构建角色列表摘要
    characters_summary = ""
    for c in state.get("characters", []):
        characters_summary += f"- {c.get('name', '?')}: {c.get('gender', '?')}, {c.get('age', '?')}岁, {c.get('occupation', '?')}\n"

    user_content = f"""请审阅以下完整的剧本杀内容：

## 剧本大纲
---
{state.get("outline", "")}
---

## 角色列表
{characters_summary}

## 初稿全文
---
{state.get("first_draft", "")}
---

请从叙事质量、逻辑严谨性、角色设计、游戏性等维度给出详细审稿意见。

在开头给出评审结果：[通过-Accept，小修-Minor revision，大修-Major revision，拒绝-Reject] 4选1，
然后逐条返回关键意见和修改方向。
"""

    review_opinion = await call_llm(system_prompt, user_content)

    return {
        "review_opinion": review_opinion,
        "current_step": STEP_REVIEW_BY_LLM,
    }
