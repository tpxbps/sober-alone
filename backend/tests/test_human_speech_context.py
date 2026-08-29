from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Character, GameRecord, GameSession, PlayerState, Script
from app.game.flow_controller import GameFlowController


@pytest.mark.asyncio
async def test_each_ai_consumes_complete_human_speech_independently():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        session.add(
            Script(
                script_id="script",
                title="test",
                game_full_process=[],
                free_speech_limits=[],
            )
        )
        session.add_all(
            [
                Character(character_id="human", script_id="script", name="真人"),
                Character(character_id="ai-1", script_id="script", name="林岚"),
                Character(character_id="ai-2", script_id="script", name="周沉"),
            ]
        )
        session.add(
            GameSession(
                session_id="game",
                script_id="script",
                human_character_id="human",
                current_stage="free_discussion",
            )
        )
        await session.flush()
        session.add_all(
            [
                PlayerState(session_id="game", character_id="ai-1"),
                PlayerState(session_id="game", character_id="ai-2"),
                GameRecord(
                    session_id="game",
                    record_type="speech",
                    stage="free_discussion",
                    round_num=1,
                    speaker_character_id="human",
                    speaker_name="真人",
                    raw_content="@林岚 你如何解释门口的脚印？原话必须完整保留。",
                ),
            ]
        )
        await session.commit()

        controller = GameFlowController.__new__(GameFlowController)
        controller.session = SimpleNamespace(session_id="game", human_character_id="human")
        controller.agent_manager = SimpleNamespace(
            get_character_name=lambda character_id: {
                "ai-1": "林岚",
                "ai-2": "周沉",
            }[character_id]
        )
        controller._pending_human_record_ids = {}

        first_context, record_id = await controller._build_unseen_human_context("ai-1", session)
        other_context, other_record_id = await controller._build_unseen_human_context(
            "ai-2", session
        )

        assert "原话必须完整保留" in first_context
        assert "你被真人玩家直接点名" in first_context
        assert "真人发言｜自由讨论｜第1轮｜真人" in first_context
        assert "free_discussion" not in first_context
        assert "[记录" not in first_context
        assert f"记录 {record_id}" not in first_context
        assert "直接点名" not in other_context
        assert record_id == other_record_id > 0

        controller._pending_human_record_ids["ai-1"] = record_id
        await controller._consume_injected_human_context("ai-1", session)
        consumed, _ = await controller._build_unseen_human_context("ai-1", session)
        still_unseen, _ = await controller._build_unseen_human_context("ai-2", session)
        assert consumed == ""
        assert "原话必须完整保留" in still_unseen

    await engine.dispose()
