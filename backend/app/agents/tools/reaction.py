"""
update_role_reaction tool
用于在线索分析阶段更新怀疑图谱

限制: 仅在 clue_analysis 阶段可调用
功能: 更新怀疑图谱（suspicion_reasons）- 支持同时更新多名角色
"""

from langchain.tools import ToolRuntime, tool
from langgraph.config import get_stream_writer
from pydantic import BaseModel, Field

from app.agents.context import get_db_session

# 允许调用此工具的阶段
ALLOWED_STAGES = ["clue_analysis"]


class CharacterSuspicion(BaseModel):
    """单个角色的怀疑信息"""

    character_name: str = Field(description="角色名称（必须为剧本中的角色）")
    suspicion_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="对目标角色的怀疑程度 0.0-1.0",
    )
    suspicion_reason: str = Field(
        default="",
        description="怀疑该角色的理由",
    )


class ClueAnalysisInput(BaseModel):
    """线索分析输入参数"""

    suspicion_updates: list[CharacterSuspicion] = Field(
        default_factory=list,
        description="需要更新的角色怀疑列表（可同时更新多名角色，如无需更新则为空列表）",
    )


@tool(args_schema=ClueAnalysisInput)
async def update_role_reaction(
    suspicion_updates: list[CharacterSuspicion],
    runtime: ToolRuntime,
) -> str:
    """
    仅在线索分析阶段可用，用于更新你对其他角色的怀疑程度。

    当线索让你对某些角色产生或改变怀疑时调用此工具。
    可以同时更新多名角色的怀疑程度。

    注意:
    - 只有当线索确实让你对某些角色产生或改变怀疑时，才需要更新怀疑图谱
    - 怀疑程度应该是基于线索的理性判断，不要凭空猜测

    Args:
        suspicion_updates: 需要更新的角色怀疑列表，每项包含角色名、怀疑程度和理由

    Returns:
        str: 操作结果
    """
    # 发送流式状态消息
    writer = get_stream_writer()
    writer("线索影响着我的看法...")

    state = runtime.state

    # 检查阶段限制
    current_stage = state.get("current_stage", "")
    if current_stage not in ALLOWED_STAGES:
        return f"当前阶段为「{current_stage}」，无法更新怀疑。此工具仅在线索分析阶段可用。"

    # 从 state 获取上下文
    session_id = state.get("session_id", "")
    character_id = state.get("character_id", "")
    character_name_map = state.get("character_name_map", {})
    character_names = state.get("character_names", [])
    db_session = get_db_session()

    if db_session is None:
        return "无法更新状态：数据库连接不可用。"

    # 如果没有更新，直接返回
    if not suspicion_updates:
        return "未提供任何怀疑更新。"

    # 校验所有目标角色名称
    target_ids = {}  # {character_name: character_id}
    for update in suspicion_updates:
        target_name = update.character_name

        if target_name not in character_names:
            return (
                f"错误：角色「{target_name}」不在当前剧本中。可用角色：{', '.join(character_names)}"
            )

        # 根据角色名找到角色ID
        target_id = None
        for cid, cname in character_name_map.items():
            if cname == target_name:
                target_id = cid
                break

        if not target_id:
            return f"错误：找不到角色「{target_name}」的ID。"

        target_ids[target_name] = target_id

    try:
        from sqlalchemy import select
        from sqlalchemy.orm.attributes import flag_modified

        from app.db.models import PlayerState

        # 获取当前玩家状态
        result = await db_session.execute(
            select(PlayerState).where(
                PlayerState.session_id == session_id,
                PlayerState.character_id == character_id,
            )
        )
        player_state = result.scalar_one_or_none()

        if not player_state:
            return "无法更新状态：玩家状态不存在。"

        # 更新怀疑图谱（支持多名角色）
        updated_characters = []
        suspicion_reasons = dict(player_state.suspicion_reasons or {})
        suspicion = dict(player_state.suspicion or {})

        for update in suspicion_updates:
            target_name = update.character_name
            target_id = target_ids[target_name]
            score = update.suspicion_score
            reason = update.suspicion_reason

            # 获取当前怀疑数据
            current_data = suspicion_reasons.get(target_id, {"score": 0.0, "reason": ""})

            # 更新怀疑值（取较大值，而非累加）
            new_score = max(current_data.get("score", 0.0), score)

            # 合并理由
            existing_reason = current_data.get("reason", "")
            if reason:
                if existing_reason:
                    new_reason = f"{existing_reason}; {reason}"
                else:
                    new_reason = reason
            else:
                new_reason = existing_reason

            suspicion_reasons[target_id] = {"score": new_score, "reason": new_reason}
            suspicion[target_id] = new_score

            updated_characters.append(
                f"{target_name}({score:.1f}{' - ' + reason if reason else ''})"
            )

        player_state.suspicion_reasons = suspicion_reasons
        player_state.suspicion = suspicion
        flag_modified(player_state, "suspicion_reasons")
        flag_modified(player_state, "suspicion")

        await db_session.commit()

        return f"【怀疑更新】{'; '.join(updated_characters)}"

    except Exception as e:
        await db_session.rollback()
        return f"更新状态失败: {str(e)}"
