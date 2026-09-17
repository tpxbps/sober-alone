"""Chronological conversation, independent from the editable outline paragraphs."""


def append_event(
    session: dict, kind: str, content: str = "", *, event_id: str, question: dict | None = None
) -> None:
    events = session.setdefault("events", [])
    if any(event["id"] == event_id for event in events):
        return
    event = {"id": event_id, "seq": len(events) + 1, "kind": kind, "content": content}
    if question:
        event["question"] = question
    events.append(event)


def ensure_conversation(session: dict) -> dict:
    if "events" not in session:
        # Old paragraph indices are not reliable after revisions. Do not invent
        # an interleaved chronology; retain the recovered text as one snapshot.
        text = "\n\n".join(p["content"] for p in session.get("segments", []))
        if text:
            append_event(session, "restored", text, event_id="restored-outline")
        decisions = "\n\n".join(
            "\n".join(filter(None, (d.get("choice"), d.get("other_text"))))
            for d in session.get("decisions", [])
        )
        if decisions:
            append_event(
                session,
                "restored",
                "此前记录的作者输入：\n" + decisions,
                event_id="restored-decisions",
            )
        session.setdefault("events", [])
    session["protocol_version"] = 3
    return session
