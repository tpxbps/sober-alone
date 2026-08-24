"""Private browser-held author key helpers.

The raw key is accepted only from the request header.  Workflow checkpoints and
the application database store its SHA-256 digest, which is safe to compare but
is never serialized back to clients.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Annotated

from fastapi import Header, HTTPException

AUTHOR_KEY_HEADER = "X-Sober-Author-Key"
MIN_AUTHOR_KEY_LENGTH = 32


def hash_author_key(raw_key: str) -> str:
    key = raw_key.strip()
    if len(key) < MIN_AUTHOR_KEY_LENGTH:
        raise ValueError("作者凭证无效")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def owner_hash_matches(expected: str | None, provided: str | None) -> bool:
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected, provided)


def require_author_key_hash(
    raw_key: Annotated[str | None, Header(alias=AUTHOR_KEY_HEADER)] = None,
) -> str:
    if not raw_key:
        raise HTTPException(status_code=403, detail="缺少作者凭证")
    try:
        return hash_author_key(raw_key)
    except ValueError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


def optional_author_key_hash(
    raw_key: Annotated[str | None, Header(alias=AUTHOR_KEY_HEADER)] = None,
) -> str | None:
    if not raw_key:
        return None
    try:
        return hash_author_key(raw_key)
    except ValueError:
        return None
