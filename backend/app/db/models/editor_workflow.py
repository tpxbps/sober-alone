"""Durable script-editor workflow and operation metadata."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class EditorWorkflow(Base):
    __tablename__ = "editor_workflows"

    thread_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    script_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_step: Mapped[str] = mapped_column(String(64), default="init")
    status: Mapped[str] = mapped_column(String(20), default="idle")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    operations: Mapped[list["EditorOperation"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )


class EditorOperation(Base):
    __tablename__ = "editor_operations"

    operation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("editor_workflows.thread_id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    target_step: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(20), default="queued")
    request_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    workflow: Mapped["EditorWorkflow"] = relationship(back_populates="operations")
