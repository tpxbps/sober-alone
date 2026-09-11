"""Explicit checked-content fixtures for persistence and workflow regression tests."""

from app.script_editor.editing import hydrate_completed_script, normalize_game_data
from app.script_editor.nodes.quality_check import (
    CAPABILITY_VERSION,
    QUALITY_CHECK_VERSION,
    quality_fingerprint,
)
from app.script_editor.nodes.safety_check import SAFETY_VERSION, review_chunks, safety_fingerprint


def valid_state():
    from test_script_editing import completed_script

    script, characters = completed_script()
    state = hydrate_completed_script(script, characters, script.owner_key_hash or "")
    state["workflow_mode"] = "create"
    state["original_snapshot"] = {}
    state.update(normalize_game_data(state))
    return state


def approve(state):
    """Simulate successful judges without patching or bypassing the production gate."""
    normalized = normalize_game_data(state)
    assert not normalized.get("data_validation_errors"), normalized
    state.update(normalized)
    state["quality_report"] = {
        "status": "passed",
        "check_version": QUALITY_CHECK_VERSION,
        "capability_version": CAPABILITY_VERSION,
        "content_fingerprint": quality_fingerprint(state),
    }
    count = len(list(review_chunks(state["game_data_sections"])))
    state["safety_report"] = {
        "status": "passed",
        "version": SAFETY_VERSION,
        "fingerprint": safety_fingerprint(state),
        "total": count,
        "passed": count,
    }
    return state
