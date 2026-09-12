"""One persistence contract for role beliefs and incremental speech observations."""

from __future__ import annotations

import hashlib
from typing import Any

from app.agents.reaction import SpeechReaction, SuspectedByValue, SuspicionValue


def canonical_graph(graph: dict, names: dict[str, str], *, incoming=False, model=SuspicionValue):
    """Read legacy names; an existing ID wins conflicts whose age is unknowable."""
    reverse = {name: cid for cid, name in names.items()}
    result = {}
    for key, value in (graph or {}).items():
        cid = key if key in names else reverse.get(key)
        if cid is None:
            if incoming:
                raise ValueError(f"未知角色：{key}")
            continue
        if incoming and cid in result:
            raise ValueError(f"同一角色不能重复更新：{key}")
        try:
            parsed = model.model_validate(value).model_dump()
        except ValueError:
            if incoming:
                raise
            continue
        if cid not in result or key == cid:
            result[cid] = parsed
    return result


def normalize_beliefs(player, names: dict[str, str]) -> None:
    player.suspicion_reasons = canonical_graph(player.suspicion_reasons, names)
    player.suspected_by = canonical_graph(player.suspected_by, names, model=SuspectedByValue)
    player.suspicion = {cid: value["score"] for cid, value in player.suspicion_reasons.items()}
    scores = [value["score"] for value in player.suspected_by.values()]
    player.suspected_intensity = sum(scores) / len(scores) if scores else 0.0


def apply_beliefs(player, reaction: SpeechReaction | dict, names: dict[str, str]) -> None:
    """Validate the whole update before assigning any field. Scores are absolute."""
    value = reaction.model_dump() if isinstance(reaction, SpeechReaction) else reaction
    suspicion = canonical_graph(value.get("my_suspicion_graph", {}), names, incoming=True)
    suspected = canonical_graph(
        value.get("my_suspected_by", {}), names, incoming=True, model=SuspectedByValue
    )
    if player.character_id in suspicion or player.character_id in suspected:
        raise ValueError("不能将自己作为怀疑关系目标")
    normalize_beliefs(player, names)
    player.suspicion_reasons = {**player.suspicion_reasons, **suspicion}
    player.suspected_by = {**player.suspected_by, **suspected}
    normalize_beliefs(player, names)


def observations(value: dict | None) -> dict[str, list[dict[str, Any]]]:
    """Upgrade legacy strings without losing their text or changing new entry IDs."""
    result = {}
    for speaker, entries in (value or {}).items():
        entries = entries if isinstance(entries, list) else [entries]
        converted = []
        for index, entry in enumerate(entries):
            if isinstance(entry, dict) and entry.get("entry_id"):
                converted.append(dict(entry))
            elif isinstance(entry, str) and entry:
                key = hashlib.sha256(f"{speaker}:{index}:{entry}".encode()).hexdigest()[:20]
                converted.append(
                    {
                        "entry_id": f"legacy:{key}",
                        "record_id": None,
                        "speaker_id": speaker,
                        "kind": "summary",
                        "text": entry,
                    }
                )
        if converted:
            result[speaker] = converted
    return result


def put_observation(
    player, speaker: str, record_id: int, text: str, kind: str, *, stage="", round_num=0
) -> None:
    values = observations(player.player_perspectives)
    key = f"speech:{record_id}"
    entries = [entry for entry in values.get(speaker, []) if entry["entry_id"] != key]
    entries.append(
        {
            "entry_id": key,
            "record_id": record_id,
            "speaker_id": speaker,
            "kind": kind,
            "text": text,
            "stage": stage,
            "round_num": round_num,
        }
    )
    values[speaker] = entries
    player.player_perspectives = values
