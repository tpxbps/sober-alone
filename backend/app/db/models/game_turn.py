"""A durable, browser-independent speech operation (never stores credentials)."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GameTurn(Base):
    __tablename__ = "game_turns"

    turn_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("game_sessions.session_id", ondelete="CASCADE"), index=True
    )
    speaker_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(10))
    stage: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    state_revision: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text, default="")
    generation_done: Mapped[bool] = mapped_column(Boolean, default=False)
    thinking_tip: Mapped[str] = mapped_column(Text, default="")
    clue_refs: Mapped[list] = mapped_column(JSON, default=list)
    record_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_checkpoint_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    attempt_state: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str] = mapped_column(String(64), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    def snapshot(self):
        return {
            key: getattr(self, key)
            for key in (
                "turn_id",
                "session_id",
                "speaker_id",
                "kind",
                "stage",
                "status",
                "attempt",
                "seq",
                "state_revision",
                "content",
                "thinking_tip",
                "clue_refs",
                "record_id",
                "error_code",
                "error_message",
            )
        } | {"created_at": self.created_at.isoformat()}
