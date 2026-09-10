"""Select an opt-in, immutable resource set using the session's own script text."""

import json
import re

from app.core.config import settings
from app.game.content_quality import content_fingerprint


def resource_namespace(script: dict) -> str:
    """Legacy assets stay available until a complete revision has been published.

    A resource producer writes ``resources.json`` last, after audio and vectors
    are ready. Never select resources using the current database row for an old
    session: callers must pass its immutable runtime snapshot.
    """
    script_id = str(script.get("script_id", ""))
    if not re.fullmatch(r"[A-Za-z0-9_-]+", script_id):
        raise ValueError("Invalid resource script ID")
    fingerprint = content_fingerprint(script)
    namespace = f"{script_id}__{fingerprint}"
    manifest = settings.audio_dir / "scripts" / namespace / "resources.json"
    if not manifest.exists():
        return script_id
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("content_fingerprint") != fingerprint or data.get("status") != "ready":
        raise ValueError("Incomplete or mismatched script resources")
    return namespace
