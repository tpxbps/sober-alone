import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import GameRecord, GameSession, Script
from app.game.content_quality import content_fingerprint
from app.game.endings import OUTCOMES, ending_audio_tasks, normalize_endings, select_ending
from app.services.game_presenter import GameStatePresenter
from app.services.game_runtime import build_runtime_snapshot
from app.services.voting import VotingService


def script_data():
    return {
        "script_id": "ending-script",
        "title": "封存的信",
        "full_truth": "案件事实始终一致。",
        "characters": [{"character_id": "a", "name": "甲"}, {"character_id": "b", "name": "乙"}],
        "ending_config": {
            "mode": "multiple",
            "culprit_character_id": "a",
            "branches": [
                {"when": outcome, "title": outcome, "text": f"只属于 {outcome} 的后续。"}
                for outcome in OUTCOMES
            ],
        },
    }


@pytest.mark.parametrize(
    "counts,expected",
    [
        ({"a": 2, "b": 1}, "correct"),
        ({"b": 2, "a": 1}, "incorrect"),
        ({"a": 1, "b": 1}, "tie"),
        ({"b": 1, "a": 1}, "tie"),
        ({}, "no_votes"),
    ],
)
def test_outcome_uses_counts_not_first_tied_id(counts, expected):
    assert select_ending(script_data(), {"vote_count": counts})["when"] == expected


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c["branches"].pop(),
        lambda c: c["branches"][0].update(when="tie"),
        lambda c: c["branches"][0].update(text="  "),
        lambda c: c["branches"][0].update(when="extra_discussion"),
        lambda c: c.update(culprit_character_id="missing"),
        lambda c: c.update(mode="single"),
    ],
)
def test_incomplete_or_unexecutable_config_cannot_be_saved(mutate):
    script = script_data()
    mutate(script["ending_config"])
    with pytest.raises(ValueError):
        normalize_endings(script["ending_config"], script["characters"])


def test_snapshots_fingerprint_and_public_projection():
    script = script_data()
    snapshot = build_runtime_snapshot(script)
    fingerprint = content_fingerprint(script)
    script["ending_config"]["branches"][0]["text"] = "修改后的结局"
    assert content_fingerprint(script) != fingerprint
    assert snapshot["ending_config"]["branches"][0]["text"] != "修改后的结局"
    legacy = deepcopy(script)
    legacy.pop("ending_config")
    assert content_fingerprint(legacy) == content_fingerprint({**legacy, "ending_config": None})
    assert select_ending(legacy, {"vote_count": {"a": 1}}) is None
    assert "ending_config" not in GameStatePresenter.script(snapshot)
    private = GameStatePresenter.characters(
        [
            {"character_id": "a", "character_script_summary": "秘密甲"},
            {"character_id": "b", "character_script_summary": "秘密乙"},
        ],
        "a",
    )
    assert private[0]["character_script_summary"] == "秘密甲"
    assert private[1]["character_script_summary"] is None
    assert len(ending_audio_tasks(snapshot)) == 4
    assert all(
        sum(f"只属于 {other} 的后续。" in item["text"] for other in OUTCOMES) == 1
        for item in ending_audio_tasks(snapshot)
    )


@pytest.mark.asyncio
async def test_finalization_persists_one_selected_branch_and_retries_are_idempotent(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'endings.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    data = script_data()
    async with factory() as db:
        db.add(Script(script_id=data["script_id"], title=data["title"]))
        db.add(
            GameSession(
                session_id="session",
                script_id=data["script_id"],
                current_stage="vote",
                votes={"v1": {"suspect_id": "a", "suspect_name": "甲"}},
                runtime_snapshot=build_runtime_snapshot(data),
            )
        )
        await db.commit()
        session = SimpleNamespace(
            current_stage="vote",
            current_round=1,
            status="voting",
            speech_queue=[],
            current_speaker=None,
        )

        async def advance(_db):
            session.current_stage = "review"
            session.status = "review"
            return SimpleNamespace(
                from_stage="vote", to_stage="review", message="完成", system_notice="旧主持文案"
            )

        controller = SimpleNamespace(
            session=session,
            script_data=data,
            agent_manager=SimpleNamespace(agents={}),
            advance_stage=advance,
        )
        service = VotingService(db, lambda _: controller)
        results = await asyncio.gather(service.finalize("session"), service.finalize("session"))
        assert all(result["success"] for result in results)
        assert results[0]["vote_results"]["ending"]["when"] == "correct"
        records = list((await db.execute(select(GameRecord).order_by(GameRecord.id))).scalars())
        assert len(records) == 2
        assert data["full_truth"] in records[0].raw_content
        assert records[1].raw_content.endswith("只属于 correct 的后续。")
        assert "incorrect" not in records[1].raw_content
        assert records[1].audio_url is None  # Text remains usable when optional TTS was skipped.
    # A fresh service/controller after restore must use the already persisted result.
    async with factory() as db:
        controller.session.current_stage = "review"
        restored = await VotingService(db, lambda _: controller).finalize("session")
        assert restored["vote_results"]["ending"]["when"] == "correct"
    await engine.dispose()


def test_legacy_deepseek_ids_resolve_to_current_model(monkeypatch):
    from app.core import llm_factory
    from app.core.model_registry import get_model_spec

    monkeypatch.setattr(llm_factory, "_create_deepseek", lambda *args: args[0])
    for model in ("deepseek-flash", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"):
        assert get_model_spec(model).name == "deepSeek-v4.1-flash"
        assert llm_factory.create_llm(model=model, api_key="unit-test-only") == "deepseek-flash"
