"""
submit_final_vote tool
用于提交最终投票

限制: 仅在 vote 阶段可调用
数据来源: 阶段信息从 state 获取
"""

import asyncio
from datetime import datetime

from langchain.tools import ToolRuntime, tool
from langgraph.config import get_stream_writer
from pydantic import BaseModel, Field

from app.agents.context import get_db_session

# 允许调用此工具的阶段
ALLOWED_STAGES = ["vote"]

# Per-session locks for concurrent vote safety
_vote_locks: dict[str, asyncio.Lock] = {}


class VoteInput(BaseModel):
    """投票输入参数"""

    suspect_name: str = Field(description="你投票认为是凶手的角色名")
    reasoning: str = Field(description="你的投票理由，简述为什么认为此人是凶手")


@tool(args_schema=VoteInput)
async def submit_final_vote(suspect_name: str, reasoning: str, runtime: ToolRuntime) -> str:
    """
    提交最终投票。

    仅在投票阶段可调用。
    指认你认为的凶手并说明理由。
    注意: 每位玩家只能投票一次!

    Args:
        suspect_name: 你认为是凶手的角色名
        reasoning: 投票理由

    Returns:
        str: 投票确认信息
    """
    # 发送流式状态消息
    writer = get_stream_writer()
    writer("正在提交投票...")

    state = runtime.state

    # 检查阶段限制
    current_stage = state.get("current_stage", "")
    if current_stage not in ALLOWED_STAGES:
        print(f"当前阶段为「{current_stage}」，无法投票。此工具仅在投票阶段可用。")
        return f"当前阶段为「{current_stage}」，无法投票。此工具仅在投票阶段可用。"

    # 从 state 获取上下文
    session_id = state.get("session_id", "")
    character_id = state.get("character_id", "")
    character_name_map = state.get("character_name_map", {})
    db_session = get_db_session()

    if db_session is None:
        print("投票失败：数据库连接不可用。")
        return "投票失败：数据库连接不可用。"

    # 根据角色名找到角色ID
    suspect_id = None
    for cid, cname in character_name_map.items():
        if cname == suspect_name:
            suspect_id = cid
            break

    if not suspect_id:
        print(f"投票失败：找不到名为「{suspect_name}」的角色。请确认角色名称正确。")
        return f"投票失败：找不到名为「{suspect_name}」的角色。请确认角色名称正确。"

    from app.db.models import GameRecord, GameSession, PlayerState, RecordType

    # 使用 per-session 锁确保并发投票的 DB 读写安全
    lock = _vote_locks.setdefault(session_id, asyncio.Lock())

    async with lock:
        try:
            from sqlalchemy import select

            # 清除会话缓存，确保读取最新数据
            db_session.expire_all()

            # 检查是否已投票
            result = await db_session.execute(
                select(PlayerState).where(
                    PlayerState.session_id == session_id,
                    PlayerState.character_id == character_id,
                )
            )
            player_state = result.scalar_one_or_none()

            if not player_state:
                print("投票失败：玩家状态不存在。")
                return "投票失败：玩家状态不存在。"

            if player_state.has_voted:
                print("投票失败：你已经投过票了，不能重复投票！")
                return "投票失败：你已经投过票了，不能重复投票！"

            # 获取游戏会话（更新投票记录）
            session_result = await db_session.execute(
                select(GameSession).where(GameSession.session_id == session_id)
            )
            game_session = session_result.scalar_one_or_none()

            if not game_session:
                print("投票失败：游戏会话不存在。")
                return "投票失败：游戏会话不存在。"

            # 更新玩家投票状态
            player_state.has_voted = True
            player_state.voted_for = suspect_id
            player_state.vote_reasoning = reasoning

            # 更新游戏会话的投票记录
            # 注意：必须创建新dict对象，否则SQLAlchemy无法检测JSON列变更
            votes = dict(game_session.votes or {})
            votes[character_id] = {
                "suspect_id": suspect_id,
                "suspect_name": suspect_name,
                "reasoning": reasoning,
            }
            game_session.votes = votes

            # 记录投票行为
            voter_name = character_name_map.get(character_id, "")
            record = GameRecord(
                session_id=session_id,
                record_type=RecordType.VOTE.value,
                stage="vote",
                speaker_character_id=character_id,
                speaker_name=voter_name,
                raw_content=f"投票给「{suspect_name}」，理由：{reasoning}",
                timestamp=datetime.now(),
            )
            db_session.add(record)

            await db_session.commit()
            print(f"✓ 投票成功！\n你已投票给「{suspect_name}」。\n理由：{reasoning}")
            return f"✓ 投票成功！\n你已投票给「{suspect_name}」。\n理由：{reasoning}"

        except Exception as e:
            await db_session.rollback()
            print(f"投票失败：{str(e)}")
            return f"投票失败：{str(e)}"
