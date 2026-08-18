"""
Prompt Templates — 提示词模板工具
用于将变量注入到默认提示词中
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.script_editor.prompts.defaults import DEFAULT_PROMPTS

DIFFICULTY_LABELS = {
    1: "简单",
    2: "中等",
    3: "困难",
    4: "极难",
}

DIFFICULTY_DESCRIPTIONS = {
    1: "适合新手玩家，线索指向较为明显，推理难度较低",
    2: "适合有一定经验的玩家，需要一定的推理能力和信息整合能力",
    3: "适合资深玩家，线索复杂，推理链长，需要深度分析",
    4: "适合硬核玩家，线索碎片化，大量误导信息，推理极具挑战",
}


def get_prompt(step: str, state: Mapping[str, Any]) -> str:
    """
    获取指定步骤的提示词（优先使用用户自定义的，否则使用默认）

    Args:
        step: 步骤名
        state: 当前工作流状态（用于格式化模板变量）

    Returns:
        格式化后的提示词文本
    """
    # 优先使用用户自定义提示词
    prompts = state.get("prompts", {})
    template = prompts.get(step, DEFAULT_PROMPTS.get(step, ""))

    # 格式化模板变量
    try:
        return template.format(
            player_count=state.get("player_count", 4),
            difficulty=state.get("difficulty", 1),
            difficulty_label=DIFFICULTY_LABELS.get(state.get("difficulty", 1), "简单"),
            difficulty_desc=DIFFICULTY_DESCRIPTIONS.get(state.get("difficulty", 1), ""),
            num_clue_rounds=state.get("num_clue_rounds", 2),
        )
    except KeyError:
        return template


def get_default_prompts() -> dict[str, str]:
    """获取所有步骤的默认提示词（未经格式化）"""
    return dict(DEFAULT_PROMPTS)
