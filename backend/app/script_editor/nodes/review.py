"""
review_by_llm node — 独立 LLM 审稿（自动步骤，无需用户确认）
"""

from app.core.config import settings
from app.script_editor.llm import create_editor_llm as create_llm
from app.script_editor.nodes.utils import call_llm
from app.script_editor.prompts.templates import get_prompt
from app.script_editor.services.execution import creative_context
from app.script_editor.state import STEP_REVIEW_BY_LLM, ScriptGenState


async def review_by_llm(state: ScriptGenState) -> dict:
    """使用同一模型但审稿人角色，对大纲+初稿进行审稿"""
    system_prompt = (
        get_prompt("review", state)
        + """
【当前阶段职责】这是作者可读的全知初稿，个人剧本、速览、结构化游戏数据和资源会由后续节点生成。
不得因尚未拆分角色个人本、缺少字段或图片音频而判为缺陷，也不要要求作者提前拆分。
必须区分开局时点和后续线索公布时点：开局尚未鉴定、某轮再公布检验结果，是合法的分轮披露，不是时间矛盾。不得把全知稿中后续发生的事件当成角色开局已知。
重点核对因果、时间线、人物行为与证据设计。将有原文依据的事实矛盾与可选创作建议分开。
作者确认的主题、人物关系与结局优先；多人因相近恐惧行动可以是刻意主题，不自动判为动机重复。
声称信息缺失前检查全文是否已包含同义内容；引文包含所称缺失事实时不得再报遗漏。
"""
    )

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

## 真人补充意见（若有）
{state.get("human_review", "")}

请从叙事质量、逻辑严谨性、角色设计、游戏性、系统匹配性等维度给出详细审稿意见。

在开头给出评审结果：[通过-Accept，小修-Minor revision，大修-Major revision，拒绝-Reject] 4选1，
然后逐条返回关键意见和修改方向。
"""

    review_opinion = await call_llm(
        system_prompt,
        user_content + creative_context(state, "review_by_llm"),
        llm=create_llm(
            model=settings.get_script_review_model(),
            temperature=0.1,
            timeout=240,
            max_retries=0,
        ),
    )

    return {
        "review_opinion": review_opinion,
        "current_step": STEP_REVIEW_BY_LLM,
    }
