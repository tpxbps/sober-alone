import json
from types import SimpleNamespace

import pytest

from app.services.game_speech import GameSpeechService, encode_sse


def event_type(frame: str) -> str:
    return json.loads(frame.removeprefix("data: "))["type"]


def test_encode_sse_preserves_unicode_and_wire_terminator():
    assert encode_sse({"type": "token", "text": "雾港"}) == (
        'data: {"type": "token", "text": "雾港"}\n\n'
    )


@pytest.mark.asyncio
async def test_human_stream_event_order_is_stable():
    class Controller:
        session = SimpleNamespace(
            human_character_id="human",
            current_speaker="human",
            current_stage="intro",
        )
        agent_manager = SimpleNamespace(get_character_name=lambda character_id: "赵屿")

        async def process_speech(self, **_kwargs):
            return {
                "success": True,
                "reactions": [{"character_id": "ai", "content": "我会核对时间线。"}],
                "next_speaker": "ai",
                "next_speaker_name": "赵屿",
            }

    async def ensure_controller(_session_id, _db):
        return Controller()

    service = GameSpeechService(object(), ensure_controller)
    frames = [frame async for frame in service.stream_human("session", "我的发言")]

    assert [event_type(frame) for frame in frames] == [
        "speech_recorded",
        "thinking",
        "reaction",
        "reactions_done",
        "done",
    ]


@pytest.mark.asyncio
async def test_ai_stream_finishes_with_speech_done_then_done():
    class Controller:
        async def generate_ai_speech(self, _character_id, _db):
            yield {"type": "progress", "status": "正在整理线索"}
            yield {"type": "token", "text": "结论"}

        async def process_speech(self, **_kwargs):
            return {"next_speaker": "human", "next_speaker_name": "林岚"}

    async def ensure_controller(_session_id, _db):
        return Controller()

    service = GameSpeechService(object(), ensure_controller)
    frames = [frame async for frame in service.stream_ai("session", "ai")]

    assert [event_type(frame) for frame in frames] == [
        "thinking",
        "token",
        "speech_done",
        "done",
    ]
