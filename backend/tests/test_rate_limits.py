import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from openai import APIError, RateLimitError

from app.core import rate_limits
from app.core.inference import InferenceRecoveryError, retryable_gateway_error


def limited(retry_after=None):
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return RateLimitError(
        "private provider response",
        response=httpx.Response(
            429, headers=headers, request=httpx.Request("POST", "https://example.invalid")
        ),
        body={"error": {"code": "rate_limit_exceeded", "message": "private response"}},
    )


def test_http_limit_keeps_only_safe_metadata():
    error = limited("8")
    details = rate_limits.rate_limit_details(error)
    assert details == {
        "http_status": 429,
        "rate_limit_signal": "http_status",
        "rate_limit_code": "rate_limit_exceeded",
        "retry_after_seconds": 8,
    }
    assert "private" not in json.dumps(details)
    assert retryable_gateway_error(error)


def test_stream_limit_and_wrapped_error_are_recognized_without_guessing_messages():
    request = httpx.Request("POST", "https://example.invalid")
    error = APIError("private response", request=request, body={"code": "rate_limit_exceeded"})
    wrapped = RuntimeError("wrapper")
    wrapped.__cause__ = error
    assert retryable_gateway_error(wrapped)
    assert rate_limits.rate_limit_details(wrapped)["http_status"] is None
    assert rate_limits.rate_limit_details(wrapped)["rate_limit_signal"] == "stream_code"
    assert not retryable_gateway_error(APIError("429 rate limit", request=request, body=None))


def test_account_recovery_wins_over_429():
    error = limited()
    error.__cause__ = InferenceRecoveryError("api_key_quota", status=429)
    assert not retryable_gateway_error(error)
    assert rate_limits.rate_limit_details(error) is None


@pytest.mark.parametrize("value", ["bad", "nan", "inf", "-2", "1e999"])
def test_invalid_retry_after_uses_existing_jitter(monkeypatch, value):
    monkeypatch.setattr(rate_limits.random, "uniform", lambda *_: 1)
    assert rate_limits.retry_delay_seconds(limited(value), remaining_seconds=10) == 1


def test_retry_after_date_and_budget_are_respected(monkeypatch):
    monkeypatch.setattr(rate_limits.random, "uniform", lambda *_: 1)
    date = format_datetime(datetime.now(UTC) + timedelta(seconds=30))
    delay = rate_limits.retry_delay_seconds(limited(date), remaining_seconds=60)
    assert 28 <= delay <= 30
    assert rate_limits.retry_delay_seconds(limited("30"), remaining_seconds=20) is None
    assert rate_limits.retry_delay_seconds(limited("20"), remaining_seconds=20) is None
    assert rate_limits.retry_delay_seconds(limited("0"), remaining_seconds=20) == 1
