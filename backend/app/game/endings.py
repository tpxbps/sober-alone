"""Author-defined epilogues selected by the final vote, never by an LLM."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Outcome = Literal["correct", "incorrect", "tie", "no_votes"]
OUTCOMES = ("correct", "incorrect", "tie", "no_votes")


class EndingBranch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    when: Outcome
    title: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=12000)


class EndingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    mode: Literal["single", "multiple"] = "single"
    culprit_character_id: str = ""
    branches: list[EndingBranch] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def complete_branches(self):
        if self.mode == "multiple":
            if not self.culprit_character_id:
                raise ValueError("多结局必须选择用于投票判定的真凶")
            if len(self.branches) != 4 or {b.when for b in self.branches} != set(OUTCOMES):
                raise ValueError("多结局须各有一个正确、错误、平票、无有效票分支，不可重复或缺失")
        elif self.branches or self.culprit_character_id:
            raise ValueError("单结局不能携带多结局分支或判定角色")
        return self


def normalize_endings(value, characters: list[dict] | None = None) -> dict | None:
    if isinstance(value, str):
        value = json.loads(value)
    if value is None:
        return None
    config = EndingConfig.model_validate(value)
    if config.mode == "single":
        return None
    if characters is not None and config.culprit_character_id not in {
        str(c.get("character_id", "")) for c in characters
    }:
        raise ValueError("结局判定角色必须来自本剧本角色列表")
    result = config.model_dump()
    result["branches"] = sorted(result["branches"], key=lambda b: OUTCOMES.index(b["when"]))
    return result


def select_ending(script: dict, vote_results: dict) -> dict | None:
    config = normalize_endings(script.get("ending_config"), script.get("characters"))
    if not config:
        return None
    # Recompute from actual vote counts, independent of insertion-order tie breaking.
    counts = vote_results.get("vote_count") or {}
    maximum = max(counts.values(), default=0)
    leaders = [cid for cid, count in counts.items() if count == maximum and maximum > 0]
    if not leaders:
        outcome = "no_votes"
    elif len(leaders) > 1:
        outcome = "tie"
    elif leaders[0] == config["culprit_character_id"]:
        outcome = "correct"
    else:
        outcome = "incorrect"
    return next(dict(branch) for branch in config["branches"] if branch["when"] == outcome)


def render_ending(ending: dict | None) -> str:
    return f"## 本局结局：{ending['title']}\n\n{ending['text']}" if ending else ""


def ending_audio_tasks(script: dict) -> list[dict]:
    """One independently playable epilogue, with no unused branches in its audio."""
    config = normalize_endings(script.get("ending_config"))
    return (
        [
            {
                "id": f"tts_ending_{b['when']}",
                "path": f"ending_{b['when']}",
                "label": f"结局·{b['title']} TTS",
                "text": render_ending(b),
            }
            for b in config["branches"]
        ]
        if config
        else []
    )
