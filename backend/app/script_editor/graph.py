"""
Script Generation Graph — LangGraph StateGraph 定义
"""

import logging
from typing import Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.script_editor.nodes.convert import convert_to_game_data
from app.script_editor.nodes.final_draft import generate_final_draft
from app.script_editor.nodes.first_draft import generate_first_draft
from app.script_editor.nodes.init_node import init_workflow
from app.script_editor.nodes.outline import generate_outline
from app.script_editor.nodes.review import review_by_llm
from app.script_editor.nodes.review_nodes import (
    review_final,
    review_first_draft,
    review_game_data,
    review_outline,
)
from app.script_editor.nodes.safety_check import safety_check
from app.script_editor.nodes.save import generate_assets, save_to_database
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
) -> Literal["convert_to_game_data", "safety_check"]:
    """游戏数据审阅后路由：确认→安全审查，重新生成→重新转化"""
    action = state.get("_review_action", "confirm")
    if action == "regenerate":
        return "convert_to_game_data"
    return "safety_check"


def _route_after_safety_check(
    state: ScriptGenState,
) -> Literal["save_to_database", "review_game_data"]:
    """安全审查后路由：通过→保存，未通过→返回修改"""
    if state.get("safety_passed", False):
        return "save_to_database"
    return "review_game_data"


def _route_after_save(state: ScriptGenState) -> Literal["generate_assets", "end"]:
    """保存失败时停止工作流，避免继续生成资产并误报完成。"""
    if state.get("error_message"):
        return "end"
    return "generate_assets"


# === 构建图 ===


def build_script_gen_graph():
    """
    构建剧本生成工作流图

    拓扑：
    START → init → generate_outline → review_outline ←─→ generate_outline
      → generate_first_draft → review_first_draft ←─→ generate_first_draft
      → review_by_llm → generate_final_draft → review_final ←─→ generate_final_draft
      → convert_to_game_data → review_game_data ←─→ convert_to_game_data
      → safety_check → (pass) → save_to_database → (success) → generate_assets → END
                                              └── (error) → END
                   └── (fail) → review_game_data
    """
    builder = StateGraph(ScriptGenState)

    # 添加所有节点
    builder.add_node("init_workflow", init_workflow)
    builder.add_node("generate_outline", generate_outline)
    builder.add_node("review_outline", review_outline)
    builder.add_node("generate_first_draft", generate_first_draft)
    builder.add_node("review_first_draft", review_first_draft)
    builder.add_node("review_by_llm", review_by_llm)
    builder.add_node("generate_final_draft", generate_final_draft)
    builder.add_node("review_final", review_final)
    builder.add_node("convert_to_game_data", convert_to_game_data)
    builder.add_node("review_game_data", review_game_data)
    builder.add_node("save_to_database", save_to_database)
    builder.add_node("generate_assets", generate_assets)
    builder.add_node("safety_check", safety_check)

    # 添加边
    builder.add_edge(START, "init_workflow")
    builder.add_edge("init_workflow", "generate_outline")
    builder.add_edge("generate_outline", "review_outline")

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
    builder.add_edge("review_by_llm", "generate_final_draft")
    builder.add_edge("generate_final_draft", "review_final")

    # 终稿审阅后条件路由
    builder.add_conditional_edges(
        "review_final",
        _route_after_final_review,
        ["generate_final_draft", "convert_to_game_data"],
    )

    # 数据转化 → 数据审阅
    builder.add_edge("convert_to_game_data", "review_game_data")

    # 数据审阅后条件路由（确认→安全审查，重新生成→重新转化）
    builder.add_conditional_edges(
        "review_game_data",
        _route_after_game_data_review,
        ["convert_to_game_data", "safety_check"],
    )

    # 安全审查后条件路由（通过→保存，未通过→返回修改）
    builder.add_conditional_edges(
        "safety_check",
        _route_after_safety_check,
        ["save_to_database", "review_game_data"],
    )

    # 保存成功后才生成资源；保存失败则保留 error_message 并停止
    builder.add_conditional_edges(
        "save_to_database",
        _route_after_save,
        {"generate_assets": "generate_assets", "end": END},
    )
    builder.add_edge("generate_assets", END)

    # 使用 MemorySaver 编译
    memory = MemorySaver()
    graph = builder.compile(checkpointer=memory)

    return graph


# 全局图实例（懒加载）
_graph = None


def get_script_gen_graph():
    """获取全局图实例"""
    global _graph
    if _graph is None:
        _graph = build_script_gen_graph()
    return _graph
