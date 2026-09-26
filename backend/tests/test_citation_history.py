from types import SimpleNamespace

import pytest
from test_state_reliability import game as base_game

from app.db.models import GameRecord
from app.game.citation_history import display_records
from app.game.citation_syntax import speech_text

game = base_game


@pytest.mark.asyncio
async def test_history_service_repairs_without_updating_database(game):
    from app.services.game_service import GameService

    db, controller = game
    controller.session.revealed_clues = [
        {"id": "c01", "summary": "门锁", "stage": 1},
        {"id": "c02", "summary": "窗台", "stage": 2},
    ]
    announcement = GameRecord(
        session_id="g", record_type="system", stage="clue_analysis", clue_refs=["c01"]
    )
    old = GameRecord(
        session_id="g",
        record_type="speech",
        stage="free_discussion",
        speaker_character_id="a",
        raw_content="[未闭合，后面c01记录。[c01]和[c02]",
        clue_refs=[],
    )
    future = GameRecord(
        session_id="g", record_type="system", stage="clue_analysis", clue_refs=["c02"]
    )
    db.add_all([announcement, old, future])
    await db.commit()
    result = await GameService(db).get_game_records("g")
    assert result[1]["clue_refs"] == ["c01"]
    assert result[1]["content"] == "[未闭合，后面[c01]记录。[c01]和"
    await db.refresh(old)
    assert old.clue_refs == []
    assert old.raw_content.endswith("[c01]和[c02]")


def test_historical_repair_uses_preceding_announcements_not_future_clues():
    clues = [
        {"id": "c01", "summary": "门锁", "stage": 1},
        {"id": "c02", "summary": "窗台", "stage": 2},
        {"id": "c03", "summary": "新材料", "stage": 3},
    ]
    session = SimpleNamespace(revealed_clues=clues, human_character_id="human")

    def record(id, kind, text="", refs=(), speaker="ai", stage="clue_analysis"):
        return GameRecord(
            id=id,
            session_id="test",
            record_type=kind,
            raw_content=text,
            clue_refs=list(refs),
            speaker_character_id=speaker,
            stage=stage,
        )

    records = [
        record(1, "speech", "我知道[c01]", stage="introduction"),
        record(2, "system", refs=["c01"]),
        record(3, "speech", "c01记录与[c02]"),
        record(4, "system", refs=["c02"]),
        record(5, "speech", "[对照c01材料与[c02]][c01][c02]。再看[c02]和[c03]", refs=["c01"]),
        record(6, "speech", "[我的判断][c01,c03]", speaker="human"),
        record(7, "system", refs=["c03"]),
    ]
    result = display_records(records, session)
    assert result[0]["clue_refs"] == []
    assert result[2]["content"] == "[c01]记录与"
    assert result[2]["clue_refs"] == ["c01"]
    assert result[4]["content"] == "[对照材料与窗台][c01,c02]。再看[c02]和"
    assert result[4]["clue_refs"] == ["c01", "c02"]
    assert result[5]["content"] == "[我的判断][c01,c03]"
    assert result[5]["clue_refs"] == []
    assert records[4].clue_refs == ["c01"]  # Read repair never mutates storage.
    assert (
        speech_text(result[4]["content"], clues, result[4]["clue_refs"])
        == "对照材料与窗台。再看窗台和"
    )


def test_legacy_game_without_announcements_retains_only_saved_permission():
    session = SimpleNamespace(
        human_character_id="human",
        revealed_clues=[
            {"id": "c01", "summary": "材料一"},
            {"id": "c02", "summary": "材料二"},
        ],
    )
    record = GameRecord(
        id=1,
        record_type="speech",
        speaker_character_id="ai",
        stage="free_discussion",
        raw_content="[c01]与[c02]",
        clue_refs=["c01"],
    )
    assert display_records([record], session)[0]["clue_refs"] == ["c01"]


def test_vote_and_summary_repair_preserve_vote_time_scope():
    session = SimpleNamespace(
        human_character_id="human",
        revealed_clues=[
            {"id": "c01", "summary": "门锁"},
            {"id": "c02", "summary": "后来的线索"},
        ],
    )
    records = [
        GameRecord(record_type="system", stage="clue_analysis", clue_refs=["c01"]),
        GameRecord(
            record_type="vote",
            stage="vote",
            speaker_character_id="a",
            raw_content="[门锁未撬][c01]，但[c02]未知",
            clue_refs=[],
        ),
        GameRecord(record_type="system", stage="clue_analysis", clue_refs=["c02"]),
        GameRecord(
            record_type="system",
            stage="review",
            extra_data="vote_summary",
            raw_content="投票：[c01]，不得补入[c02]",
            clue_refs=[],
        ),
    ]
    result = display_records(records, session)
    assert result[1]["clue_refs"] == ["c01"]
    assert result[3]["clue_refs"] == ["c01"]
    assert "c02" not in result[3]["content"]
    assert records[1].clue_refs == []
