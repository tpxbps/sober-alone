"""Anonymous, session-bound recommendations; no public comment feed."""

import hashlib
import re
import secrets
from datetime import datetime

from fastapi import HTTPException, Request, Response
from sqlalchemy import case, func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GameRecord, GameSession, ScriptFeedback
from app.game.content_quality import content_fingerprint

FEEDBACK_COOKIE = "sober_feedback_v1"


def reviewer_identity(request: Request, response: Response | None = None) -> str | None:
    raw = request.cookies.get(FEEDBACK_COOKIE, "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", raw):
        if response is None:
            return None
        raw = secrets.token_urlsafe(32)
        response.set_cookie(
            FEEDBACK_COOKIE,
            raw,
            max_age=365 * 86400,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            path="/",
        )
    return hashlib.sha256(raw.encode()).hexdigest()


def feedback_summary(total: int = 0, positive: int = 0) -> dict:
    p = positive / total if total else None
    label = "待评价"
    if total >= 5 and p is not None:
        if total >= 50 and p >= 0.95:
            label = "好评如潮"
        elif total >= 50 and p <= 0.05:
            label = "差评如潮"
        elif total >= 20 and p >= 0.8:
            label = "特别好评"
        elif total >= 20 and p < 0.2:
            label = "一片差评"
        else:
            label = next(
                label
                for threshold, label in (
                    (0.8, "好评"),
                    (0.7, "多半好评"),
                    (0.4, "褒贬不一"),
                    (0.2, "多半差评"),
                    (0, "差评"),
                )
                if p >= threshold
            )
    return {
        "total": total,
        "positive": positive,
        "positive_rate": p,
        "label": label,
        "threshold": 5,
    }


async def feedback_summaries(db: AsyncSession) -> dict[str, dict]:
    rows = await db.execute(
        select(
            ScriptFeedback.script_id,
            func.count(),
            func.sum(case((ScriptFeedback.recommended.is_(True), 1), else_=0)),
        ).group_by(ScriptFeedback.script_id)
    )
    return {script_id: feedback_summary(total, positive) for script_id, total, positive in rows}


async def eligible_session(db: AsyncSession, session_id: str, reviewer: str | None) -> GameSession:
    session = await db.get(GameSession, session_id)
    if not session:
        raise HTTPException(404, "对局不存在")
    if (
        not reviewer
        or not session.reviewer_hash
        or not secrets.compare_digest(session.reviewer_hash, reviewer)
    ):
        raise HTTPException(403, "此浏览器未绑定该对局，无法评价")
    has_reveal = await db.scalar(
        select(GameRecord.id)
        .where(
            GameRecord.session_id == session_id,
            GameRecord.stage == "review",
            GameRecord.record_type == "system",
        )
        .limit(1)
    )
    if (
        session.current_stage not in ("review", "completed")
        or not has_reveal
        or session.human_character_id not in (session.votes or {})
    ):
        raise HTTPException(409, "完成投票并揭晓真相后才能评价")
    return session


async def read_feedback(db: AsyncSession, session: GameSession) -> dict | None:
    feedback = await db.scalar(
        select(ScriptFeedback).where(
            ScriptFeedback.script_id == session.script_id,
            ScriptFeedback.reviewer_hash == session.reviewer_hash,
        )
    )
    if not feedback:
        return None
    return {
        "recommended": feedback.recommended,
        "comment": feedback.comment,
        "updated_at": feedback.updated_at.isoformat(),
    }


async def save_feedback(
    db: AsyncSession, session: GameSession, recommended: bool, comment: str | None
) -> dict:
    now = datetime.now()
    snapshot = session.runtime_snapshot or {}
    script = snapshot.get("script", snapshot)
    values = {
        "script_id": session.script_id,
        "reviewer_hash": session.reviewer_hash,
        "recommended": recommended,
        "comment": (comment or "").strip(),
        "source_session_id": session.session_id,
        "content_fingerprint": content_fingerprint(script, snapshot.get("characters")),
        "created_at": now,
        "updated_at": now,
    }
    update = {
        k: v for k, v in values.items() if k not in ("script_id", "reviewer_hash", "created_at")
    }
    if comment is None:
        update.pop("comment")
    await db.execute(
        insert(ScriptFeedback)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["script_id", "reviewer_hash"],
            set_=update,
        )
    )
    await db.commit()
    return await read_feedback(db, session)
