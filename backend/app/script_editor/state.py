"""
Script Generation Workflow State
定义 LangGraph StateGraph 的状态结构
"""

from typing import TypedDict


class ScriptGenState(TypedDict, total=False):
    """剧本生成工作流状态"""

    # === 用户输入 ===
    user_idea: str  # 用户的初始创意/大纲
    player_count: int  # 玩家人数 (默认 4)
    difficulty: int  # 难度 1-4
    num_clue_rounds: int  # 线索轮次数量
    ending_mode: str  # single | multiple

    # === 各步骤生成内容 ===
    outline: str  # 结构化大纲
    outline_session: dict  # optional v2 co-creation; absent for legacy checkpoints
    characters: list[dict]  # 角色档案列表 [{name, gender, age, occupation, profile, appearance}]
    first_draft: str  # 初稿全文
    review_opinion: str  # 独立审稿意见
    human_review: str  # 真人审稿意见
    quality_report: dict
    quality_acceptance: dict
    final_draft: str  # 终稿全文
    character_scripts: dict  # {角色名: 个人剧本文本}
    system_prompts_map: dict  # {角色名: system_prompt文本}

    # === 用户可修改的提示词 ===
    prompts: dict[str, str]  # {步骤名: 提示词文本}

    # === 最终结构化游戏数据 ===
    game_full_process: list[dict]  # 完整流程 JSON (匹配现有 schema)
    clue_stages: list[dict]  # canonical structured public clues
    full_truth: str  # 真相揭晓文本
    ending_config: dict | None
    free_speech_limits: list[int]  # 各轮自由讨论发言次数
    game_data_sections: dict  # 结构化数据各部分 (用于审阅)

    # === 元数据 ===
    script_title: str  # 剧本标题
    script_id: str  # 剧本 UUID
    cover_image_url: str  # 封面图 URL
    character_avatars: dict[str, str]  # {角色ID: 头像URL}
    character_voice_ids: dict[str, str]  # {角色ID: voice_id}

    # === 完成剧本编辑 ===
    workflow_mode: str  # "create" | "edit"
    owner_key_hash: str  # private digest, never serialized
    original_snapshot: dict  # immutable structure and asset dependency baseline
    asset_plan: list[dict]
    selected_asset_ids: list[str]
    data_validation_errors: list[str]
    convert_progress: dict
    asset_progress: dict

    # === 工作流控制 ===
    current_step: str  # 当前步骤标识
    error_message: str  # 错误信息
    safety_passed: bool  # 是否通过安全审查
    safety_rejection_reason: str  # 安全审查未通过时的原因
    _review_action: str  # 路由信号："confirm" 或 "regenerate"


# === 步骤常量 ===
STEP_INIT = "init"
STEP_GENERATE_OUTLINE = "generate_outline"
STEP_REVIEW_OUTLINE = "review_outline"
STEP_GENERATE_FIRST_DRAFT = "generate_first_draft"
STEP_REVIEW_FIRST_DRAFT = "review_first_draft"
STEP_REVIEW_BY_LLM = "review_by_llm"
STEP_GENERATE_FINAL_DRAFT = "generate_final_draft"
STEP_REVIEW_FINAL = "review_final"
STEP_REVIEW_REPORT = "review_report"
STEP_CHECK_QUALITY = "check_game_quality"
STEP_REVIEW_QUALITY = "review_quality"
STEP_CONVERT = "convert_to_game_data"
STEP_REVIEW_GAME_DATA = "review_game_data"
STEP_SAVE = "save_to_database"
STEP_GENERATE_ASSETS = "generate_assets"
STEP_SAFETY_CHECK = "safety_check"
STEP_NORMALIZE_GAME_DATA = "normalize_game_data"
STEP_PREPARE_ASSET_PLAN = "prepare_asset_plan"
STEP_REVIEW_ASSET_PLAN = "review_asset_plan"

# 步骤标签（用于前端显示）
STEP_LABELS: dict[str, str] = {
    STEP_INIT: "初始化",
    STEP_GENERATE_OUTLINE: "生成大纲",
    STEP_REVIEW_OUTLINE: "大纲审阅",
    STEP_GENERATE_FIRST_DRAFT: "生成初稿",
    STEP_REVIEW_FIRST_DRAFT: "初稿审阅",
    STEP_REVIEW_BY_LLM: "AI审稿",
    STEP_GENERATE_FINAL_DRAFT: "生成终稿",
    STEP_REVIEW_REPORT: "审稿意见确认",
    STEP_REVIEW_FINAL: "终稿确认",
    STEP_CHECK_QUALITY: "检查剧本质量",
    STEP_REVIEW_QUALITY: "质量检查结果",
    STEP_CONVERT: "数据转化",
    STEP_REVIEW_GAME_DATA: "游戏数据确认",
    STEP_SAVE: "保存完成",
    STEP_GENERATE_ASSETS: "资源生成",
    STEP_SAFETY_CHECK: "安全审查",
    STEP_NORMALIZE_GAME_DATA: "校验游戏数据",
    STEP_PREPARE_ASSET_PLAN: "分析资源变更",
    STEP_REVIEW_ASSET_PLAN: "资源更新确认",
}

# 需要用户确认的步骤（有 interrupt）
INTERRUPT_STEPS = {
    STEP_REVIEW_REPORT,
    STEP_REVIEW_QUALITY,
    STEP_REVIEW_OUTLINE,
    STEP_REVIEW_FIRST_DRAFT,
    STEP_REVIEW_FINAL,
    STEP_REVIEW_GAME_DATA,
    STEP_SAFETY_CHECK,
    STEP_REVIEW_ASSET_PLAN,
}
