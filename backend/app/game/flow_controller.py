"""
GameFlowController - 游戏流程控制器
管理游戏的整体进程和阶段转换
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.agents import AgentManager
from app.db.models import (
    GameRecord,
    GameSession,
    GameStage,
    GameStatus,
    PlayerState,
    RecordType,
)
from app.game.speech_scheduler import SpeechScheduler


@dataclass
class StageTransition:
    """阶段转换信息"""

    from_stage: str
    to_stage: str
    round_num: int
    message: str
    system_notice: str
    audio_key: str = ""  # 用于定位预生成的系统消息音频文件


class GameFlowController:
    """
    游戏流程控制器

    职责：
    1. 管理游戏整体流程（自我介绍→线索轮次→投票→复盘）
    2. 控制阶段转换
    3. 协调AgentManager和SpeechScheduler
    4. 处理玩家发言和状态更新

    游戏流程:
    1. 自我介绍 (intro) - 顺序发言
    2. 线索轮次×N (clue_analysis + free_discussion)
    3. 总结发言 (summary) - 顺序发言
    4. 投票 (vote)
    5. 复盘 (review)
    """

    def __init__(
        self,
        game_session: GameSession,
        script_data: dict[str, Any],
        agent_manager: AgentManager,
    ):
        """
        初始化流程控制器

        Args:
            game_session: 游戏会话对象
            script_data: 剧本数据（包含game_full_process等）
            agent_manager: Agent管理器
        """
        self.session = game_session
        self.script_data = script_data
        self.agent_manager = agent_manager

        # 发言调度器
        self.scheduler = SpeechScheduler()

        # 解析游戏流程
        self.game_process = script_data.get("game_full_process", [])
        self.current_process_index = 0
        self.current_child_index = 0  # 用于追踪 advancement 类型中的子阶段
        self.restore_cursor()

        # 角色信息缓存
        self.characters = script_data.get("characters", [])
        self.character_map = {c["character_id"]: c for c in self.characters}

    def restore_cursor(self) -> tuple[int, int]:
        """Restore the in-memory process cursor from persisted session fields.

        The public v0.1 schema deliberately keeps the cursor derivable instead of
        adding another pair of mutable columns. ``current_round`` is the 1-based
        advancement number while the persisted stage distinguishes each child
        phase and the vote/review tail.
        """
        if not self.game_process:
            self.current_process_index = 0
            self.current_child_index = 0
            return (0, 0)

        stage = self.session.current_stage
        indices_by_type: dict[str, list[int]] = {}
        for index, process in enumerate(self.game_process):
            indices_by_type.setdefault(process.get("type", ""), []).append(index)

        if stage in {GameStage.CLUE_ANALYSIS.value, GameStage.FREE_DISCUSSION.value}:
            candidates = indices_by_type.get("advancement", [])
            ordinal = max(int(self.session.current_round or 1) - 1, 0)
            if candidates:
                self.current_process_index = candidates[min(ordinal, len(candidates) - 1)]
        elif stage in {GameStage.SUMMARY.value, GameStage.VOTE.value}:
            candidates = indices_by_type.get("vote", [])
            if candidates:
                self.current_process_index = candidates[0]
        elif stage in {GameStage.REVIEW.value, GameStage.COMPLETED.value}:
            candidates = indices_by_type.get("review", [])
            if candidates:
                self.current_process_index = candidates[-1]
            else:
                self.current_process_index = len(self.game_process) - 1
        else:
            candidates = indices_by_type.get("initial", [])
            self.current_process_index = candidates[0] if candidates else 0

        self.current_child_index = int(
            stage in {GameStage.FREE_DISCUSSION.value, GameStage.VOTE.value}
        )
        return (self.current_process_index, self.current_child_index)

    async def start_game(self, db_session=None) -> dict[str, Any]:
        """
        开始游戏

        Returns:
            Dict: 游戏开始信息
        """
        # 更新游戏状态
        self.session.status = GameStatus.IN_PROGRESS.value
        self.session.current_stage = GameStage.INTRO.value
        self.session.started_at = datetime.now()

        # 构建发言队列（所有角色）
        character_ids = [c["character_id"] for c in self.characters]
        self.session.speech_queue = character_ids
        self.session.current_speaker = character_ids[0] if character_ids else None

        # 初始化玩家状态
        if db_session:
            await self._initialize_player_states(db_session)

        # 获取第一个阶段的系统通知
        first_stage = self.game_process[0] if self.game_process else {}
        system_notice = first_stage.get("system_notice", "游戏开始，请各位依次进行自我介绍。")
        audio_key = "stage_0" if system_notice else ""

        # 记录系统消息到游戏记录
        if db_session and system_notice:
            audio_url = ""
            if audio_key:
                audio_url = (
                    f"/audio/scripts/{self.session.script_id}/system_messages/{audio_key}.wav"
                )
            system_record = GameRecord(
                session_id=self.session.session_id,
                record_type=RecordType.SYSTEM.value,
                stage=GameStage.INTRO.value,
                round_num=0,
                raw_content=system_notice,
                audio_url=audio_url or None,
                timestamp=datetime.now(),
            )
            db_session.add(system_record)
            await db_session.commit()

        return {
            "status": "started",
            "session_id": self.session.session_id,
            "current_stage": self.session.current_stage,
            "speech_queue": self.session.speech_queue,
            "current_speaker": self.session.current_speaker,
            "system_notice": system_notice,
        }

    async def _clear_consumed_perspectives(self, character_id: str, db_session):
        """
        清除该角色已消费的 player_perspectives（发言后调用）

        agent 在 speak() 时通过 _build_knowledge_context 读取并注入了所有累积的 perspectives。
        注入后这些数据已存在于 agent 的 checkpointer 历史中，下次发言无需重复注入。
        清除后，下次 _build_knowledge_context 只会注入新累积的 perspectives（增量）。
        """
        if not db_session:
            return
        try:
            from sqlalchemy import select
            from sqlalchemy.orm.attributes import flag_modified

            result = await db_session.execute(
                select(PlayerState).where(
                    PlayerState.session_id == self.session.session_id,
                    PlayerState.character_id == character_id,
                )
            )
            player_state = result.scalar_one_or_none()
            if player_state and player_state.player_perspectives:
                player_state.player_perspectives = {}
                flag_modified(player_state, "player_perspectives")
                await db_session.commit()
        except Exception:
            pass

    async def _initialize_player_states(self, db_session):
        """初始化所有玩家的状态"""
        for char in self.characters:
            char_id = char["character_id"]

            player_state = PlayerState(
                session_id=self.session.session_id,
                character_id=char_id,
                suspicion={},
                suspected_intensity=0.0,
                wait_rounds=0,
                total_speeches=0,
                total_words=0,
                has_spoken_this_round=False,
                speeches_this_round=0,
            )
            db_session.add(player_state)

        await db_session.commit()

    async def process_speech(
        self,
        character_id: str,
        content: str,
        is_human: bool = False,
        db_session=None,
        skip_reactions: bool = False,
    ) -> dict[str, Any]:
        """
        处理玩家发言

        Args:
            character_id: 发言者角色ID
            content: 发言内容
            is_human: 是否是真人玩家
            db_session: 数据库会话
            skip_reactions: 跳过反应广播（用于错误兜底消息）

        Returns:
            Dict: 处理结果，包含下一位发言者等信息
        """
        # 清除该角色已消费的 perspectives（已通过 _build_knowledge_context 注入到 agent 历史中）
        await self._clear_consumed_perspectives(character_id, db_session)

        # 记录发言
        await self._record_speech(character_id, content, db_session)

        # 更新发言者状态
        await self._update_speaker_state(character_id, content, db_session)

        # 仅在自由发言阶段维护wait_rounds（发言机会成本）
        if self.session.current_stage == GameStage.FREE_DISCUSSION.value:
            await self._increment_wait_rounds_for_others(character_id, db_session)

        # ── 先更新队列和下一位发言者（持久化到DB），再做慢的reaction广播 ──
        # 这样即使reaction期间页面刷新，DB中已有正确的next_speaker，不会卡死

        # 记录发言者
        self.scheduler.record_speech(character_id)

        # 从发言队列中移除并持久化到数据库
        import json

        from sqlalchemy import text

        if character_id in (self.session.speech_queue or []):
            new_queue = list(self.session.speech_queue)
            new_queue.remove(character_id)
            self.session.speech_queue = new_queue

            # 持久化到数据库 - 使用直接SQL更新
            if db_session:
                await db_session.execute(
                    text(
                        "UPDATE game_sessions SET speech_queue = :queue "
                        "WHERE session_id = :session_id"
                    ),
                    {
                        "queue": json.dumps(new_queue),
                        "session_id": self.session.session_id,
                    },
                )

        # 根据当前阶段决定下一步（会将 current_speaker 持久化到 DB）
        next_result = await self._determine_next_speaker(db_session)

        # 广播给其他AI玩家（让他们做出反应）— 放在队列更新之后
        reactions = {}
        if not skip_reactions:
            try:
                reactions = await self.agent_manager.broadcast_speech(
                    speaker_id=character_id,
                    content=content,
                )
            except Exception:
                reactions = {}

        # 保存反应结果到数据库（更新PlayerState）
        if db_session and reactions:
            await self._save_reactions_to_db(reactions, character_id, db_session)

        return {
            "success": True,
            "speaker_id": character_id,
            "speaker_name": self.agent_manager.get_character_name(character_id),
            **next_result,
        }

    async def broadcast_reactions_stream(self, speaker_id: str, content: str) -> dict[str, Any]:
        """
        流式广播reaction（真人发言时使用，支持UI反馈）

        Args:
            speaker_id: 发言者ID
            content: 发言内容

        Returns:
            Dict[str, Any]: 各Agent的反应结果
        """
        return await self.agent_manager.broadcast_speech(
            speaker_id=speaker_id,
            content=content,
        )

    async def _record_speech(self, character_id: str, content: str, db_session):
        """记录发言到数据库"""
        if not db_session:
            return

        character_name = self.agent_manager.get_character_name(character_id)

        try:
            record = GameRecord(
                session_id=self.session.session_id,
                record_type=RecordType.SPEECH.value,
                stage=self.session.current_stage,
                round_num=self.session.current_round,
                speaker_character_id=character_id,
                speaker_name=character_name,
                raw_content=content,
                timestamp=datetime.now(),
            )
            db_session.add(record)
            await db_session.commit()
        except Exception:
            await db_session.rollback()

    async def _update_speaker_state(self, character_id: str, content: str, db_session):
        """更新发言者状态"""
        if not db_session:
            return

        from sqlalchemy import select

        result = await db_session.execute(
            select(PlayerState).where(
                PlayerState.session_id == self.session.session_id,
                PlayerState.character_id == character_id,
            )
        )
        player_state = result.scalar_one_or_none()

        if player_state:
            player_state.wait_rounds = 0
            player_state.has_spoken_this_round = True
            player_state.total_speeches += 1
            player_state.speeches_this_round += 1
            player_state.total_words += len(content)
            player_state.last_speech_at = datetime.now()

            # 在自由发言阶段，递减剩余发言次数
            if self.session.current_stage == GameStage.FREE_DISCUSSION.value:
                if player_state.remaining_speech_count > 0:
                    player_state.remaining_speech_count -= 1

            await db_session.commit()

    async def _increment_wait_rounds_for_others(self, speaker_id: str, db_session):
        """
        为其他玩家增加wait_rounds（发言机会成本）

        仅在自由发言阶段调用。每次发言后，更新除发言者外所有玩家的等待轮次。
        这用于计算发言机会成本，影响自由发言阶段的发言调度。

        Args:
            speaker_id: 当前发言者ID
            db_session: 数据库会话
        """
        if not db_session:
            return

        from sqlalchemy import update

        # 为除发言者外的所有玩家增加wait_rounds
        await db_session.execute(
            update(PlayerState)
            .where(
                PlayerState.session_id == self.session.session_id,
                PlayerState.character_id != speaker_id,
            )
            .values(wait_rounds=PlayerState.wait_rounds + 1)
        )
        await db_session.commit()

    async def _reset_wait_rounds_for_all(self, db_session):
        """
        重置所有玩家的wait_rounds为0

        在进入自由发言阶段时调用，确保所有玩家从相同的发言机会成本起点开始。
        """
        if not db_session:
            return

        from sqlalchemy import update

        await db_session.execute(
            update(PlayerState)
            .where(PlayerState.session_id == self.session.session_id)
            .values(wait_rounds=0)
        )
        await db_session.commit()

    async def _init_speech_count_for_all(self, db_session, speech_count: int):
        """
        初始化所有玩家的remaining_speech_count并重置has_spoken_this_round

        在进入自由讨论阶段时调用，根据剧本难度设置每位玩家的发言次数。

        Args:
            db_session: 数据库会话
            speech_count: 每位玩家的发言次数
        """
        if not db_session:
            return

        from sqlalchemy import update

        await db_session.execute(
            update(PlayerState)
            .where(PlayerState.session_id == self.session.session_id)
            .values(
                remaining_speech_count=speech_count,
                has_spoken_this_round=False,
                speeches_this_round=0,
            )
        )
        await db_session.commit()

    async def _reset_spoken_flags_for_all(self, db_session):
        """
        重置所有玩家的has_spoken_this_round和speeches_this_round

        在进入新的顺序发言阶段时调用（intro, clue_analysis, summary）。
        """
        if not db_session:
            return

        from sqlalchemy import update

        await db_session.execute(
            update(PlayerState)
            .where(PlayerState.session_id == self.session.session_id)
            .values(
                has_spoken_this_round=False,
                speeches_this_round=0,
            )
        )
        await db_session.commit()

    async def _save_reactions_to_db(self, reactions: dict[str, Any], speaker_id: str, db_session):
        """
        保存AI玩家的反应结果到数据库

        更新每个玩家的PlayerState中的suspicion_reasons、suspected_by和player_perspectives字段

        Args:
            reactions: 反应结果 {character_id: SpeechReaction | Dict}
            speaker_id: 发言者角色ID
            db_session: 数据库会话
        """
        from sqlalchemy import select

        for character_id, reaction in reactions.items():
            if isinstance(reaction, Exception) or "error" in reaction:
                continue

            # 获取该玩家的PlayerState
            result = await db_session.execute(
                select(PlayerState).where(
                    PlayerState.session_id == self.session.session_id,
                    PlayerState.character_id == character_id,
                )
            )
            player_state = result.scalar_one_or_none()
            if not player_state:
                continue

            # 获取反应数据
            my_suspicion_graph = (
                reaction.my_suspicion_graph
                if hasattr(reaction, "my_suspicion_graph")
                else reaction.get("my_suspicion_graph", {})
            )
            my_suspected_by = (
                reaction.my_suspected_by
                if hasattr(reaction, "my_suspected_by")
                else reaction.get("my_suspected_by", {})
            )
            main_perspective = (
                reaction.main_perspective
                if hasattr(reaction, "main_perspective")
                else reaction.get("main_perspective", "")
            )

            from sqlalchemy.orm.attributes import flag_modified

            # 更新怀疑图谱 (合并现有数据)
            current_suspicion = dict(player_state.suspicion_reasons or {})
            for target_name, data in my_suspicion_graph.items():
                current_suspicion[target_name] = data
            player_state.suspicion_reasons = current_suspicion
            flag_modified(player_state, "suspicion_reasons")

            # 更新被怀疑记录 (合并现有数据)
            current_suspected_by = dict(player_state.suspected_by or {})
            for source_name, data in my_suspected_by.items():
                current_suspected_by[source_name] = data
            player_state.suspected_by = current_suspected_by
            flag_modified(player_state, "suspected_by")

            # 计算被怀疑强度 (所有怀疑分数的平均值)
            if current_suspected_by:
                scores = [d.get("score", 0) for d in current_suspected_by.values()]
                player_state.suspected_intensity = sum(scores) / len(scores)

            # 更新对发言者的要点提炼 (累加存储为LIST)
            if main_perspective:
                current_perspectives = dict(player_state.player_perspectives or {})
                if speaker_id not in current_perspectives:
                    current_perspectives[speaker_id] = []
                elif not isinstance(current_perspectives[speaker_id], list):
                    # 兼容旧格式：单条字符串转为列表
                    current_perspectives[speaker_id] = [current_perspectives[speaker_id]]
                current_perspectives[speaker_id].append(main_perspective)
                player_state.player_perspectives = current_perspectives
                flag_modified(player_state, "player_perspectives")

        await db_session.commit()

    async def _determine_next_speaker(self, db_session) -> dict[str, Any]:
        """确定下一位发言者"""
        current_stage = self.session.current_stage

        # 顺序发言阶段
        if current_stage in [
            GameStage.INTRO.value,
            GameStage.SUMMARY.value,
            GameStage.VOTE.value,
        ]:
            result = await self._get_next_sequential_speaker(db_session)
            return result

        # 自由发言阶段
        elif current_stage == GameStage.FREE_DISCUSSION.value:
            return await self._get_next_free_speaker(db_session)

        # 线索分析阶段（顺序发言）
        elif current_stage == GameStage.CLUE_ANALYSIS.value:
            return await self._get_next_sequential_speaker(db_session)

        return {"next_speaker": None, "stage_complete": True}

    async def _get_next_sequential_speaker(self, db_session=None) -> dict[str, Any]:
        """获取顺序发言的下一位"""

        from sqlalchemy import text

        speech_queue = self.session.speech_queue or []

        if speech_queue:
            next_speaker = speech_queue[0]
            self.session.current_speaker = next_speaker

            # 持久化到数据库 - 使用直接SQL更新，因为self.session可能是detached对象
            if db_session:
                await db_session.execute(
                    text(
                        "UPDATE game_sessions SET current_speaker = :speaker "
                        "WHERE session_id = :session_id"
                    ),
                    {
                        "speaker": next_speaker,
                        "session_id": self.session.session_id,
                    },
                )
                await db_session.commit()

            return {
                "next_speaker": next_speaker,
                "next_speaker_name": self.agent_manager.get_character_name(next_speaker),
                "stage_complete": False,
            }
        else:
            # 阶段完成 — 清除 current_speaker，确保刷新后前端能正确判断状态
            self.session.current_speaker = None
            if db_session:
                await db_session.execute(
                    text(
                        "UPDATE game_sessions SET current_speaker = NULL "
                        "WHERE session_id = :session_id"
                    ),
                    {"session_id": self.session.session_id},
                )
                await db_session.commit()

            return {
                "next_speaker": None,
                "stage_complete": True,
                "message": "当前阶段已完成，可以推进到下一阶段",
            }

    async def _get_next_free_speaker(self, db_session) -> dict[str, Any]:
        """
        获取自由发言的下一位

        自由发言阶段规则：
        1. 每位玩家有remaining_speech_count次发言机会（由剧本难度决定）
        2. 当所有玩家的remaining_speech_count为0时，阶段结束
        3. has_spoken_this_round仅用于UI展示"结束阶段"按钮（所有玩家至少发言一次后可手动推进）
        """
        # 获取所有玩家状态
        player_states = await self._get_all_player_states(db_session)

        # 检查是否所有玩家都没有剩余发言次数
        all_exhausted = all(state.get("remaining_speech_count", 0) == 0 for state in player_states)
        if all_exhausted and player_states:
            return {
                "next_speaker": None,
                "stage_complete": True,
                "message": "所有玩家发言次数已用完，自由发言阶段结束",
            }

        # 过滤出仍有发言机会的玩家
        available_players = [
            state for state in player_states if state.get("remaining_speech_count", 0) > 0
        ]

        if not available_players:
            return {
                "next_speaker": None,
                "stage_complete": True,
                "message": "没有可发言的玩家，自由发言阶段结束",
            }

        # 选择下一位发言者（仅从有剩余发言次数的玩家中选择）
        result = await self.scheduler.select_next_speaker(
            player_states=available_players,
            human_character_id=self.session.human_character_id,
        )

        if result:
            from sqlalchemy import text

            next_speaker, tendency = result
            self.session.current_speaker = next_speaker
            # 持久化到数据库 - 使用直接SQL更新
            if db_session:
                await db_session.execute(
                    text(
                        "UPDATE game_sessions SET current_speaker = :speaker "
                        "WHERE session_id = :session_id"
                    ),
                    {
                        "speaker": next_speaker,
                        "session_id": self.session.session_id,
                    },
                )
                await db_session.commit()
            return {
                "next_speaker": next_speaker,
                "next_speaker_name": self.agent_manager.get_character_name(next_speaker),
                "tendency_score": tendency.score,
                "stage_complete": False,
            }
        else:
            return {
                "next_speaker": None,
                "stage_complete": True,
                "message": "自由发言阶段已完成",
            }

    async def _get_all_player_states(self, db_session) -> list[dict[str, Any]]:
        """获取所有玩家状态"""
        if not db_session:
            return []

        from sqlalchemy import select

        result = await db_session.execute(
            select(PlayerState).where(PlayerState.session_id == self.session.session_id)
        )
        states = result.scalars().all()

        return [
            {
                **state.to_dict(),
                "character_name": self.agent_manager.get_character_name(state.character_id),
            }
            for state in states
        ]

    async def advance_stage(self, db_session=None) -> StageTransition:
        """
        推进到下一阶段

        处理以下场景：
        1. 从 CLUE_ANALYSIS 到 FREE_DISCUSSION（同一 advancement 内的子阶段）
        2. 从一个主阶段到下一个主阶段

        Returns:
            StageTransition: 阶段转换信息
        """
        from_stage = self.session.current_stage
        current_config = self.game_process[self.current_process_index]
        current_type = current_config.get("type")

        # 检查是否在 advancement 类型中，且需要从 CLUE_ANALYSIS 过渡到 FREE_DISCUSSION
        if (
            current_type == "advancement"
            and self.session.current_stage == GameStage.CLUE_ANALYSIS.value
        ):
            children = current_config.get("children", [])
            # 如果还有下一个子阶段（自由讨论），则过渡到自由讨论
            if len(children) > 1 and self.current_child_index == 0:
                self.current_child_index = 1
                return await self.transition_to_free_discussion(db_session)

        # 检查是否在 vote 类型中，且需要从 SUMMARY 过渡到 VOTE
        if current_type == "vote" and self.session.current_stage == GameStage.SUMMARY.value:
            # SUMMARY 发言结束，进入实际投票阶段
            return await self.transition_to_vote(db_session)

        # 增加轮次计数
        self.session.current_round += 1

        # 重置子阶段索引
        self.current_child_index = 0

        # 检查是否还有下一阶段
        if self.current_process_index + 1 >= len(self.game_process):
            # 游戏结束
            return await self._end_game(db_session)

        # 移动到下一阶段
        self.current_process_index += 1
        next_stage_config = self.game_process[self.current_process_index]
        next_stage_type = next_stage_config.get("type")

        # 更新当前阶段
        stage_mapping = {
            "initial": GameStage.INTRO.value,
            "advancement": GameStage.CLUE_ANALYSIS.value,
            "vote": GameStage.SUMMARY.value,
            "review": GameStage.REVIEW.value,
        }
        self.session.current_stage = stage_mapping.get(next_stage_type, GameStage.INTRO.value)

        # 构建发言队列（保持剧本原始角色顺序）
        queue = [c["character_id"] for c in self.characters]

        if next_stage_type == "advancement":
            children = next_stage_config.get("children", [])
            if children:
                self.session.current_stage = GameStage.CLUE_ANALYSIS.value
                self.session.speech_queue = queue
                self.session.current_speaker = queue[0] if queue else None
                if db_session:
                    await self._reset_spoken_flags_for_all(db_session)
        elif next_stage_type == "vote":
            self.session.current_stage = GameStage.SUMMARY.value
            self.session.speech_queue = queue
            self.session.current_speaker = queue[0] if queue else None
            if db_session:
                await self._reset_spoken_flags_for_all(db_session)
        elif next_stage_type == "review":
            # 复盘阶段
            self.session.current_stage = GameStage.REVIEW.value
            self.session.status = GameStatus.REVIEW.value

        # 提交阶段变更
        if db_session:
            await db_session.commit()

        # 获取系统通知（对于advancement类型，从children中获取）
        system_notice = ""
        audio_key = ""
        if next_stage_type == "advancement":
            children = next_stage_config.get("children", [])
            if children:
                system_notice = children[0].get("system_notice", "")
                audio_key = f"stage_{self.current_process_index}_child_0"
        elif next_stage_type == "vote":
            # 投票阶段：system_notice 在 children[0]（总结发言引导）
            children = next_stage_config.get("children", [])
            if children:
                system_notice = children[0].get("system_notice", "")
                audio_key = f"stage_{self.current_process_index}_child_0"
            else:
                system_notice = next_stage_config.get("system_notice", "")
                if system_notice:
                    audio_key = f"stage_{self.current_process_index}"
            if not system_notice:
                system_notice = (
                    "总结发言阶段，请各位依次进行最终总结，阐述你的推理、指控理由、以及最终辩护。"
                )
        else:
            system_notice = next_stage_config.get("system_notice", "")
            # Fallback: if review stage has no system_notice, use full_truth
            if not system_notice and next_stage_type == "review":
                full_truth = self.script_data.get("full_truth", "")
                if full_truth:
                    system_notice = f"真相揭晓：\n\n{full_truth}"
            if system_notice:
                audio_key = f"stage_{self.current_process_index}"

        return StageTransition(
            from_stage=from_stage,
            to_stage=self.session.current_stage,
            round_num=self.session.current_round,
            message=f"阶段从 {from_stage} 推进到 {self.session.current_stage}",
            system_notice=system_notice,
            audio_key=audio_key,
        )

    async def _end_game(self, db_session) -> StageTransition:
        """结束游戏"""
        from_stage = self.session.current_stage
        self.session.status = GameStatus.FINISHED.value
        self.session.current_stage = GameStage.COMPLETED.value
        self.session.finished_at = datetime.now()

        if db_session:
            await db_session.commit()

        return StageTransition(
            from_stage=from_stage,
            to_stage=GameStage.COMPLETED.value,
            round_num=self.session.current_round,
            message="游戏结束",
            system_notice="游戏已结束，感谢参与！",
        )

    async def transition_to_free_discussion(self, db_session=None) -> StageTransition:
        """
        从线索分析阶段过渡到自由讨论阶段

        在进入自由讨论阶段时调用，会:
        1. 更新当前阶段为自由讨论
        2. 重置所有玩家的wait_rounds为0（确保公平的发言机会成本起点）
        3. 初始化所有玩家的remaining_speech_count（基于剧本难度）
        4. 重置has_spoken_this_round为False
        5. 清空发言队列（自由讨论阶段使用调度算法）

        Args:
            db_session: 数据库会话

        Returns:
            StageTransition: 阶段转换信息
        """
        from_stage = self.session.current_stage

        # 获取当前 advancement 配置中的自由讨论 system_notice
        current_config = self.game_process[self.current_process_index]
        children = current_config.get("children", [])
        system_notice = "线索分析结束，现在进入自由讨论阶段。请各位畅所欲言！"
        if len(children) > 1:
            system_notice = children[1].get("system_notice", system_notice)

        # 更新阶段
        self.session.current_stage = GameStage.FREE_DISCUSSION.value
        self.session.speech_queue = []  # 自由讨论不使用固定队列

        # 计算当前是第几个 advancement 阶段（用于索引 free_speech_limits）
        advancement_index = sum(
            1
            for i in range(self.current_process_index)
            if self.game_process[i].get("type") == "advancement"
        )

        # 优先从剧本 free_speech_limits 字段获取发言次数
        # 格式: [2, 2] — 第 i 个元素对应第 i 个 advancement 阶段的自由讨论发言次数
        speech_count = None
        free_speech_limits = self.script_data.get("free_speech_limits")
        if free_speech_limits:
            try:
                import json as _json

                limits = (
                    _json.loads(free_speech_limits)
                    if isinstance(free_speech_limits, str)
                    else free_speech_limits
                )
                if isinstance(limits, list) and 0 <= advancement_index < len(limits):
                    speech_count = limits[advancement_index]
            except (ValueError, TypeError):
                pass

        # 回退策略：根据剧本难度决定发言次数
        if speech_count is None:
            difficulty = self.script_data.get("difficulty", 1)
            speech_count = {1: 2, 2: 3, 3: 4}.get(difficulty, 2)

        # 重置所有玩家的状态
        if db_session:
            await self._reset_wait_rounds_for_all(db_session)
            await self._init_speech_count_for_all(db_session, speech_count)

            # 选择第一位AI发言者（自由讨论阶段AI应主动发言，不必等真人）
            first_speaker_result = await self._get_next_free_speaker(db_session)
            if first_speaker_result.get("next_speaker"):
                self.session.current_speaker = first_speaker_result["next_speaker"]

        return StageTransition(
            from_stage=from_stage,
            to_stage=GameStage.FREE_DISCUSSION.value,
            round_num=self.session.current_round,
            message=f"阶段从 {from_stage} 推进到自由讨论",
            system_notice=system_notice,
            audio_key=f"stage_{self.current_process_index}_child_1",
        )

    async def transition_to_vote(self, db_session=None) -> StageTransition:
        """
        从总结发言阶段过渡到投票阶段

        SUMMARY 发言结束后调用，会:
        1. 更新当前阶段为投票阶段
        2. 清空发言队列
        3. 清空当前发言者

        Args:
            db_session: 数据库会话

        Returns:
            StageTransition: 阶段转换信息
        """
        from_stage = self.session.current_stage

        # 获取当前 vote 配置中的 system_notice（从 children[1] 获取投票引导）
        current_config = self.game_process[self.current_process_index]
        children = current_config.get("children", [])
        default_notice = "总结发言结束，现在进入投票阶段。请各位投票指认凶手！"
        if len(children) > 1:
            system_notice = children[1].get("system_notice", default_notice)
        else:
            system_notice = current_config.get("system_notice", default_notice)

        # 更新阶段
        self.session.current_stage = GameStage.VOTE.value
        self.session.speech_queue = []  # 投票阶段不使用发言队列
        self.session.current_speaker = None  # 投票阶段没有当前发言者

        if db_session:
            await db_session.commit()

        return StageTransition(
            from_stage=from_stage,
            to_stage=GameStage.VOTE.value,
            round_num=self.session.current_round,
            message=f"阶段从 {from_stage} 推进到投票",
            system_notice=system_notice,
            audio_key=f"stage_{self.current_process_index}_child_1",
        )

    async def generate_ai_speech(
        self, character_id: str, db_session=None
    ) -> AsyncIterator[dict[str, Any]]:
        """
        生成AI玩家发言

        返回结构化的流式数据，支持多种UI效果:
        - token: LLM生成的文本片段
        - tool_call: 工具调用
        - tool_result: 工具执行结果
        - progress: Agent进度更新

        Args:
            character_id: 角色ID
            db_session: 数据库会话

        Yields:
            Dict[str, Any]: 结构化的流式数据，包含type和相应字段
        """
        from app.agents.agent_player import (
            StreamError,
            StreamProgress,
            StreamToken,
        )

        agent = self.agent_manager.get_agent(character_id)
        if not agent:
            return

        # 构建完整的游戏状态
        game_state = await self._build_game_state(character_id, db_session)
        stage = self.session.current_stage

        async for chunk in agent.speak(game_state, stage):
            # 将StreamChunk转换为dict以便JSON序列化
            if isinstance(chunk, StreamToken):
                yield {
                    "type": "token",
                    "text": chunk.text,
                    "node": chunk.node,
                }
            elif isinstance(chunk, StreamProgress):
                yield {
                    "type": "progress",
                    "step": chunk.step,
                    "status": chunk.status,
                }
            elif isinstance(chunk, StreamError):
                yield {
                    "type": "error",
                    "message": chunk.message,
                }

    async def _build_game_state(self, character_id: str, db_session) -> dict[str, Any]:
        """
        构建 Agent 所需的完整游戏状态

        Args:
            character_id: 角色ID
            db_session: 数据库会话

        Returns:
            Dict: 游戏状态，包含 GameAgentState 所需的所有字段
        """
        # 基础游戏上下文
        character_name_map = {c["character_id"]: c.get("name", "") for c in self.characters}
        character_names = list(character_name_map.values())

        game_state = {
            "session_id": self.session.session_id,
            "script_id": self.session.script_id,
            "character_id": character_id,
            "character_name": self.agent_manager.get_character_name(character_id),
            "current_stage": self.session.current_stage,
            "current_round": self.session.current_round,
            "db_session": db_session,
            "character_name_map": character_name_map,
            "character_names": character_names,  # 用于校验角色名称
        }

        # 构建发言上下文（动态系统推送内容）
        game_state["context"] = await self._build_speech_context(character_id)

        return game_state

    async def _build_speech_context(self, character_id: str) -> str:
        """
        构建发言上下文（仅包含动态的系统推送内容）

        注意: 阶段相关的静态提示词由 agent_player._get_stage_prompt 处理
              其他玩家的发言要点由 agent_player._build_knowledge_context 处理
              此方法仅负责获取当前阶段的 system_notice（动态系统消息）
        """
        context_parts = []

        # 自由讨论阶段在线索轮次中时，线索已在顺序发言阶段注入过，无需重复
        if self.session.current_stage == GameStage.FREE_DISCUSSION.value:
            return ""

        # 获取当前阶段的配置
        if self.current_process_index < len(self.game_process):
            current_config = self.game_process[self.current_process_index]
            stage_type = current_config.get("type")

            # 对于 advancement 类型（线索轮次），system_notice 在 children 中
            if stage_type == "advancement":
                children = current_config.get("children", [])
                if children:
                    # 获取线索分析阶段的 system_notice
                    system_notice = children[0].get("system_notice", "")
                    if system_notice:
                        context_parts.append(system_notice)
            else:
                # 其他阶段的 system_notice 直接在配置中
                system_notice = current_config.get("system_notice", "")
                if system_notice:
                    context_parts.append(system_notice)

        return "\n".join(context_parts)

    def get_game_state(self) -> dict[str, Any]:
        """获取当前游戏状态"""

        # 构建agent_llm_info
        agent_llm_info = {}
        for cid, info in self.agent_manager.agents.items():
            agent_llm_info[cid] = {
                "model": info.llm_model,
                "provider": info.llm_provider,
                "is_human": info.is_human,
            }

        return {
            "session_id": self.session.session_id,
            "status": self.session.status,
            "current_stage": self.session.current_stage,
            "current_round": self.session.current_round,
            "current_speaker_id": self.session.current_speaker,
            "current_speaker_name": (
                self.agent_manager.get_character_name(self.session.current_speaker)
                if self.session.current_speaker
                else None
            ),
            "speech_queue": self.session.speech_queue or [],
            "human_character_id": self.session.human_character_id,
            "has_all_spoken": len(self.session.speech_queue or []) == 0,
            "agent_llm_info": agent_llm_info,
        }
