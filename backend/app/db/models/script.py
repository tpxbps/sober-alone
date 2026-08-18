"""Script and character models owned by the local application database."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.game_session import GameSession


class Script(Base):
    __tablename__ = "scripts"

    script_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    overview: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(String(500), default="")
    difficulty: Mapped[int] = mapped_column(Integer, default=1)
    player_count: Mapped[int] = mapped_column(Integer, default=4)
    estimated_duration: Mapped[int] = mapped_column(Integer, default=20)
    game_full_process: Mapped[list] = mapped_column(JSON, default=list)
    full_truth: Mapped[str] = mapped_column(Text, default="")
    cover_image_url: Mapped[str] = mapped_column(String(500), default="")
    free_speech_limits: Mapped[list] = mapped_column(JSON, default=list)
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    characters: Mapped[list[Character]] = relationship(
        back_populates="script", cascade="all, delete-orphan"
    )
    sessions: Mapped[list[GameSession]] = relationship(
        back_populates="script", cascade="all, delete-orphan"
    )


class Character(Base):
    __tablename__ = "characters"

    character_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    script_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("scripts.script_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    gender: Mapped[str] = mapped_column(String(20), default="")
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occupation: Mapped[str] = mapped_column(String(100), default="")
    character_script: Mapped[str] = mapped_column(Text, default="")
    character_script_summary: Mapped[str] = mapped_column(Text, default="")
    profile: Mapped[str] = mapped_column(Text, default="")
    appearance: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    avatar_url: Mapped[str] = mapped_column(String(500), default="")
    portrait_url: Mapped[str] = mapped_column(String(500), default="")
    voice_id: Mapped[str] = mapped_column(String(100), default="")

    script: Mapped[Script] = relationship(back_populates="characters")
