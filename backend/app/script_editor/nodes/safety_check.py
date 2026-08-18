"""
safety_check node — LLM 内容安全合规审查
在数据入库前对所有游戏文本进行安全检查（LLM as Judge）
"""

import asyncio
import logging
import re

from langgraph.types import interrupt

from app.script_editor.state import STEP_SAFETY_CHECK, ScriptGenState

logger = logging.getLogger(__name__)

SAFETY_SYSTEM_PROMPT = """你是一位内容安全审查专家，负责检查游戏剧本内容是否符合中国法律法规和社会主义核心价值观。

请检查以下内容中是否包含：
1. 色情、淫秽或低俗内容
2. 赌博相关美化或诱导内容
3. 毒品相关美化内容
4. 反动、颠覆国家政权或危害国家安全的言论
5. 暴力恐怖主义美化或煽动
6. 歧视性内容（种族、性别、宗教、地域等）
7. 其他违反中国法律法规的内容

注意：剧本杀游戏本身包含悬疑、推理、谋杀等元素是正常的游戏设计，只要不美化犯罪、不宣扬违法内容、不违反公序良俗即可。

审查标准：
- 正常的悬疑推理情节（如杀人动机、作案手法描述）不算违规
- 角色之间的合理冲突和矛盾不算违规
- 但涉及美化犯罪、鼓励违法行为、色情描写、政治敏感内容则不通过

请回复格式：
第一行写 PASS 或 FAIL
如果 FAIL，从第二行开始写明具体原因"""


async def safety_check(state: ScriptGenState) -> dict:
    """安全审查节点 — 在保存数据库前检查所有游戏数据内容"""
    game_data_sections = state.get("game_data_sections", {})
    review_text = _assemble_review_text(game_data_sections)

    if len(review_text.strip()) < 50:
        return {"current_step": STEP_SAFETY_CHECK, "safety_passed": True}

    try:
        from app.core.llm_factory import create_llm

        llm = create_llm(model="deepseek-v4-flash", temperature=0.1, timeout=60, max_retries=2)

        response = await asyncio.wait_for(
            llm.ainvoke(
                [
                    {"role": "system", "content": SAFETY_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"请审查以下游戏剧本内容：\n\n{review_text}",
                    },
                ]
            ),
            timeout=90,
        )

        content = response.content if hasattr(response, "content") else str(response)
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        passed = bool(re.match(r"\s*PASS", content, re.IGNORECASE))

        if passed:
            logger.info("Safety check passed")
            return {"current_step": STEP_SAFETY_CHECK, "safety_passed": True}

        reason = content.split("\n", 1)[-1].strip() if "\n" in content else content.strip()
        logger.warning(f"Safety check failed: {reason}")
        interrupt(
            {
                "step": STEP_SAFETY_CHECK,
                "step_label": "安全审查",
                "rejected": True,
                "reason": reason or "内容未通过安全审查",
            }
        )

        return {
            "current_step": STEP_SAFETY_CHECK,
            "safety_passed": False,
            "safety_rejection_reason": reason or "内容未通过安全审查",
            "_review_action": "regenerate",
        }

    except TimeoutError:
        reason = "内容安全审查超时，请检查模型配置后重新提交"
        logger.error("Safety check timed out (90s), rejecting until reviewed")
        return {
            "current_step": STEP_SAFETY_CHECK,
            "safety_passed": False,
            "safety_rejection_reason": reason,
            "_review_action": "regenerate",
        }
    except Exception as e:
        logger.error(f"Safety check error: {e}", exc_info=True)
        return {
            "current_step": STEP_SAFETY_CHECK,
            "safety_passed": False,
            "safety_rejection_reason": "内容安全审查失败，请检查模型配置后重新提交",
            "_review_action": "regenerate",
        }


def _assemble_review_text(sections: dict) -> str:
    """将所有游戏数据文本组装为审查输入"""
    parts = []

    if sections.get("overview"):
        parts.append(f"【剧本概述】\n{sections['overview']}")

    if sections.get("description"):
        parts.append(f"【剧本描述】\n{sections['description']}")

    if sections.get("opening"):
        parts.append(f"【开场系统消息】\n{sections['opening']}")

    for stage in sections.get("clue_stages", []):
        parts.append(
            f"【第{stage.get('round_number', '?')}轮线索】\n"
            f"{stage.get('system_notice', '')}\n"
            f"{stage.get('discussion_notice', '')}"
        )

    if sections.get("truth_reveal"):
        parts.append(f"【真相揭晓】\n{sections['truth_reveal']}")

    if sections.get("full_truth"):
        parts.append(f"【完整真相】\n{sections['full_truth']}")

    for name, script in (sections.get("character_scripts") or {}).items():
        parts.append(f"【{name}的个人剧本】\n{script[:2000]}")

    for cd in sections.get("character_data", []):
        parts.append(
            f"【{cd.get('name', '?')}的角色数据】\n"
            f"{cd.get('profile', '')}\n{cd.get('system_prompt', '')}"
        )

    return "\n\n".join(parts)
