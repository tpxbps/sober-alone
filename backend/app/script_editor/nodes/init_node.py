"""
init_workflow node — 初始化工作流状态
"""

import uuid

from app.script_editor.prompts.defaults import DEFAULT_PROMPTS
from app.script_editor.state import (
    STEP_INIT,
    ScriptGenState,
)


def init_workflow(state: ScriptGenState) -> dict:
    """
    初始化工作流：设置默认值和 UUID
    """
    script_id = str(uuid.uuid4())

    # 加载默认提示词
    default_prompts = dict(DEFAULT_PROMPTS)

    # 合并用户自定义的提示词
    user_prompts = state.get("prompts", {})
    merged_prompts = {**default_prompts, **user_prompts}

    return {
        "script_id": script_id,
        "current_step": STEP_INIT,
        "prompts": merged_prompts,
        "player_count": state.get("player_count", 4),
        "difficulty": state.get("difficulty", 1),
        "num_clue_rounds": state.get("num_clue_rounds", 2),
        "characters": [],
        "character_scripts": {},
        "system_prompts_map": {},
        "game_full_process": [],
        "free_speech_limits": [2] * state.get("num_clue_rounds", 2),
        "character_avatars": {},
        "character_voice_ids": {},
    }
