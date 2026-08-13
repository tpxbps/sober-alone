"""
generate_final_draft node — 根据审稿意见生成终稿
"""

from app.script_editor.nodes.utils import call_llm
from app.script_editor.prompts.templates import get_prompt
from app.script_editor.state import STEP_GENERATE_FINAL_DRAFT, ScriptGenState


async def generate_final_draft(state: ScriptGenState) -> dict:
    """根据审稿意见生成终稿"""
    system_prompt = get_prompt("generate_final_draft", state)

    # 构建角色列表
    characters_summary = ""
    for c in state.get("characters", []):
        name = c.get("name", "?")
        characters_summary += (
            f"- {name}: {c.get('gender', '?')}, {c.get('age', '?')}岁, {c.get('occupation', '?')}\n"
        )

    # 构建审稿意见部分（AI + 人类）
    review_section = f"""## AI审稿意见
---
{state.get("review_opinion", "")}
---"""

    human_review = state.get("human_review", "")
    if human_review:
        review_section += f"""

## 真人审稿意见
---
{human_review}
---"""

    user_content = f"""请根据以下材料生成终稿。

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

{review_section}

请根据以上审稿意见修改并输出完整终稿。注意终稿应同时考虑初稿生成时对各轮线索分阶段设计的考量。
"""

    final_draft = await call_llm(system_prompt, user_content)

    return {
        "final_draft": final_draft,
        "current_step": STEP_GENERATE_FINAL_DRAFT,
    }
