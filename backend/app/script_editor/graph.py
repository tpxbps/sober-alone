"""
Script Generation Graph — LangGraph StateGraph 定义
"""

import logging
from typing import Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.script_editor.nodes.convert import convert_to_game_data
from app.script_editor.nodes.editing import build_asset_plan, normalize_edited_game_data
from app.script_editor.nodes.final_draft import generate_final_draft
from app.script_editor.nodes.first_draft import generate_first_draft
from app.script_editor.nodes.init_node import init_workflow
from app.script_editor.nodes.outline import generate_outline
from app.script_editor.nodes.quality_check import review_quality
from app.script_editor.nodes.review import review_by_llm
from app.script_editor.nodes.review_nodes import (
    review_asset_plan,
    review_final,
    review_first_draft,
    review_game_data,
    review_outline,
    review_report,
)
from app.script_editor.nodes.safety_check import safety_check
from app.script_editor.nodes.save import generate_assets, save_to_database
from app.script_editor.services.execution import observable_node
from app.script_editor.state import ScriptGenState

logger = logging.getLogger(__name__)


# === 路由函数 ===


def _route_after_outline_review(
    state: ScriptGenState,
) -> Literal["generate_outline", "generate_first_draft"]:
    """大纲审阅后路由：确认→初稿，重新生成→大纲"""
    action = state.get("_review_action", "confirm")
    if action == "regenerate":
        return "generate_outline"
    return "generate_first_draft"


def _route_after_first_draft_review(
    state: ScriptGenState,
) -> Literal["generate_first_draft", "review_by_llm"]:
    """初稿审阅后路由：确认→AI审稿，重新生成→初稿"""
    action = state.get("_review_action", "confirm")
    if action == "regenerate":
        return "generate_first_draft"
    return "review_by_llm"


def _route_after_final_review(
    state: ScriptGenState,
) -> Literal["generate_final_draft", "convert_to_game_data"]:
    """终稿审阅后路由：确认→数据转化，重新生成→终稿"""
    action = state.get("_review_action", "confirm")
    if action == "regenerate":
        return "generate_final_draft"
    return "convert_to_game_data"


def _route_after_game_data_review(
    state: ScriptGenState,
) -> Literal["convert_to_game_data", "normalize_game_data"]:
    """游戏数据审阅后路由：确认→安全审查，重新生成→重新转化"""
    action = state.get("_review_action", "confirm")
    if action == "regenerate":
        return "convert_to_game_data"
    return "normalize_game_data"


def _route_from_start(state: ScriptGenState) -> Literal["init_workflow", "review_game_data"]:
    if state.get("workflow_mode") == "edit":
        return "review_game_data"
    return "init_workflow"


def _route_after_normalize(
    state: ScriptGenState,
) -> Literal["review_game_data", "safety_check"]:
    if state.get("data_validation_errors"):
        return "review_game_data"
    return "safety_check"


def _route_after_safety_check(
    state: ScriptGenState,
) -> Literal[
    "prepare_asset_plan",
    "save_to_database",
    "review_game_data",
    "normalize_game_data",
    "review_failure",
]:
    """安全审查后路由：通过→保存，未通过→返回修改"""
    from app.script_editor.nodes.safety_check import safety_approved

    if safety_approved(state):
        if state.get("workflow_mode") == "edit":
            return "prepare_asset_plan"
        return "save_to_database"
    return "review_failure" if state.get("retry_step") == "safety_check" else "review_game_data"


def _route_after_save(state: ScriptGenState) -> Literal["generate_assets", "review_failure"]:
    """保存失败时停止工作流，避免继续生成资产并误报完成。"""
    if state.get("error_message"):
        return "review_failure"
    return "generate_assets"


def review_failure(state):
    from langgraph.types import interrupt

    response = interrupt(
        {
            "step": state.get("current_step"),
            "retry_step": state.get("retry_step"),
            "error_message": state.get("error_message"),
            "failed": True,
        }
    )
    if response.get("action") not in ("retry_failed", "regenerate"):
        raise ValueError("失败任务只能重试")
    return {"error_message": "", "_review_action": "retry_failed"}


# === 构建图 ===


def build_script_gen_graph(checkpointer=None):
    """
    构建剧本生成工作流图

    拓扑：
    START → init → generate_outline → review_outline ←─→ generate_outline
      → generate_first_draft → review_first_draft ←─→ generate_first_draft
      → review_by_llm → review_report → generate_final_draft → review_final
      → convert_to_game_data → review_game_data ←─→ convert_to_game_data
      → normalize_game_data → safety_check（质检是审阅页的可选操作）
      → safety_check → (pass) → save_to_database → (success) → generate_assets → END
                                              └── (error) → review_failure
                   └── (fail) → review_game_data
    """
    builder = StateGraph(ScriptGenState)

    def add_node(name, fn):
        builder.add_node(name, observable_node(name, fn))

    # 添加所有节点
    builder.add_node("init_workflow", init_workflow)
    add_node("generate_outline", generate_outline)
    builder.add_node("review_outline", review_outline)
    add_node("generate_first_draft", generate_first_draft)
    builder.add_node("review_first_draft", review_first_draft)
    add_node("review_by_llm", review_by_llm)
    add_node("generate_final_draft", generate_final_draft)
    builder.add_node("review_final", review_final)
    builder.add_node("review_report", review_report)
    # Retained only to resume old checkpoints without creating another mandatory check.
    builder.add_node("check_game_quality", lambda state: {})
    builder.add_node("review_quality", review_quality)
    add_node("convert_to_game_data", convert_to_game_data)
    builder.add_node("review_game_data", review_game_data)
    builder.add_node("normalize_game_data", normalize_edited_game_data)
    builder.add_node("prepare_asset_plan", build_asset_plan)
    builder.add_node("review_asset_plan", review_asset_plan)
    add_node("save_to_database", save_to_database)
    add_node("generate_assets", generate_assets)
    add_node("safety_check", safety_check)

    # 添加边
    builder.add_conditional_edges(
        START,
        _route_from_start,
        ["init_workflow", "review_game_data"],
    )
    builder.add_edge("init_workflow", "generate_outline")
    from app.script_editor.outline.nodes import (
        check_outline,
        direct_outline,
        finalize_outline,
        wait_for_answer,
    )

    add_node("outline_director", direct_outline)
    builder.add_node("outline_wait", wait_for_answer)
    add_node("outline_finalize", finalize_outline)
    builder.add_node("outline_check", check_outline)
    from app.script_editor.outline.revisions import apply_outline_input

    add_node("outline_apply", apply_outline_input)
    outline_routes = {
        "direct": "outline_director",
        "write": "generate_outline",
        "wait": "outline_wait",
        "finalize": "outline_finalize",
        "check": "outline_check",
        "review": "review_outline",
        "apply": "outline_apply",
    }

    def outline_route(state):
        return (state.get("outline_session") or {}).get("next_action", "review")

    builder.add_conditional_edges("generate_outline", outline_route, outline_routes)
    builder.add_conditional_edges("outline_director", outline_route, outline_routes)
    builder.add_edge("outline_wait", "outline_apply")
    builder.add_conditional_edges("outline_apply", outline_route, outline_routes)
    builder.add_edge("outline_finalize", "review_outline")
    builder.add_conditional_edges("outline_check", outline_route, outline_routes)

    # 大纲审阅后条件路由
    builder.add_conditional_edges(
        "review_outline",
        _route_after_outline_review,
        ["generate_outline", "generate_first_draft"],
    )

    builder.add_edge("generate_first_draft", "review_first_draft")

    # 初稿审阅后条件路由
    builder.add_conditional_edges(
        "review_first_draft",
        _route_after_first_draft_review,
        ["generate_first_draft", "review_by_llm"],
    )

    # 审稿 → 生成终稿 → 终稿审阅
    builder.add_edge("review_by_llm", "review_report")
    builder.add_conditional_edges(
        "review_report",
        lambda s: (
            "review_by_llm" if s.get("_review_action") == "regenerate" else "generate_final_draft"
        ),
        ["review_by_llm", "generate_final_draft"],
    )
    builder.add_edge("generate_final_draft", "review_final")

    # 终稿审阅后条件路由
    builder.add_conditional_edges(
        "review_final",
        _route_after_final_review,
        ["generate_final_draft", "convert_to_game_data"],
    )

    # 数据转化 → 数据审阅
    builder.add_node("review_failure", review_failure)
    builder.add_conditional_edges(
        "review_failure",
        lambda s: s["retry_step"],
        ["convert_to_game_data", "safety_check", "save_to_database"],
    )
    builder.add_conditional_edges(
        "convert_to_game_data",
        lambda s: "review_failure" if s.get("error_message") else "review_game_data",
        ["review_failure", "review_game_data"],
    )

    # 数据审阅后条件路由（确认→规范化，重新生成→重新转化）
    builder.add_conditional_edges(
        "review_game_data",
        _route_after_game_data_review,
        ["convert_to_game_data", "normalize_game_data"],
    )

    builder.add_conditional_edges(
        "normalize_game_data",
        _route_after_normalize,
        ["review_game_data", "safety_check"],
    )

    builder.add_edge("check_game_quality", "review_game_data")
    builder.add_edge("review_quality", "review_game_data")

    # 安全审查后条件路由（通过→保存，未通过→返回修改）
    builder.add_conditional_edges(
        "safety_check",
        _route_after_safety_check,
        [
            "prepare_asset_plan",
            "save_to_database",
            "review_game_data",
            "normalize_game_data",
            "review_failure",
        ],
    )

    builder.add_edge("prepare_asset_plan", "review_asset_plan")
    builder.add_edge("review_asset_plan", "save_to_database")

    # 保存成功后才生成资源；保存失败则保留 error_message 并停止
    builder.add_conditional_edges(
        "save_to_database",
        _route_after_save,
        {"generate_assets": "generate_assets", "review_failure": "review_failure"},
    )
    builder.add_edge("generate_assets", END)

    graph = builder.compile(checkpointer=checkpointer or MemorySaver())

    return graph


# 全局图实例（懒加载）
_graph = None


def get_script_gen_graph():
    """获取全局图实例"""
    global _graph
    if _graph is None:
        _graph = build_script_gen_graph()
    return _graph


def set_script_gen_graph(checkpointer) -> None:
    """Install the process-wide graph backed by the lifespan-owned checkpointer."""
    global _graph
    _graph = build_script_gen_graph(checkpointer)
