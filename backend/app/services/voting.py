"""Voting orchestration independent from the GameService transport facade."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GameRecord, GameSession, PlayerState

ControllerGetter = Callable[[str], Any | None]


class VotingService:
    def __init__(
        self,
        db_session: AsyncSession | None = None,
        get_controller: ControllerGetter | None = None,
    ) -> None:
        self.db = db_session
        self._get_controller = get_controller or (lambda _session_id: None)

    @staticmethod
    def summarize(votes: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
        if not votes:
            return {}

        vote_count: dict[str, int] = {}
        for vote_info in votes.values():
            suspect_id = vote_info.get("suspect_id")
            if suspect_id:
                vote_count[suspect_id] = vote_count.get(suspect_id, 0) + 1

        max_votes = max(vote_count.values(), default=0)
        tied_suspects = [
            suspect_id
            for suspect_id, count in vote_count.items()
            if max_votes > 0 and count == max_votes
        ]

        return {
            "vote_count": vote_count,
            "total_votes": len(votes),
            "final_suspect": tied_suspects[0] if tied_suspects else None,
            "final_suspect_votes": max_votes,
            "tied_suspects": tied_suspects,
            "details": votes,
        }

    async def submit_vote(
        self, session_id: str, suspect_id: str, suspect_name: str, reasoning: str = ""
    ) -> dict[str, Any]:
        """
        提交真人玩家投票

        真人玩家投票可以选择填写理由，前端直接提供选项。
        接口接收真人玩家认为的最终结果id+名称+可选理由。

        Args:
            session_id: 游戏会话ID
            suspect_id: 嫌疑人角色ID
            suspect_name: 嫌疑人名称
            reasoning: 投票理由（可选）

        Returns:
            Dict: 投票结果
        """
        flow_controller = self._get_controller(session_id)
        if not flow_controller:
            return {"success": False, "error": "游戏会话不存在"}

        human_character_id = flow_controller.session.human_character_id
        if not human_character_id:
            return {"success": False, "error": "本局没有真人玩家"}

        # 检查当前阶段是否为投票阶段
        from app.db.models import GameStage

        if flow_controller.session.current_stage != GameStage.VOTE.value:
            return {"success": False, "error": "当前不是投票阶段"}

        try:
            from datetime import datetime

            from sqlalchemy import select

            from app.db.models import GameRecord, GameSession, PlayerState, RecordType

            # 检查是否已投票
            result = await self.db.execute(
                select(PlayerState).where(
                    PlayerState.session_id == session_id,
                    PlayerState.character_id == human_character_id,
                )
            )
            player_state = result.scalar_one_or_none()

            if not player_state:
                return {"success": False, "error": "玩家状态不存在"}

            if player_state.has_voted:
                return {"success": False, "error": "你已经投过票了"}

            # 更新玩家投票状态
            player_state.has_voted = True
            player_state.voted_for = suspect_id
            player_state.vote_reasoning = reasoning  # 可选理由

            # 更新游戏会话的投票记录
            session_result = await self.db.execute(
                select(GameSession).where(GameSession.session_id == session_id)
            )
            game_session = session_result.scalar_one_or_none()

            if game_session:
                votes = dict(game_session.votes or {})
                votes[human_character_id] = {
                    "suspect_id": suspect_id,
                    "suspect_name": suspect_name,
                    "reasoning": reasoning,  # 可选理由
                }
                game_session.votes = votes

            # 记录投票行为
            vote_content = f"投票给「{suspect_name}」"
            if reasoning:
                vote_content += f"，理由：{reasoning}"
            # 获取真人角色名称
            voter_name = ""
            fc = self._get_controller(session_id)
            if fc:
                voter_name = fc.agent_manager.get_character_name(human_character_id) or ""
            record = GameRecord(
                session_id=session_id,
                record_type=RecordType.VOTE.value,
                stage="vote",
                speaker_character_id=human_character_id,
                speaker_name=voter_name,
                raw_content=vote_content,
                timestamp=datetime.now(),
            )
            self.db.add(record)

            await self.db.commit()

            return {
                "success": True,
                "message": f"投票成功！你已投票给「{suspect_name}」",
            }

        except Exception as e:
            await self.db.rollback()
            return {"success": False, "error": f"投票失败：{str(e)}"}

    async def collect_single_ai_vote(
        self, flow_controller, character_id: str, agent, db_session=None
    ) -> dict[str, Any]:
        """
        收集单个AI玩家的投票

        Args:
            flow_controller: 流程控制器
            character_id: 角色ID
            agent: AgentPlayer实例
            db_session: 可选的数据库会话（并发投票时使用独立会话）

        Returns:
            Dict: 投票结果
        """
        session = db_session or self.db
        try:
            import asyncio

            # 带 per-agent 超时（90s），防止单个 agent 无限挂起
            async def _run_vote():
                async for _ in agent.speak(
                    {
                        "session_id": flow_controller.session.session_id,
                        "script_id": flow_controller.session.script_id,
                        "character_id": character_id,
                        "character_name": flow_controller.agent_manager.get_character_name(
                            character_id
                        ),
                        "current_stage": "vote",
                        "current_round": flow_controller.session.current_round,
                        "db_session": session,
                        "character_name_map": {
                            c["character_id"]: c.get("name", "") for c in flow_controller.characters
                        },
                        "character_names": [c.get("name", "") for c in flow_controller.characters],
                    },
                    "vote",
                ):
                    pass

            await asyncio.wait_for(_run_vote(), timeout=90)

            # 查询数据库获取投票结果
            from sqlalchemy import select

            from app.db.models import PlayerState

            result = await session.execute(
                select(PlayerState).where(
                    PlayerState.session_id == flow_controller.session.session_id,
                    PlayerState.character_id == character_id,
                )
            )
            player_state = result.scalar_one_or_none()

            if player_state and player_state.has_voted:
                return {
                    "suspect_id": player_state.voted_for,
                    "suspect_name": player_state.vote_reasoning or "",
                    "success": True,
                }
            else:
                return {"success": False, "message": "AI未能完成投票"}

        except Exception as e:
            return {"success": False, "message": str(e)}

    async def get_results(self, session_id: str) -> dict[str, Any]:
        """
        获取投票结果统计

        Args:
            session_id: 游戏会话ID

        Returns:
            dict: 投票结果统计，包含每位玩家的投票详情
        """
        from sqlalchemy import select

        from app.db.models import GameSession

        try:
            result = await self.db.execute(
                select(GameSession).where(GameSession.session_id == session_id)
            )
            game_session = result.scalar_one_or_none()

            if not game_session or not game_session.votes:
                return {}

            return VotingService.summarize(game_session.votes)

        except Exception:
            return {}

    async def record_abstain(self, flow_controller, character_id: str, db_session):
        """将AI玩家记录为弃票"""
        from sqlalchemy.orm.attributes import flag_modified

        from app.db.models import GameRecord, GameSession, RecordType

        char_name = flow_controller.agent_manager.get_character_name(character_id)
        try:
            ps_result = await db_session.execute(
                select(PlayerState).where(
                    PlayerState.session_id == flow_controller.session.session_id,
                    PlayerState.character_id == character_id,
                )
            )
            player_state = ps_result.scalar_one_or_none()
            if player_state:
                player_state.has_voted = True
                player_state.voted_for = None
                player_state.vote_reasoning = "弃票"

            gs_result = await db_session.execute(
                select(GameSession).where(
                    GameSession.session_id == flow_controller.session.session_id
                )
            )
            game_session = gs_result.scalar_one_or_none()
            if game_session:
                votes = dict(game_session.votes or {})
                votes[character_id] = {
                    "suspect_id": None,
                    "suspect_name": "弃票",
                    "reasoning": "AI未能完成投票",
                }
                game_session.votes = votes
                flag_modified(game_session, "votes")

            record = GameRecord(
                session_id=flow_controller.session.session_id,
                record_type=RecordType.VOTE.value,
                stage="vote",
                speaker_character_id=character_id,
                speaker_name=char_name,
                raw_content=f"「{char_name}」弃票",
                timestamp=datetime.now(),
            )
            db_session.add(record)
            await db_session.commit()
        except Exception:
            await db_session.rollback()

    async def finalize(self, session_id: str) -> dict[str, Any]:
        """
        完成投票并推进到复盘阶段

        1. 收集所有AI玩家投票
        2. 获取投票结果
        3. 构建复盘消息
        4. 推进到复盘阶段
        """
        flow_controller = self._get_controller(session_id)
        if not flow_controller:
            return {"success": False, "error": "游戏会话不存在"}

        # 幂等：如果已经推进到 review 阶段，直接返回已有结果
        if flow_controller.session.current_stage == "review":
            gs_result = await self.db.execute(
                select(GameSession).where(GameSession.session_id == session_id)
            )
            game_session = gs_result.scalar_one_or_none()
            return {
                "success": True,
                "vote_results": game_session.vote_result if game_session else None,
                "transition": {
                    "from_stage": "vote",
                    "to_stage": "review",
                    "message": "投票已统计完毕",
                },
            }

        # 1. 收集所有AI玩家的投票
        ai_agents = []
        for char_id, info in flow_controller.agent_manager.agents.items():
            if info.agent and char_id != flow_controller.session.human_character_id:
                ai_agents.append((char_id, info))

        if ai_agents:
            import asyncio

            from app.db.session import AsyncSessionLocal

            async def _collect_vote_task(char_id: str, info):
                """并发收集单个AI投票（使用独立数据库会话）"""
                async with AsyncSessionLocal() as vote_session:
                    # 检查该AI是否已经投票
                    ps_result = await vote_session.execute(
                        select(PlayerState).where(
                            PlayerState.session_id == flow_controller.session.session_id,
                            PlayerState.character_id == char_id,
                        )
                    )
                    player_state = ps_result.scalar_one_or_none()
                    if player_state and player_state.has_voted:
                        return {"success": True}

                    try:
                        result = await self.collect_single_ai_vote(
                            flow_controller, char_id, info.agent, vote_session
                        )
                        await vote_session.commit()
                        return result
                    except Exception as e:
                        await vote_session.rollback()
                        return {"success": False, "message": str(e)}

            # 并发执行所有AI投票，整体超时120秒
            tasks = [_collect_vote_task(cid, info) for cid, info in ai_agents]
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=120,
                )
            except TimeoutError:
                results = [TimeoutError("voting timeout")] * len(ai_agents)

            # 顺序处理失败（弃票）
            for (char_id, info), result in zip(ai_agents, results):
                if isinstance(result, Exception):
                    await self.record_abstain(flow_controller, char_id, self.db)
                elif isinstance(result, dict) and not result.get("success"):
                    await self.record_abstain(flow_controller, char_id, self.db)

        # 2. 获取投票结果（先清除主会话缓存以读取并发提交的数据）
        self.db.expire_all()
        vote_results = await self.get_results(session_id)

        if not vote_results:
            return {"success": False, "error": "没有投票记录"}

        # 3. 更新最终投票结果到游戏会话
        result = await self.db.execute(
            select(GameSession).where(GameSession.session_id == session_id)
        )
        game_session = result.scalar_one_or_none()

        if game_session:
            game_session.vote_result = vote_results
            final_id = vote_results.get("final_suspect")
            game_session.final_suspect_id = final_id
            for _, vinfo in (game_session.votes or {}).items():
                if vinfo.get("suspect_id") == final_id:
                    game_session.final_suspect_name = vinfo.get("suspect_name", "")
                    break

        await self.db.commit()

        # 4. 构建复盘消息
        review_message = self.build_review_message(vote_results, flow_controller.script_data)

        # 将复盘消息持久化到数据库，确保刷新后仍可显示
        review_record = GameRecord(
            session_id=session_id,
            record_type="system",
            stage="review",
            raw_content=review_message,
            timestamp=datetime.now(),
        )
        self.db.add(review_record)

        # 推进到复盘阶段
        transition = await flow_controller.advance_stage(self.db)

        # 持久化阶段变更到数据库（flow_controller.session 是 detached ORM 对象，
        # 需要通过 raw SQL 确保写入）
        import json as json_mod

        from sqlalchemy import text as sql_text

        await self.db.execute(
            sql_text(
                "UPDATE game_sessions SET current_stage = :stage, "
                "current_round = :round, status = :status, "
                "speech_queue = :queue, current_speaker = :speaker "
                "WHERE session_id = :session_id"
            ),
            {
                "stage": flow_controller.session.current_stage,
                "round": flow_controller.session.current_round,
                "status": flow_controller.session.status,
                "queue": json_mod.dumps(flow_controller.session.speech_queue or []),
                "speaker": (
                    flow_controller.session.speech_queue[0]
                    if flow_controller.session.speech_queue
                    else flow_controller.session.current_speaker
                ),
                "session_id": session_id,
            },
        )

        # 确保复盘记录和阶段变更都被保存
        await self.db.commit()

        return {
            "success": True,
            "vote_results": vote_results,
            "review_message": review_message,
            "transition": {
                "from_stage": transition.from_stage,
                "to_stage": transition.to_stage,
                "message": transition.message,
                "system_notice": transition.system_notice,
            },
        }

    def build_review_message(
        self, vote_results: dict[str, Any], script_data: dict[str, Any]
    ) -> str:
        """
        构建复盘阶段的消息

        包含：
        1. 所有玩家的投票结果和理由
        2. 投票统计（得票数）
        3. 剧本的完整真相（full_truth）

        Args:
            vote_results: 投票结果
            script_data: 剧本数据

        Returns:
            str: 复盘消息
        """
        lines = []

        details = vote_results.get("details", {})

        # Build id->name map from vote details
        id_to_name = {}
        for _, vote_info in details.items():
            sid = vote_info.get("suspect_id")
            sname = vote_info.get("suspect_name")
            if sid and sname:
                id_to_name[sid] = sname

        # 1. 投票结果汇总
        lines.append("## 投票结果收集如下\n")
        for _, vote_info in details.items():
            suspect_name = vote_info.get("suspect_name", "未知")
            reasoning = vote_info.get("reasoning", "")
            if reasoning:
                lines.append(f"- 投票给「{suspect_name}」，理由：{reasoning}")
            else:
                lines.append(f"- 投票给「{suspect_name}」")

        # 2. 投票统计
        lines.append("\n## 投票统计\n")
        vote_count = vote_results.get("vote_count", {})
        total_votes = vote_results.get("total_votes", 0)
        for sid, count in sorted(vote_count.items(), key=lambda x: -x[1]):
            display_name = id_to_name.get(sid, sid)
            lines.append(f"- 「{display_name}」：{count} 票")

        final_suspect = vote_results.get("final_suspect")
        final_suspect_name = id_to_name.get(final_suspect, final_suspect)
        final_suspect_votes = vote_results.get("final_suspect_votes", 0)
        tied_suspects = vote_results.get("tied_suspects", [])
        if final_suspect:
            if final_suspect_votes == total_votes:
                lines.append(f"\n最终，大家一致指认「{final_suspect_name}」为凶手。")
            elif len(tied_suspects) > 1:
                tied_names = "」和「".join(id_to_name.get(sid, sid) for sid in tied_suspects)
                lines.append(
                    f"\n最终，「{tied_names}」以 {final_suspect_votes} 票平票，共同成为最大嫌疑人。"
                )
            else:
                lines.append(
                    f"\n最终，「{final_suspect_name}」以 {final_suspect_votes} 票成为最大嫌疑人。"
                )

        # 3. 真相揭晓
        full_truth = script_data.get("full_truth", "")
        if full_truth:
            lines.append(f"\n## 真相揭晓\n\n{full_truth}")

        return "\n\n".join(lines)
