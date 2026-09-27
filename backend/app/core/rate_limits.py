"""Content-free rate-limit signals and waiting within an existing retry budget."""

import math
import random
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

_RATE_LIMIT_CODES = frozenset(
    {"429", "rate_limit_error", "rate_limit_exceeded", "too_many_requests"}
)


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        try:
            date = parsedate_to_datetime(value)
            seconds = (date - datetime.now(UTC)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) and seconds >= 0 else None


def rate_limit_details(error: BaseException) -> dict | None:
    """Recognize explicit status/codes, never infer limits from free-form messages."""
    from app.core.inference import InferenceRecoveryError, raise_for_inference_recovery

    try:
        raise_for_inference_recovery(error)
    except InferenceRecoveryError:
        return None
    pending, seen = [error], set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        response = getattr(current, "response", None)
        status = getattr(current, "status_code", getattr(response, "status_code", None))
        body = getattr(current, "body", None)
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            body = body["error"]
        code = None
        if isinstance(body, dict):
            code = next(
                (
                    str(body[key]).lower()
                    for key in ("code", "type", "status")
                    if str(body.get(key)).lower() in _RATE_LIMIT_CODES
                ),
                None,
            )
        if status == 429 or code:
            headers = getattr(response, "headers", {})
            return {
                "http_status": 429 if status == 429 else None,
                "rate_limit_signal": "http_status" if status == 429 else "stream_code",
                "rate_limit_code": code,
                "retry_after_seconds": _retry_after(headers.get("retry-after")),
            }
        pending.extend(e for e in (current.__cause__, current.__context__) if e is not None)
    return None


def retry_delay_seconds(error: BaseException, *, remaining_seconds: float) -> float | None:
    """One existing retry, with jitter; never shorten the server's requested wait."""
    details = rate_limit_details(error)
    delay = random.uniform(0.5, 1.5)
    if details and details["retry_after_seconds"] is not None:
        delay = max(delay, details["retry_after_seconds"])
    return delay if delay < remaining_seconds else None
