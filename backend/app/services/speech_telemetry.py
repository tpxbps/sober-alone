"""Optional content-free observer for deployments with a metrics sink."""

import logging
from collections.abc import Callable
from typing import Any

_observer: Callable[[dict[str, Any]], None] | None = None


def set_speech_observer(observer):
    global _observer
    _observer = observer


def report_speech_metric(event: str, session_id: str, generation: dict, **values):
    if _observer is None:
        return
    payload = {
        "event": event,
        "session_id": session_id,
        **{
            key: generation.get(key)
            for key in (
                "generation_id",
                "attempt_id",
                "character_id",
                "stage",
                "round",
                "attempt",
            )
        },
        **{
            key: value
            for key, value in values.items()
            if key
            in {
                "duration_ms",
                "cycle_duration_ms",
                "first_event_ms",
                "first_visible_ms",
                "client_first_display_ms",
                "reason",
                "direct_refs",
                "associated_refs",
                "unknown_refs",
            }
        },
    }
    try:
        _observer(payload)
    except Exception:
        logging.getLogger(__name__).warning("Speech metrics sink unavailable")
