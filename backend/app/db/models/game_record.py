"""
GameRecord model - 游戏记录数据模型
存储游戏过程中的所有对话和事件
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.game_session import GameSession


class RecordType(str, Enum):
    """记录类型枚举"""

    SYSTEM = "system"  # 系统通知 (剧情推进、线索展示等)
    SPEECH = "speech"  # 角色发言
    VOTE = "vote"  # 投票记录
    REACTION = "reaction"  # 心理反应更新 (内部记录，不展示给玩家)
    SUMMARY = "summary"  # 阶段总结


class GameRecord(Base):
    """
    游戏对话记录
    记录游戏中发生的所有事件和对话
    """

    __tablename__ = "game_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("game_sessions.session_id", ondelete="CASCADE"), nullable=False
    )

    # 记录类型
    record_type: Mapped[str] = mapped_column(String(20), default=lambda: RecordType.SPEECH.value)

    # 所属阶段和轮次
    stage: Mapped[str | None] = mapped_column(String(30), nullable=True)
    round_num: Mapped[int] = mapped_column(Integer, default=0)

    # 发言者信息 (不使用外键，直接存储ID和名称)
    speaker_character_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    speaker_name: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # 内容
    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 额外元数据 (注意: 不能使用 'metadata' 作为列名，SQLAlchemy保留字)
    extra_data: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # TTS 音频 URL（按需生成的音频文件路径）
    audio_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # 时间戳
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    # 关系
    session: Mapped[GameSession] = relationship("GameSession", back_populates="records")

    def __repr__(self):
        return f"<GameRecord(id={self.id}, type={self.record_type}, speaker={self.speaker_name})>"

    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "record_type": self.record_type,
            "stage": self.stage,
            "round_num": self.round_num,
            "speaker_character_id": self.speaker_character_id,
            "speaker_name": self.speaker_name,
            "raw_content": self.raw_content,
            "summary_content": self.summary_content,
            "audio_url": self.audio_url,
            "timestamp": (self.timestamp.isoformat() if self.timestamp is not None else None),
        }

    def to_display_dict(self):
        """
        转换为用于展示的字典
        不包含内部记录（如reaction）
        """
        if str(self.record_type) == RecordType.REACTION:
            return None

        return {
            "id": self.id,
            "session_id": self.session_id,
            "record_type": self.record_type,  # Frontend expects record_type
            "stage": self.stage,
            "speaker_id": self.speaker_character_id,  # Frontend expects speaker_id
            "speaker_name": (
                self.speaker_name
                if str(self.record_type) in (RecordType.SPEECH, RecordType.VOTE)
                else None  # System messages don't have speaker_name
            ),
            "content": self.raw_content,
            "audio_url": self.audio_url,
            "timestamp": (self.timestamp.isoformat() if self.timestamp is not None else None),
        }
