"""One private recommendation per anonymous browser and script."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ScriptFeedback(Base):
    __tablename__ = "script_feedback"
    __table_args__ = (UniqueConstraint("script_id", "reviewer_hash", name="uq_feedback_reviewer"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    script_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("scripts.script_id", ondelete="CASCADE"), index=True
    )
    reviewer_hash: Mapped[str] = mapped_column(String(64))
    recommended: Mapped[bool] = mapped_column(Boolean)
    comment: Mapped[str] = mapped_column(Text, default="")
    # Deliberately not a session FK: clearing finished games must retain feedback.
    source_session_id: Mapped[str] = mapped_column(String(36))
    content_fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
