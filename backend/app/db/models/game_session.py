"""
GameSession model - 游戏会话数据模型
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.game_record import GameRecord
    from app.db.models.player_state import PlayerState


def generate_uuid() -> str:
    return str(uuid.uuid4())


class GameStatus(str, Enum):
    """游戏状态枚举"""

    WAITING = "waiting"  # 等待玩家加入
    INITIALIZING = "initializing"  # 初始化中
    IN_PROGRESS = "in_progress"  # 进行中
    VOTING = "voting"  # 投票阶段
    REVIEW = "review"  # 复盘阶段
    FINISHED = "finished"  # 已结束


class GameStage(str, Enum):
    """游戏阶段枚举"""

    INTRO = "intro"  # 自我介绍
    CLUE_ANALYSIS = "clue_analysis"  # 线索分析
    FREE_DISCUSSION = "free_discussion"  # 自由讨论
    SUMMARY = "summary"  # 总结发言
    VOTE = "vote"  # 最终投票
    REVIEW = "review"  # 复盘揭晓
    COMPLETED = "completed"  # 游戏结束


class GameSession(Base):
    """
    游戏对局会话
    存储每一局游戏的核心状态信息
    """

    __tablename__ = "game_sessions"

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    script_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("scripts.script_id", ondelete="CASCADE"), nullable=False
    )

    # 游戏状态
    status: Mapped[str] = mapped_column(String(20), default=lambda: GameStatus.WAITING.value)
    current_stage: Mapped[str] = mapped_column(String(30), default=lambda: GameStage.INTRO.value)
    current_round: Mapped[int] = mapped_column(Integer, default=0)

    # 玩家映射
    # player_threads: {"character_id": "thread_id"} - 用于Agent checkpoint
    player_threads: Mapped[dict] = mapped_column(JSON, default=dict)
    # player_types: {"character_id": "human"/"ai"}
    player_types: Mapped[dict] = mapped_column(JSON, default=dict)
    # 真人玩家选择的角色ID
    human_character_id: Mapped[str] = mapped_column(String(36), nullable=True)

    # 发言控制
    # speech_queue: [character_id, ...] - 发言队列
    speech_queue: Mapped[list] = mapped_column(JSON, default=list)
    # 当前发言角色
    current_speaker: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # 本轮已发言的角色列表 (用于自由发言阶段判断是否所有人都发过言)
    round_speakers: Mapped[list] = mapped_column(JSON, default=list)

    # 投票结果: {"voter_id": {"suspect_id": xxx, "reasoning": xxx}}
    votes: Mapped[dict] = mapped_column(JSON, default=dict)

    # 最终投票结果
    final_suspect_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    final_suspect_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    vote_result: Mapped[dict] = mapped_column(JSON, default=dict)  # 投票统计结果

    # MVP评选
    mvp_character_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    mvp_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 关系
    player_states: Mapped[list[PlayerState]] = relationship(
        "PlayerState", back_populates="session", cascade="all, delete-orphan"
    )
    records: Mapped[list[GameRecord]] = relationship(
        "GameRecord", back_populates="session", cascade="all, delete-orphan"
    )
    script = relationship("Script", back_populates="sessions")

    def __repr__(self):
        return f"<GameSession(session_id={self.session_id}, status={self.status}, stage={self.current_stage})>"

    def to_dict(self):
        """转换为字典"""
        return {
            "session_id": self.session_id,
            "script_id": self.script_id,
            "status": self.status,
            "current_stage": self.current_stage,
            "current_round": self.current_round,
            "player_threads": self.player_threads,
            "player_types": self.player_types,
            "human_character_id": self.human_character_id,
            "speech_queue": self.speech_queue,
            "current_speaker": self.current_speaker,
            "round_speakers": self.round_speakers,
            "votes": self.votes,
            "created_at": (self.created_at.isoformat() if self.created_at is not None else None),
            "started_at": (self.started_at.isoformat() if self.started_at is not None else None),
            "finished_at": (self.finished_at.isoformat() if self.finished_at is not None else None),
        }
