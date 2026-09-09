"""Only the browser that completed a game may read/update its own feedback."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.script_feedback import (
    eligible_session,
    read_feedback,
    reviewer_identity,
    save_feedback,
)

router = APIRouter()


class FeedbackRequest(BaseModel):
    recommended: bool
    comment: str | None = Field(default=None, max_length=1000)


@router.get("/{session_id}/feedback")
async def get_feedback(session_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    session = await eligible_session(db, session_id, reviewer_identity(request))
    return {"success": True, "feedback": await read_feedback(db, session)}


@router.put("/{session_id}/feedback")
async def put_feedback(
    session_id: str, body: FeedbackRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    session = await eligible_session(db, session_id, reviewer_identity(request))
    return {
        "success": True,
        "feedback": await save_feedback(db, session, body.recommended, body.comment),
    }
