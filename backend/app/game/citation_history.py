"""Repair old AI citations using the public announcements preceding each speech.

Never infer historical permission from the session's current clue list alone.
This is a read adapter; saved messages and game snapshots remain unchanged.
"""

from app.game.clues import parse_clue_citations, stage_public_clues


def display_records(records, session):
    clues = {clue["id"]: clue for clue in (session.revealed_clues or [])}
    disclosed = set()
    result = []
    for record in records:
        saved = set(record.clue_refs or [])
        if record.record_type == "system" and record.stage == "clue_analysis":
            disclosed.update(saved & clues.keys())
        item = record.to_display_dict()
        if item is None:
            continue
        if record.record_type == "speech":
            is_ai = record.speaker_character_id != session.human_character_id
            # Saved references remain the fallback for pre-announcement legacy games.
            allowed = stage_public_clues(
                record.stage, [clues[id] for id in disclosed | saved if id in clues]
            )
            content, refs, _ = parse_clue_citations(
                record.raw_content or "", allowed, strip_unknown=is_ai
            )
            item["content"] = content if is_ai else record.raw_content
            item["clue_refs"] = refs
        result.append(item)
    return result
