"""
SpeechScheduler - 发言调度器
实现自由发言阶段的AI玩家发言倾向评估和调度
"""

import random
from dataclasses import dataclass
from typing import Any


@dataclass
class SpeechTendency:
    """发言倾向评分结果"""

    character_id: str
    character_name: str
    score: float
    components: dict[str, float]  # 评分各组成部分


class SpeechScheduler:
    """
    发言调度器：主要在“自由发言”阶段，评估AI玩家的发言倾向并“涌现”出主动发言者

    功能：
    1. 计算AI玩家的发言倾向评分
    2. 根据评分选择下一位发言者
    3. 处理真人玩家的特权操作（插队、跳过、推进）

    发言倾向评分公式:
    score = α * 被怀疑强度 + β * 主动怀疑强度 + γ * 发言机会成本

    参数说明：
    - α (ALPHA) = 0.4: 被怀疑强度权重 - 被怀疑越多越想发言辩解
    - β (BETA) = 0.3: 主动怀疑强度权重 - 怀疑别人越多越想发言指控
    - γ (GAMMA) = 0.3: 发言机会成本权重 - 沉默越久越需要发言
    """

    # 权重参数
    ALPHA = 0.4  # 被怀疑强度权重
    BETA = 0.3  # 主动怀疑强度权重
    GAMMA = 0.3  # 发言机会成本权重

    # 沉默轮次归一化基数
    MAX_WAIT_NORMALIZATION = 3

    def __init__(self):
        """初始化调度器"""
        # 最小发言间隔（避免同一角色连续发言）
        self.min_speech_interval = 1
        # 最近发言记录
        self.recent_speakers: list[str] = []

    async def calculate_speech_tendency(self, player_state: dict[str, Any]) -> SpeechTendency:
        """
        计算单个玩家的发言倾向评分

        Args:
            player_state: 玩家状态字典，包含：
                - character_id: 角色ID
                - character_name: 角色名称
                - suspected_intensity: 被怀疑强度 (0.0-1.0，同时反映辩解欲望)
                - suspicion: 怀疑图谱 {target_id: score}
                - wait_rounds: 沉默轮次

        Returns:
            SpeechTendency: 发言倾向评分结果
        """
        character_id = player_state.get("character_id", "")
        character_name = player_state.get("character_name", "未知")

        # 被怀疑强度: 越高越想发言辩解
        suspected = float(player_state.get("suspected_intensity", 0.0))

        # 主动怀疑强度: 对别人怀疑越多越想发言
        suspicion_map = player_state.get("suspicion", {})
        if suspicion_map:
            active_suspicion = sum(float(v) for v in suspicion_map.values()) / len(suspicion_map)
        else:
            active_suspicion = 0.0

        # 发言机会成本: 沉默越久越需要发言
        wait_rounds = int(player_state.get("wait_rounds", 0))
        opportunity_cost = min(wait_rounds / self.MAX_WAIT_NORMALIZATION, 1.0)

        # 计算总分
        score = (
            self.ALPHA * suspected + self.BETA * active_suspicion + self.GAMMA * opportunity_cost
        )

        # 限制在0-1范围
        score = min(max(score, 0.0), 1.0)

        return SpeechTendency(
            character_id=character_id,
            character_name=character_name,
            score=score,
            components={
                "suspected": suspected,
                "active_suspicion": active_suspicion,
                "opportunity_cost": opportunity_cost,
            },
        )

    async def select_next_speaker(
        self,
        player_states: list[dict[str, Any]],
        human_character_id: str = "",
    ) -> tuple[str, SpeechTendency] | None:
        """
        选择下一位发言者

        优先级：
        1. 本轮尚未发言的AI玩家（按倾向评分加权随机）
        2. 已发言过的AI玩家（按倾向评分加权随机）
        同时排除最近刚发言的角色（避免连续发言）

        Args:
            player_states: 所有玩家状态列表
            human_character_id: 真人玩家角色ID

        Returns:
            Optional[Tuple[str, SpeechTendency]]: (角色ID, 发言倾向) 或 None
        """
        # 构建候选者：排除真人玩家和最近发言者
        candidates: list[tuple[str, SpeechTendency, bool]] = []  # (char_id, tendency, has_spoken)

        for state in player_states:
            char_id = state.get("character_id")
            if not isinstance(char_id, str):
                continue
            if char_id == human_character_id:
                continue
            if char_id in self.recent_speakers[-self.min_speech_interval :]:
                continue

            tendency = await self.calculate_speech_tendency(state)
            has_spoken = bool(state.get("has_spoken_this_round", False))
            candidates.append((char_id, tendency, has_spoken))

        # 放宽限制：如果排除最近发言者后无候选，重新加入
        if not candidates:
            for state in player_states:
                char_id = state.get("character_id")
                if not isinstance(char_id, str):
                    continue
                if char_id == human_character_id:
                    continue
                tendency = await self.calculate_speech_tendency(state)
                has_spoken = bool(state.get("has_spoken_this_round", False))
                candidates.append((char_id, tendency, has_spoken))

        if not candidates:
            return None

        # 分层：未发言优先
        not_spoken = [(cid, t) for cid, t, spoken in candidates if not spoken]
        has_spoken = [(cid, t) for cid, t, spoken in candidates if spoken]

        # 选择层：优先从"未发言"层选，若为空则从"已发言"层选
        pool = not_spoken if not_spoken else has_spoken

        return self._weighted_random_pick(pool)

    def _weighted_random_pick(
        self, candidates: list[tuple[str, SpeechTendency]]
    ) -> tuple[str, SpeechTendency] | None:
        """从候选者中加权随机选择（前3名）"""
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[1].score, reverse=True)
        top = candidates[:3]
        if len(top) == 1:
            return top[0]
        weights = [c[1].score + 0.1 for c in top]
        total = sum(weights)
        r = random.random() * total
        cumulative = 0.0
        for char_id, tendency in top:
            cumulative += tendency.score + 0.1
            if r <= cumulative:
                return (char_id, tendency)
        return top[0]

    def record_speech(self, character_id: str):
        """
        记录发言者

        Args:
            character_id: 发言者角色ID
        """
        self.recent_speakers.append(character_id)
        # 保持最近10条记录
        if len(self.recent_speakers) > 10:
            self.recent_speakers = self.recent_speakers[-10:]

    async def check_round_completion(
        self, player_states: list[dict[str, Any]], min_speeches_per_player: int = 1
    ) -> bool:
        """
        检查当前轮次是否可以由玩家主动跳过，而不必等待所有玩家用光发言次数
        检查条件：所有玩家至少发言过一次

        Args:
            player_states: 玩家状态列表
            min_speeches_per_player: 每个玩家最少发言次数

        Returns:
            bool: 是否可以跳过
        """
        for state in player_states:
            speeches = int(state.get("speeches_this_round", 0))
            if speeches < min_speeches_per_player:
                return False
        return True

    async def get_speech_order(
        self,
        player_states: list[dict[str, Any]],
        human_character_id: str = "",
        is_sequential: bool = False,
    ) -> list[str]:
        """
        获取发言顺序

        Args:
            player_states: 玩家状态列表
            human_character_id: 真人玩家角色ID
            is_sequential: 是否是顺序发言

        Returns:
            List[str]: 发言顺序（角色ID列表）
        """
        if is_sequential:
            # 顺序发言：返回原始顺序
            return [s.get("character_id", "<Unknown>") for s in player_states]
        else:
            # 自由发言：按发言倾向排序
            candidates = []
            for state in player_states:
                char_id = state.get("character_id")
                if char_id == human_character_id:
                    continue
                tendency = await self.calculate_speech_tendency(state)
                candidates.append((char_id, tendency.score))

            candidates.sort(key=lambda x: x[1], reverse=True)
            return [c[0] for c in candidates]
