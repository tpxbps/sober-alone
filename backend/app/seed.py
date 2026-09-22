"""Deterministic, text-only sample data for a fresh local installation."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Character, Script
from app.game.clues import CLUE_SCHEMA_VERSION, normalize_clue_stages
from app.game.content_quality import content_fingerprint

SAMPLE_DATA = json.loads(
    (Path(__file__).parent / "data" / "sample.json").read_text(encoding="utf-8")
)
SAMPLE_SCRIPT_ID = SAMPLE_DATA["script_id"]
SAMPLE_TITLE = SAMPLE_DATA["title"]
CHARACTERS = SAMPLE_DATA["characters"]


def _game_process():
    return deepcopy(SAMPLE_DATA["game_full_process"])


def _sample_clue_stages():
    return normalize_clue_stages(deepcopy(SAMPLE_DATA["clue_stages"]), script_id=SAMPLE_SCRIPT_ID)


async def seed_sample_if_empty(session: AsyncSession) -> bool:
    if await session.scalar(select(func.count()).select_from(Script)):
        return False
    payload = deepcopy(SAMPLE_DATA)
    characters = payload.pop("characters")
    payload["clue_stages"] = _sample_clue_stages()
    payload["clue_schema_version"] = CLUE_SCHEMA_VERSION
    payload["content_fingerprint"] = content_fingerprint(payload, characters)
    session.add(Script(**payload, cover_image_url="", is_ai_generated=False))
    for character in characters:
        session.add(Character(script_id=SAMPLE_SCRIPT_ID, **character))
    await session.commit()
    return True
