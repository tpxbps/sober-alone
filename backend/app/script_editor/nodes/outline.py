"""
generate_outline node — 根据用户创意生成剧本大纲（结构化输出，含标题）
"""

import asyncio
import logging

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.script_editor.nodes.utils import call_llm
from app.script_editor.prompts.templates import get_prompt
from app.script_editor.state import STEP_GENERATE_OUTLINE, ScriptGenState

logger = logging.getLogger(__name__)


class OutlineResult(BaseModel):
    """大纲结构化输出"""

    script_title: str = Field(
        description="剧本标题（2~6个字的精炼标题，如：客栈、暗夜追踪、迷雾庄园）"
    )
    content: str = Field(description="完整的剧本杀游戏大纲（Markdown格式）")


async def generate_outline(state: ScriptGenState) -> dict:
    """根据用户创意生成结构化大纲（含标题）"""
    system_prompt = get_prompt("generate_outline", state)
    user_content = f"我的剧本创意：\n\n{state.get('user_idea', '')}"

    # 尝试结构化输出（获取标题+大纲）
    title = ""
    outline = ""
    try:
        from app.core.llm_factory import create_llm

        llm = create_llm(
            model="deepseek-v4-flash", temperature=0.85, timeout=180, disable_thinking=True
        )
        structured_llm = llm.with_structured_output(
            OutlineResult, method="function_calling", tool_choice="auto"
        )
        result = await asyncio.wait_for(
            structured_llm.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_content),
                ]
            ),
            timeout=240,
        )
        title = result.script_title.strip()  # type: ignore[union-attr]
        outline = result.content.strip()  # type: ignore[union-attr]
        logger.info(f"Outline structured output OK, title: {title}")
    except Exception as e:
        logger.warning(f"Outline structured output failed, falling back to text: {e}")
        outline = await call_llm(system_prompt, user_content)

    # 降级：从大纲文本中提取标题
    if not title:
        for line in outline.split("\n"):
            line = line.strip()
            if line.startswith("# ") and len(line) > 3:
                title = line[2:].strip()
                break
    if not title or title == "未命名剧本":
        title = "未命名剧本"

    return {
        "outline": outline,
        "script_title": title,
        "current_step": STEP_GENERATE_OUTLINE,
    }
