"""MiniMax HTTP SSE adapter exposing the existing speech stream contract."""

import base64
import json

from app.core.inference import gateway_async_client, gateway_key, gateway_url
from app.services.voices import resolve_minimax_voice


class MiniMaxTTSSession:
    def __init__(self):
        self._text = ""
        self._voice = ""
        self._closed = False
        self._response = None
        self.usage_characters = 0

    async def connect(self, voice_id: str) -> bool:
        gateway_key()
        self._voice = resolve_minimax_voice(voice_id)
        return True

    async def send_text(self, text: str):
        self._text += text

    async def flush(self):
        pass

    async def finish(self):
        pass

    async def receive_audio(self):
        from app.services.tts_service import split_text_for_tts

        for text in split_text_for_tts(self._text, 9000):
            if self._closed:
                return
            completed = False
            accumulated = bytearray()
            async with gateway_async_client(timeout=120) as client:
                async with client.stream(
                    "POST",
                    gateway_url("minimax/v1/t2a_v2"),
                    json={
                        "model": "minimax-speech-2.8-turbo",
                        "text": text,
                        "stream": True,
                        "stream_options": {"exclude_aggregated_audio": True},
                        "voice_setting": {
                            "voice_id": self._voice,
                            "speed": 1,
                            "vol": 1,
                            "pitch": 0,
                        },
                        "audio_setting": {
                            "sample_rate": 32000,
                            "bitrate": 128000,
                            "format": "mp3",
                            "channel": 1,
                        },
                    },
                ) as response:
                    self._response = response
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if self._closed:
                            return
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        if not payload:
                            continue
                        frame = json.loads(payload)
                        if (frame.get("base_resp") or {}).get("status_code", 0) != 0:
                            raise RuntimeError("语音服务返回失败，请重试")
                        data = frame.get("data") or {}
                        audio = bytes.fromhex(data.get("audio") or "")
                        if data.get("status") == 2:
                            completed = True
                            self.usage_characters += (frame.get("extra_info") or {}).get(
                                "usage_characters", 0
                            )
                            if accumulated and audio:
                                if not audio.startswith(accumulated):
                                    raise RuntimeError("语音终态与增量音频不一致")
                                audio = audio[len(accumulated) :]
                        if audio:
                            accumulated.extend(audio)
                            yield {"audio": base64.b64encode(audio).decode(), "duration": 0}
                        if completed:
                            break
                    self._response = None
            if not completed or not accumulated:
                raise RuntimeError("语音流未完整结束，请重试")

    async def close(self):
        self._closed = True
        if self._response is not None:
            await self._response.aclose()

    @property
    def is_connected(self):
        return bool(self._voice) and not self._closed
