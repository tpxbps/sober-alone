"""
Review (interrupt) nodes — 用户确认/编辑各步骤内容
"""

from langgraph.types import interrupt

from app.script_editor.state import (
    STEP_REVIEW_ASSET_PLAN,
    STEP_REVIEW_FINAL,
    STEP_REVIEW_FIRST_DRAFT,
    STEP_REVIEW_GAME_DATA,
    STEP_REVIEW_OUTLINE,
    STEP_REVIEW_REPORT,
    ScriptGenState,
)


def review_outline(state: ScriptGenState) -> dict:
    """用户审阅大纲 (interrupt)"""
    user_response = interrupt(
        {
            "step": STEP_REVIEW_OUTLINE,
            "step_label": "大纲确认" if state.get("outline_session") else "大纲审阅",
            "generated_content": state.get("outline", ""),
            "prompt_used": state.get("prompts", {}).get("generate_outline", ""),
        }
    )

    action = user_response.get("action", "confirm")
    content = user_response.get("content", state.get("outline", ""))

    result = {
        "outline": content,
        "current_step": STEP_REVIEW_OUTLINE,
        "_review_action": action,  # 用于路由判断
    }
    if state.get("outline_session"):
        result["outline_session"] = {**state["outline_session"], "final_outline": content}
    return result


def review_first_draft(state: ScriptGenState) -> dict:
    """用户审阅初稿 (interrupt)"""
    user_response = interrupt(
        {
            "step": STEP_REVIEW_FIRST_DRAFT,
            "step_label": "初稿审阅",
            "generated_content": state.get("first_draft", ""),
            "characters": state.get("characters", []),
            "prompt_used": state.get("prompts", {}).get("generate_first_draft", ""),
        }
    )

    action = user_response.get("action", "confirm")
    content = user_response.get("content", state.get("first_draft", ""))
    characters = user_response.get("characters", state.get("characters", []))

    return {
        "first_draft": content,
        "characters": characters,
        "current_step": STEP_REVIEW_FIRST_DRAFT,
        "_review_action": action,
    }


def review_report(state: ScriptGenState) -> dict:
    response = interrupt(
        {
            "step": STEP_REVIEW_REPORT,
            "step_label": "审稿意见确认",
            "generated_content": state.get("review_opinion", ""),
            "human_review": state.get("human_review", ""),
            "first_draft": state.get("first_draft", ""),
            "prompt_used": state.get("prompts", {}).get("review", ""),
        }
    )
    return {
        "review_opinion": response.get("content", state.get("review_opinion", "")),
        "human_review": response.get("human_review", state.get("human_review", "")),
        "current_step": STEP_REVIEW_REPORT,
        "_review_action": response.get("action", "confirm"),
    }


def review_final(state: ScriptGenState) -> dict:
    """用户确认终稿；兼容旧客户端传入的真人意见。"""
    user_response = interrupt(
        {
            "step": STEP_REVIEW_FINAL,
            "step_label": "终稿确认",
            "generated_content": state.get("final_draft", ""),
            "review_opinion": state.get("review_opinion", ""),
            "prompt_used": state.get("prompts", {}).get("generate_final_draft", ""),
        }
    )

    action = user_response.get("action", "confirm")
    content = user_response.get("content", state.get("final_draft", ""))
    human_review = user_response.get("human_review", state.get("human_review", ""))

    return {
        "final_draft": content,
        "human_review": human_review,
        "current_step": STEP_REVIEW_FINAL,
        "_review_action": action,
    }


def review_game_data(state: ScriptGenState) -> dict:
    """用户审阅结构化游戏数据 (interrupt)"""
    interrupt_payload = {
        "step": STEP_REVIEW_GAME_DATA,
        "step_label": "游戏数据确认",
        "game_data_sections": state.get("game_data_sections", {}),
        "prompt_used": state.get("prompts", {}).get("convert_to_game_data", ""),
        "workflow_mode": state.get("workflow_mode", "create"),
    }

    validation_errors = state.get("data_validation_errors", [])
    if validation_errors:
        interrupt_payload["validation_errors"] = validation_errors

    # Forward safety check rejection reason if present
    rejection_reason = state.get("safety_rejection_reason", "")
    if not state.get("safety_passed", True) and rejection_reason:
        interrupt_payload["rejected"] = True
        interrupt_payload["reason"] = rejection_reason

    user_response = interrupt(interrupt_payload)

    action = user_response.get("action", "confirm")
    edited_sections = user_response.get("game_data_sections", state.get("game_data_sections", {}))

    result = {
        "game_data_sections": edited_sections,
        "current_step": STEP_REVIEW_GAME_DATA,
        "_review_action": action,
    }

    if action == "regenerate":
        result["convert_cache"] = {}

    # Clear rejection reason on confirm so next safety check starts fresh
    if action == "confirm":
        result["safety_rejection_reason"] = ""
        result["data_validation_errors"] = []

    return result


def review_asset_plan(state: ScriptGenState) -> dict:
    """Confirm exactly which changed or missing assets should be regenerated."""
    plan = state.get("asset_plan", [])
    user_response = interrupt(
        {
            "step": STEP_REVIEW_ASSET_PLAN,
            "step_label": "资源更新确认",
            "workflow_mode": "edit",
            "asset_plan": plan,
        }
    )

    published = {item.get("id") for item in plan if item.get("available")}
    selected = user_response.get("selected_asset_ids", [])
    if not isinstance(selected, list) or any(item not in published for item in selected):
        raise ValueError("selected_asset_ids 包含未发布或不可用的资源任务")

    return {
        "current_step": STEP_REVIEW_ASSET_PLAN,
        "selected_asset_ids": list(dict.fromkeys(selected)),
        "_review_action": "confirm",
    }
