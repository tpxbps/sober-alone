"""Content identity shared by indexing and immutable session memory."""

import hashlib


def script_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
