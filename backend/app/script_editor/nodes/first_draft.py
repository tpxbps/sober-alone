"""
generate_first_draft node — 根据确认的大纲生成初稿
"""

import re

from app.script_editor.nodes.utils import call_llm
from app.script_editor.prompts.templates import get_prompt
from app.script_editor.state import STEP_GENERATE_FIRST_DRAFT, ScriptGenState


async def generate_first_draft(state: ScriptGenState) -> dict:
    """根据确认的大纲生成初稿（含角色设定）"""
    system_prompt = get_prompt("generate_first_draft", state)

    user_content = f"""以下是已确认的剧本大纲，请据此撰写完整初稿：

---
{state.get("outline", "")}
---

玩家人数：{state.get("player_count", 4)}人
"""

    first_draft = await call_llm(system_prompt, user_content)

    # 尝试从初稿中提取角色信息
    characters = _extract_characters(first_draft, state.get("player_count", 4))

    return {
        "first_draft": first_draft,
        "characters": characters,
        "current_step": STEP_GENERATE_FIRST_DRAFT,
    }


def _extract_characters(draft: str, player_count: int) -> list[dict]:
    """
    从初稿文本中尝试提取角色信息。
    如果提取失败，返回空列表（后续步骤会补充）。
    """
    characters = []

    # 尝试匹配常见的角色描述格式
    # 格式1: **姓名**：男，XX岁，职业...
    pattern1 = re.compile(
        r"\*\*([^*]{2,10})\*\*[：:]\s*([男女])[^，,]*[，,]\s*(\d{1,3})\s*岁[，,]\s*([^。\n]+)",
        re.MULTILINE,
    )
    for match in pattern1.finditer(draft):
        if len(characters) >= player_count:
            break
        characters.append(
            {
                "name": match.group(1).strip(),
                "gender": match.group(2),
                "age": int(match.group(3)),
                "occupation": match.group(4).strip()[:50],
                "profile": "",
                "appearance": "",
            }
        )

    # 如果没提取到，尝试格式2: 姓名（男/女，XX岁）
    if not characters:
        pattern2 = re.compile(
            r"[\-\*]\s*([^\-\\*\(（\s]{2,10})\s*[\(（]\s*([男女])\s*[，,]\s*(\d{1,3})\s*岁\s*[\)）]"
        )
        for match in pattern2.finditer(draft):
            if len(characters) >= player_count:
                break
            characters.append(
                {
                    "name": match.group(1).strip(),
                    "gender": match.group(2),
                    "age": int(match.group(3)),
                    "occupation": "",
                    "profile": "",
                    "appearance": "",
                }
            )

    return characters
