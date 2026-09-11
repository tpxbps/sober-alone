"""Clue analysis writes the same absolute role state as speech reactions."""

from langchain.tools import ToolRuntime, tool
from langgraph.config import get_stream_writer
from sqlalchemy import select

from app.agents.context import get_db_session
from app.agents.reaction import PsychologicalUpdate
from app.agents.role_state import apply_beliefs
from app.db.models import PlayerState


@tool(args_schema=PsychologicalUpdate)
async def update_role_reaction(
    runtime: ToolRuntime,
    suspicion_changes: list | None = None,
    suspected_by_changes: list | None = None,
) -> str:
    """仅在线索分析阶段使用。综合已有心理状态、公开线索和玩家发言，提交涉及角色的最新绝对状态。

    分数可以降低或归零；理由覆盖旧理由；无需更新的角色不提交。可同时更新我怀疑谁和谁怀疑我。
    """
    state = runtime.state
    if state.get("current_stage") != "clue_analysis":
        return "此工具仅在线索分析阶段可用。"
    db = get_db_session()
    if db is None:
        return "无法更新状态：数据库连接不可用。"
    get_stream_writer()("线索影响着我的看法...")
    try:
        update = PsychologicalUpdate.model_validate(
            {
                "suspicion_changes": suspicion_changes or [],
                "suspected_by_changes": suspected_by_changes or [],
            }
        )
        player = await db.scalar(
            select(PlayerState).where(
                PlayerState.session_id == state["session_id"],
                PlayerState.character_id == state["character_id"],
            )
        )
        if player is None:
            return "无法更新状态：玩家状态不存在。"
        names = state.get("character_name_map", {})
        apply_beliefs(player, update.to_reaction(), names)
        await db.commit()
        import json

        return "【最新心理状态】" + json.dumps(player.get_agent_state(names), ensure_ascii=False)
    except ValueError as exc:
        await db.rollback()
        return f"状态未写入，请修正完整参数后重试：{exc}"
    except Exception:
        await db.rollback()
        return "更新状态失败，请重试。"
