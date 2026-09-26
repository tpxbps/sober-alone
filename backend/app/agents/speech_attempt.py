"""An uncommitted role generation. Never serialize this context into graph state."""

import asyncio
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SpeechAttempt:
    generation_id: str
    attempt_id: str
    active: bool = True
    thread_id: str | None = None
    previous_thread_id: str | None = None
    checkpointer: Any = None
    started: float = field(default_factory=time.monotonic)
    first_event_ms: float | None = None
    observation_ids: set[str] = field(default_factory=set)
    role_updates: list[Any] = field(default_factory=list)

    def check(self):
        if not self.active:
            raise asyncio.CancelledError("Speech attempt is no longer current")


_attempt: ContextVar[SpeechAttempt | None] = ContextVar("speech_attempt", default=None)


def current_speech_attempt() -> SpeechAttempt | None:
    attempt = _attempt.get()
    if attempt:
        attempt.check()
    return attempt


@contextmanager
def speech_attempt_scope(attempt: SpeechAttempt):
    token = _attempt.set(attempt)
    try:
        yield attempt
    finally:
        _attempt.reset(token)
