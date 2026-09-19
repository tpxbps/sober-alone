"""Versioned, declarative clue media. No executable scene content is accepted."""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def clue_source(clue) -> str:
    return digest({k: clue.get(k, "") for k in ("id", "summary", "content")})


def stage_source(stage) -> str:
    return digest(
        {
            "stage": stage["stage"],
            "overview": stage.get("overview", ""),
            "items": [clue_source(item) for item in stage["items"]],
        }
    )


class Media(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image_url: str
    thumbnail_url: str
    alt: str = Field(max_length=300)
    focus: tuple[float, float] = (0.5, 0.5)
    mobile_focus: tuple[float, float] | None = None
    source_hash: str = ""
    status: Literal["ready", "needs_review"] = "ready"

    @field_validator("image_url", "thumbnail_url")
    @classmethod
    def local_image(cls, value):
        from urllib.parse import unquote

        if not value.startswith("/images/") or any(
            part in unquote(value) for part in ("..", "\\", "?", "#", "\x00")
        ):
            raise ValueError("线索图片必须是本地 /images/ 资源")
        return value

    @field_validator("focus", "mobile_focus")
    @classmethod
    def focal_point(cls, value):
        if value is not None and any(not 0 <= number <= 1 for number in value):
            raise ValueError("裁切焦点必须位于 0 到 1 之间")
        return value


class Shot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80)
    duration_ms: int = Field(ge=1000, le=15000)
    clue_ids: list[str] = Field(default_factory=list, max_length=4)
    title: str = Field(max_length=120)
    caption: str = Field(default="", max_length=400)
    emphasis: str = Field(default="", max_length=200)
    motion: Literal["push", "pan", "split", "reveal", "timeline", "chain"] = "push"
    labels: list[str] = Field(default_factory=list, max_length=6)


class Presentation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1, 2] = 1
    revision: str = Field(min_length=1, max_length=80)
    template: Literal["cinematic", "dossier"]
    title: str = Field(min_length=1, max_length=120)
    background: Media | None = None
    shots: list[Shot] = Field(min_length=1, max_length=20)
    source_hash: str = ""
    status: Literal["ready", "needs_review"] = "ready"


def normalize_media(raw, clue):
    media = Media.model_validate(raw).model_dump(mode="json", exclude_none=True)
    source = clue_source(clue)
    if media["source_hash"] and media["source_hash"] != source:
        media["status"] = "needs_review"
    media["source_hash"] = media["source_hash"] or source
    return media


def normalize_presentation(raw, stage, allowed_ids):
    value = Presentation.model_validate(raw).model_dump(mode="json", exclude_none=True)
    if sum(shot["duration_ms"] for shot in value["shots"]) > 90000:
        raise ValueError("线索演出不能超过 90 秒")
    if len({shot["id"] for shot in value["shots"]}) != len(value["shots"]):
        raise ValueError("镜头 ID 不能重复")
    source = stage_source(stage)
    if value["source_hash"] and value["source_hash"] != source:
        value["status"] = "needs_review"
    value["source_hash"] = value["source_hash"] or source
    for shot in value["shots"]:
        if set(shot["clue_ids"]) - allowed_ids:
            # A text edit may remove an old clue: retain the disabled resource for review.
            if value["status"] != "needs_review":
                raise ValueError("线索演出不能引用未公开或不存在的线索")
    return value


def presentation_state(session):
    state = getattr(session, "clue_presentation_state", None)
    return state if isinstance(state, dict) else None


def presentation_pending(session):
    return (presentation_state(session) or {}).get("status") == "pending"


def public_presentation(session, stages):
    state = presentation_state(session)
    if not state:
        return None
    stage = next((s for s in stages if s["stage"] == state["round"]), None)
    if not stage:
        return {**state, "presentation": None, "clues": []}
    config = stage.get("presentation")
    if config and config.get("status") != "ready":
        config = None
    return {
        **state,
        "presentation": config,
        "clues": stage["items"],
        "reference_clues": [
            item for s in stages if s["stage"] <= state["round"] for item in s["items"]
        ],
    }
