"""
GameService - 游戏服务层
提供游戏相关的业务逻辑
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import get_agent_manager, remove_agent_manager
from app.db.models import GameRecord, GameSession, GameStage, GameStatus, PlayerState
from app.game import GameFlowController
from app.services.game_presenter import GameStatePresenter
from app.services.game_runtime import FlowControllerRegistry, GameRuntimeRepository
from app.services.game_speech import GameSpeechService
from app.services.voting import VotingService

logger = logging.getLogger(__name__)

# 全局流程控制器缓存 (解决跨请求状态持久化问题)
_flow_controllers = FlowControllerRegistry()


def get_flow_controller(session_id: str) -> GameFlowController | None:
    """获取流程控制器"""
    return _flow_controllers.get(session_id)


def remove_flow_controller(session_id: str):
    """移除流程控制器（游戏结束时调用）"""
    _flow_controllers.remove(session_id)


async def ensure_flow_controller(
    session_id: str, db_session: AsyncSession
) -> GameFlowController | None:
    """
    确保流程控制器存在，如果不存在则从数据库重建

    Args:
        session_id: 游戏会话ID
        db_session: 数据库会话

    Returns:
        Optional[GameFlowController]: 流程控制器实例
    """

    async def restore() -> GameFlowController | None:
        result = await db_session.execute(
            select(GameSession).where(GameSession.session_id == session_id)
        )
        game_session = result.scalar_one_or_none()
        if not game_session:
            return None

        script_data = await GameRuntimeRepository(db_session).load_script(game_session.script_id)
        if not script_data:
            return None

        agent_manager = get_agent_manager(session_id, game_session.script_id)
        if not agent_manager.agents:
            await agent_manager.initialize_agents(
                script_data.get("characters", []),
                game_session.human_character_id,
            )

        return GameFlowController(
            game_session=game_session,
            script_data=script_data,
            agent_manager=agent_manager,
        )

    return await _flow_controllers.get_or_restore(session_id, restore)


class GameService:
    """
    游戏服务

    提供游戏相关的核心业务逻辑：
    - 创建游戏
    - 获取游戏状态
    - 处理发言
    - 推进流程
    - 投票
    """

    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.runtime_repository = GameRuntimeRepository(db_session)
        self.speech_service = GameSpeechService(db_session, ensure_flow_controller)
        self.voting_service = VotingService(db_session, _flow_controllers.get)
        # 使用模块级别的缓存 _flow_controllers 而非实例变量
        # 以确保跨请求的状态持久化

    async def create_game(
        self,
        script_id: str,
        human_character_id: str,
        llm_configs: dict[str, dict[str, str | None]] | None = None,
    ) -> dict[str, Any]:
        """
        创建新游戏

        Args:
            script_id: 剧本ID
            human_character_id: 真人玩家选择的角色ID
            llm_configs: 可选的角色LLM配置，格式: {character_id: {"provider": str, "model": str}}

        Returns:
            Dict: 创建结果
        """
        # 获取剧本数据
        script_data = await self._get_script_data(script_id)
        if not script_data:
            return {"success": False, "error": "剧本不存在"}

        # 验证角色ID
        characters = script_data.get("characters", [])
        character_ids = [c["character_id"] for c in characters]
        if human_character_id not in character_ids:
            return {"success": False, "error": "角色ID无效"}

        # 创建游戏会话
        session_id = str(uuid.uuid4())
        game_session = GameSession(
            session_id=session_id,
            script_id=script_id,
            status=GameStatus.WAITING.value,
            current_stage=GameStage.INTRO.value,
            current_round=0,
            human_character_id=human_character_id,
            player_threads={},
            player_types={
                cid: ("human" if cid == human_character_id else "ai") for cid in character_ids
            },
            speech_queue=[],
            votes={},
        )
        self.db.add(game_session)
        await self.db.commit()

        # 初始化Agent管理器（传入LLM配置）
        agent_manager = get_agent_manager(session_id, script_id)
        await agent_manager.initialize_agents(characters, human_character_id, llm_configs)

        # 创建流程控制器
        flow_controller = GameFlowController(
            game_session=game_session,
            script_data=script_data,
            agent_manager=agent_manager,
        )
        _flow_controllers.put(session_id, flow_controller)

        # 开始游戏
        start_result = await flow_controller.start_game(self.db)

        # 获取LLM配置信息
        agent_llm_info = agent_manager.to_dict()["agents"]

        return {
            "success": True,
            "session_id": session_id,
            "status": start_result.get("status"),
            "current_stage": start_result.get("current_stage"),
            "current_speaker": start_result.get("current_speaker"),
            "characters": [
                {
                    "character_id": c["character_id"],
                    "name": c["name"],
                    "is_human": c["character_id"] == human_character_id,
                }
                for c in characters
            ],
            "llm_configs": {
                char_id: {
                    "provider": info.get("llm_provider"),
                    "model": info.get("llm_model"),
                }
                for char_id, info in agent_llm_info.items()
                if not info.get("is_human")
            },
        }

    async def _get_script_data(self, script_id: str) -> dict[str, Any] | None:
        """获取剧本数据"""
        return await self.runtime_repository.load_script(script_id)

    async def get_game_state(self, session_id: str) -> dict[str, Any]:
        """
        获取游戏状态

        Args:
            session_id: 游戏会话ID

        Returns:
            Dict: 游戏状态
        """
        result = await self.db.execute(
            select(GameSession).where(GameSession.session_id == session_id)
        )
        game_session = result.scalar_one_or_none()

        if not game_session:
            return {"success": False, "error": "游戏会话不存在"}

        # 获取玩家状态
        player_states = await self._get_player_states(session_id)

        # 获取剧本数据以获取角色信息
        script_data = await self._get_script_data(game_session.script_id)
        characters = script_data.get("characters", []) if script_data else []

        script_info = GameStatePresenter.script(script_data)
        presented_characters = GameStatePresenter.characters(
            characters, game_session.human_character_id
        )

        # 获取流程控制器
        flow_controller = _flow_controllers.get(session_id)

        if flow_controller:
            state = flow_controller.get_game_state()
            state["player_states"] = player_states
            state["script"] = script_info
            state["characters"] = presented_characters
            state["success"] = True
            # 确保字段名与前端一致
            if "current_speaker" in state:
                state["current_speaker_id"] = state.pop("current_speaker")
            # 返回投票状态（刷新恢复用）
            state["votes"] = dict(game_session.votes or {})
            state["vote_results"] = game_session.vote_result or None
            return state

        return {
            "success": True,
            "session_id": game_session.session_id,
            "status": game_session.status,
            "current_stage": game_session.current_stage,
            "current_round": game_session.current_round,
            "current_speaker_id": game_session.current_speaker,
            "human_character_id": game_session.human_character_id,
            "player_states": player_states,
            "script": script_info,
            "characters": presented_characters,
            "speech_queue": game_session.speech_queue or [],
            "votes": dict(game_session.votes or {}),
            "vote_results": game_session.vote_result or None,
        }

    async def _get_player_states(self, session_id: str) -> list[dict[str, Any]]:
        """获取所有玩家状态"""
        result = await self.db.execute(
            select(PlayerState).where(PlayerState.session_id == session_id)
        )
        states = result.scalars().all()
        return [s.to_dict() for s in states]

    async def process_human_speech(self, session_id: str, content: str) -> dict[str, Any]:
        """
        处理真人玩家发言

        Args:
            session_id: 游戏会话ID
            content: 发言内容

        Returns:
            Dict: 处理结果
        """
        flow_controller = await ensure_flow_controller(session_id, self.db)
        if not flow_controller:
            return {"success": False, "error": "游戏会话不存在或已结束"}

        human_character_id = flow_controller.session.human_character_id

        # 检查是否轮到真人玩家发言（自由发言阶段允许随时发言）
        current_speaker = flow_controller.session.current_speaker
        current_stage = flow_controller.session.current_stage
        if (
            current_stage != GameStage.FREE_DISCUSSION.value
            and current_speaker != human_character_id
        ):
            return {
                "success": False,
                "error": "当前不是你的发言回合",
                "current_speaker": current_speaker,
                "current_speaker_name": flow_controller.agent_manager.get_character_name(
                    current_speaker
                ),
            }

        # 处理发言
        result = await flow_controller.process_speech(
            character_id=human_character_id,
            content=content,
            is_human=True,
            db_session=self.db,
        )

        return result

    async def process_human_speech_stream(self, session_id: str, content: str):
        """Preserve the historical human-speech streaming facade."""
        async for event in self.speech_service.stream_human(session_id, content):
            yield event

    async def process_ai_speech_stream(self, session_id: str, character_id: str):
        """Preserve the historical AI-speech streaming facade."""
        async for event in self.speech_service.stream_ai(session_id, character_id):
            yield event

    async def advance_stage(self, session_id: str) -> dict[str, Any]:
        """
        推进游戏流程

        Args:
            session_id: 游戏会话ID

        Returns:
            Dict: 推进结果
        """
        flow_controller = _flow_controllers.get(session_id)
        if not flow_controller:
            return {"success": False, "error": "游戏会话不存在"}

        try:
            transition = await flow_controller.advance_stage(self.db)

            # 持久化游戏会话状态变更到数据库
            import json

            from sqlalchemy import text

            await self.db.execute(
                text(
                    "UPDATE game_sessions SET current_stage = :stage, "
                    "current_round = :round, status = :status, "
                    "speech_queue = :queue, current_speaker = :speaker "
                    "WHERE session_id = :session_id"
                ),
                {
                    "stage": flow_controller.session.current_stage,
                    "round": flow_controller.session.current_round,
                    "status": flow_controller.session.status,
                    "queue": json.dumps(flow_controller.session.speech_queue or []),
                    "speaker": (
                        flow_controller.session.speech_queue[0]
                        if flow_controller.session.speech_queue
                        else flow_controller.session.current_speaker
                    ),
                    "session_id": session_id,
                },
            )
            await self.db.commit()

            # 如果有系统通知，记录到游戏记录
            if transition.system_notice:
                audio_url = None
                if transition.audio_key:
                    audio_url = f"/audio/scripts/{flow_controller.session.script_id}/system_messages/{transition.audio_key}.wav"
                record = GameRecord(
                    session_id=session_id,
                    record_type="system",
                    stage=transition.to_stage,
                    round_num=transition.round_num,
                    raw_content=transition.system_notice,
                    audio_url=audio_url,
                    timestamp=datetime.now(),
                )
                self.db.add(record)
                await self.db.commit()

            return {
                "success": True,
                "transition": {
                    "from_stage": transition.from_stage,
                    "to_stage": transition.to_stage,
                    "round_num": transition.round_num,
                    "message": transition.message,
                    "system_notice": transition.system_notice,
                },
                # 额外返回更新后的游戏状态
                "current_speaker_id": flow_controller.session.current_speaker,
                "speech_queue": flow_controller.session.speech_queue or [],
            }
        except Exception as e:
            await self.db.rollback()
            return {"success": False, "error": str(e)}

    async def submit_vote(
        self, session_id: str, suspect_id: str, suspect_name: str, reasoning: str = ""
    ) -> dict[str, Any]:
        return await self.voting_service.submit_vote(
            session_id, suspect_id, suspect_name, reasoning
        )

    async def _collect_single_ai_vote(
        self, flow_controller, character_id: str, agent, db_session=None
    ) -> dict[str, Any]:
        return await self.voting_service.collect_single_ai_vote(
            flow_controller, character_id, agent, db_session
        )

    async def get_vote_results(self, session_id: str) -> dict[str, Any]:
        return await self.voting_service.get_results(session_id)

    async def finalize_voting(self, session_id: str) -> dict[str, Any]:
        return await self.voting_service.finalize(session_id)

    async def get_game_records(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """
        获取游戏记录

        Args:
            session_id: 游戏会话ID
            limit: 返回记录数量

        Returns:
            List[Dict]: 游戏记录列表
        """
        result = await self.db.execute(
            select(GameRecord)
            .where(GameRecord.session_id == session_id)
            .order_by(GameRecord.timestamp.asc())
            .limit(limit)
        )
        records = result.scalars().all()

        return [d for r in records if (d := r.to_display_dict()) is not None]

    async def abandon_session(self, session_id: str) -> dict[str, Any]:
        """放弃游戏会话（用户中途退出时调用，清理资源）"""
        remove_agent_manager(session_id)
        remove_flow_controller(session_id)
        return {"success": True, "message": "游戏会话已放弃"}

    async def end_game(self, session_id: str) -> dict[str, Any]:
        """
        结束游戏

        在复盘阶段后调用，清理游戏资源并标记游戏结束。
        注意：真相（full_truth）已在 finalize_voting 的 review_message 中返回。

        Args:
            session_id: 游戏会话ID

        Returns:
            Dict: 结束结果
        """
        result = await self.db.execute(
            select(GameSession).where(GameSession.session_id == session_id)
        )
        game_session = result.scalar_one_or_none()

        if not game_session:
            return {"success": False, "error": "游戏会话不存在"}

        game_session.status = GameStatus.FINISHED.value
        game_session.finished_at = datetime.now()

        await self.db.commit()

        # 清理资源
        remove_agent_manager(session_id)
        remove_flow_controller(session_id)

        return {"success": True, "message": "游戏已结束"}
