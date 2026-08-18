"""
PlayerState model - 玩家状态数据模型

数据分为两类：
1. Agent内部状态: Agent自己维护和使用的状态（怀疑图谱、被怀疑记录）
2. 调度计算字段: 用于发言调度算法的字段（被怀疑强度、辩解欲望等）
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.game_session import GameSession


class PlayerState(Base):
    """
    玩家心理状态和发言倾向

    === Agent内部状态 ===
    Agent自己维护的状态，用于角色扮演决策：
    - suspicion_reasons: 我对其他玩家的怀疑及理由
    - suspected_by: 谁怀疑了我及理由、是否需要回应
    - player_perspectives: 我对其他玩家发言的要点提炼 (用于发言时回忆)

    === 调度计算字段 ===
    用于计算发言调度优先级，Agent不应关注这些"场外"信息：
    - suspicion: 简化的怀疑分数 (用于调度算法)
    - suspected_intensity: 被怀疑强度汇总 (用于调度算法，同时反映辩解欲望)
    - wait_rounds: 沉默轮次 (用于调度算法)
    """

    __tablename__ = "player_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("game_sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    character_id: Mapped[str] = mapped_column(String(36), nullable=False)

    # ========================================
    # Agent内部状态 (Agent自己维护和使用)
    # ========================================

    # 我对其他玩家的怀疑详情
    # 格式: {target_character_id: {"score": 0.0-1.0, "reason": "怀疑理由"}}
    suspicion_reasons: Mapped[dict] = mapped_column(JSON, default=dict)

    # 谁怀疑了我
    # 格式: {source_character_id: {"score": 0.0-1.0, "reason": "被怀疑理由", "need_response": bool}}
    suspected_by: Mapped[dict] = mapped_column(JSON, default=dict)

    # 我对其他玩家发言的要点提炼 (用于发言时回忆其他玩家说了什么)
    # 格式: {speaker_character_id: "该玩家的发言要点总结"}
    player_perspectives: Mapped[dict] = mapped_column(JSON, default=dict)

    # ========================================
    # 调度计算字段 (仅用于调度算法，Agent不应使用)
    # ========================================

    # 怀疑图谱 (简化版，仅分数，用于调度)
    # 格式: {target_character_id: suspicion_score}
    suspicion: Mapped[dict] = mapped_column(JSON, default=dict)

    # 被怀疑强度: 其他玩家对该玩家的怀疑程度汇总 (用于调度，同时反映辩解欲望)
    suspected_intensity: Mapped[float] = mapped_column(Float, default=0.0)

    # 沉默轮次: 距离上次发言已过的轮次 (用于调度)
    wait_rounds: Mapped[int] = mapped_column(Integer, default=0)

    # ========================================
    # 发言统计
    # ========================================

    # 本局游戏总发言次数
    total_speeches: Mapped[int] = mapped_column(Integer, default=0)
    # 本局游戏总字数
    total_words: Mapped[int] = mapped_column(Integer, default=0)

    # 自由发言阶段剩余发言次数 (由剧本难度决定，发言后递减，为0则不可再发言)
    remaining_speech_count: Mapped[int] = mapped_column(Integer, default=0)
    # 本轮是否已发言 (仅用于UI展示"结束当前阶段"按钮：当所有玩家至少发言一次后可手动推进)
    has_spoken_this_round: Mapped[bool] = mapped_column(Boolean, default=False)
    # 本轮发言次数 (自由发言阶段)
    speeches_this_round: Mapped[int] = mapped_column(Integer, default=0)

    # ========================================
    # 投票相关
    # ========================================

    # 是否已投票
    has_voted: Mapped[bool] = mapped_column(Boolean, default=False)
    # 投票给谁
    voted_for: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # 投票理由
    vote_reasoning: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # ========================================
    # 时间戳
    # ========================================

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )
    last_speech_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 关系
    session: Mapped[GameSession] = relationship("GameSession", back_populates="player_states")

    def __repr__(self):
        return f"<PlayerState(character_id={self.character_id}, wait_rounds={self.wait_rounds})>"

    def calculate_speech_tendency(
        self,
        alpha: float = 0.4,
        beta: float = 0.3,
        gamma: float = 0.3,
        max_wait_normalization: int = 3,
    ) -> float:
        """
        计算发言倾向评分 (用于调度算法)

        Args:
            alpha: 被怀疑强度权重 (默认0.4)
            beta: 主动怀疑强度权重 (默认0.3)
            gamma: 发言机会成本权重 (默认0.3)
            max_wait_normalization: 沉默轮次归一化基数 (默认3)

        Returns:
            float: 发言倾向评分 (0.0-1.0)
        """
        # 被怀疑强度: 越高越想发言辩解
        suspected = (
            self.suspected_intensity if isinstance(self.suspected_intensity, (int, float)) else 0.0
        )

        # 主动怀疑强度: 对别人怀疑越多越想发言
        suspicion_map = self.suspicion if isinstance(self.suspicion, dict) else {}
        active_suspicion = sum(suspicion_map.values()) / max(len(suspicion_map), 1)

        # 发言机会成本: 沉默越久越需要发言
        wait_rounds = self.wait_rounds if isinstance(self.wait_rounds, int) else 0
        opportunity_cost = min(wait_rounds / max_wait_normalization, 1.0)

        score = alpha * suspected + beta * active_suspicion + gamma * opportunity_cost

        return round(cast(float, score), 3)

    def get_agent_state(self, character_name_map: dict[str, str] = {}) -> dict[str, Any]:
        """
        获取Agent内部状态 (用于注入到AgentState)

        Args:
            character_name_map: character_id -> character_name 的映射

        Returns:
            Dict: Agent内部状态
        """
        # 转换 suspicion_reasons 的 key 从 id 到 name
        my_suspicion_graph = {}
        for target_id, data in (self.suspicion_reasons or {}).items():
            target_name = character_name_map.get(target_id, target_id)
            my_suspicion_graph[target_name] = data

        # 转换 suspected_by 的 key 从 id 到 name
        my_suspected_by = {}
        for source_id, data in (self.suspected_by or {}).items():
            source_name = character_name_map.get(source_id, source_id)
            my_suspected_by[source_name] = data

        # 转换 player_perspectives 的 key 从 id 到 name
        # 同时处理 LIST 格式的观点（累加存储）
        my_player_perspectives = {}
        for speaker_id, perspective in (self.player_perspectives or {}).items():
            speaker_name = character_name_map.get(speaker_id, speaker_id)
            if isinstance(perspective, list):
                # LIST格式: 用分号连接所有观点
                if perspective:
                    combined = "；".join(perspective)
                    my_player_perspectives[speaker_name] = combined
            else:
                # 兼容旧格式: 单条字符串
                if perspective:
                    my_player_perspectives[speaker_name] = perspective

        return {
            "my_suspicion_graph": my_suspicion_graph,
            "my_suspected_by": my_suspected_by,
            "my_player_perspectives": my_player_perspectives,
        }

    def to_dict(self):
        """转换为字典"""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "character_id": self.character_id,
            # Agent内部状态
            "suspicion_reasons": self.suspicion_reasons,
            "suspected_by": self.suspected_by,
            "player_perspectives": self.player_perspectives,
            # 调度字段
            "suspicion": self.suspicion,
            "suspected_intensity": self.suspected_intensity,
            "wait_rounds": self.wait_rounds,
            # 统计
            "total_speeches": self.total_speeches,
            "total_words": self.total_words,
            "remaining_speech_count": self.remaining_speech_count,
            "has_spoken_this_round": self.has_spoken_this_round,
            "speeches_this_round": self.speeches_this_round,
            "has_voted": self.has_voted,
            # 调度评分
            "speech_tendency": self.calculate_speech_tendency(),
        }
