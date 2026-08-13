"""
StreamingTTSSession - StepFun WebSocket 流式 TTS 会话管理
用于 AI 角色发言的实时语音生成
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator

import websockets

from app.core.config import settings

logger = logging.getLogger(__name__)


class StreamingTTSSession:
    """管理一个 StepFun WebSocket TTS 流式会话"""

    def __init__(self):
        self._ws = None
        self._session_id: str | None = None
        self._connected = False
        self._audio_queue: asyncio.Queue[dict | None] = asyncio.Queue()
        self._receive_task: asyncio.Task | None = None

    async def connect(self, voice_id: str) -> bool:
        """
        建立 WebSocket 连接到 StepFun TTS 服务

        Args:
            voice_id: 音色 ID

        Returns:
            是否连接成功
        """
        api_key = settings.STEPFUN_API_KEY
        if not api_key:
            logger.warning("STEPFUN_API_KEY not configured")
            return False

        url = "wss://api.stepfun.com/v1/realtime/audio?model=step-tts-mini"
        headers = {"Authorization": f"Bearer {api_key}"}

        try:
            self._ws = await websockets.connect(
                url,
                additional_headers=headers,
                ping_interval=None,
            )

            # 等待连接成功事件
            msg = await asyncio.wait_for(self._ws.recv(), timeout=10.0)
            data = json.loads(msg)

            if data.get("type") != "tts.connection.done":
                logger.error(f"Unexpected connection event: {data}")
                await self.close()
                return False

            self._session_id = data["data"]["session_id"]

            # 发送创建会话事件
            create_event = {
                "type": "tts.create",
                "data": {
                    "session_id": self._session_id,
                    "voice_id": voice_id,
                    "response_format": "mp3",
                    "volume_ratio": 1.0,
                    "speed_ratio": 1.0,
                    "sample_rate": 24000,
                    "mode": "sentence",  # 按句生成，适合完整文本
                },
            }
            await self._ws.send(json.dumps(create_event))

            # 等待会话创建成功
            msg = await asyncio.wait_for(self._ws.recv(), timeout=10.0)
            data = json.loads(msg)

            if data.get("type") != "tts.response.created":
                logger.error(f"Unexpected create response: {data}")
                await self.close()
                return False

            self._connected = True

            # 启动后台接收任务
            self._receive_task = asyncio.create_task(self._receive_loop())

            logger.info(f"TTS streaming session connected: {self._session_id}")
            return True

        except TimeoutError:
            logger.error("TTS WebSocket connection timeout")
            await self.close()
            return False
        except Exception as e:
            logger.error(f"TTS WebSocket connection error: {e}")
            await self.close()
            return False

    async def send_text(self, text: str):
        """
        发送文本片段到 TTS 服务
        自动拆分超过 900 字的文本，避免触发 step-tts-mini 的 1000 字限制

        Args:
            text: 文本片段（通常是 LLM 生成的 token）
        """
        if not self._connected or not self._ws:
            return

        # 如果文本较短，直接发送
        if len(text) <= 900:
            await self._send_text_delta(text)
            return

        # 长文本拆分：按句子边界切割
        from app.services.tts_service import STEP_MAX_CHARS, split_text_for_tts

        chunks = split_text_for_tts(text, STEP_MAX_CHARS)
        for chunk in chunks:
            await self._send_text_delta(chunk)

    async def _send_text_delta(self, text: str):
        """发送单个文本片段"""
        if not self._ws or not self._connected:
            return
        try:
            event = {
                "type": "tts.text.delta",
                "data": {
                    "session_id": self._session_id,
                    "text": text,
                },
            }
            await self._ws.send(json.dumps(event))
        except Exception as e:
            logger.error(f"Error sending text to TTS: {e}")

    async def flush(self):
        """清空 TTS 缓冲区，强制返回已生成的音频"""
        if not self._connected or not self._ws:
            return

        try:
            event = {
                "type": "tts.text.flush",
                "data": {"session_id": self._session_id},
            }
            await self._ws.send(json.dumps(event))
        except Exception as e:
            logger.error(f"Error flushing TTS: {e}")

    async def finish(self):
        """结束文本发送，通知 TTS 服务不再有新文本"""
        if not self._connected or not self._ws:
            return

        try:
            event = {
                "type": "tts.text.done",
                "data": {"session_id": self._session_id},
            }
            await self._ws.send(json.dumps(event))
        except Exception as e:
            logger.error(f"Error finishing TTS: {e}")

    async def _receive_loop(self):
        """后台持续接收音频数据并放入队列"""
        if not self._ws:
            return
        try:
            async for msg in self._ws:
                data = json.loads(msg)
                event_type = data.get("type")

                if event_type == "tts.response.audio.delta":
                    audio_b64 = data.get("data", {}).get("audio", "")
                    duration = data.get("data", {}).get("duration", 0)
                    status = data.get("data", {}).get("status", "unfinished")

                    if audio_b64:
                        await self._audio_queue.put(
                            {
                                "audio": audio_b64,
                                "duration": duration,
                                "status": status,
                            }
                        )

                elif event_type == "tts.response.audio.done":
                    # 所有音频生成完毕 — 不转发 audio.done 中的完整音频
                    # 前端已通过 audio.delta 累积了所有流式 chunks
                    await self._audio_queue.put(None)
                    break

                elif event_type == "tts.response.error":
                    error_msg = data.get("data", {}).get("message", "Unknown error")
                    logger.error(f"TTS streaming error: {error_msg}")
                    await self._audio_queue.put(None)
                    break

                elif event_type == "tts.text.flushed":
                    pass  # 确认刷新

        except websockets.exceptions.ConnectionClosed:
            logger.info("TTS WebSocket connection closed")
        except Exception as e:
            logger.error(f"TTS receive loop error: {e}")
        finally:
            await self._audio_queue.put(None)

    async def receive_audio(self) -> AsyncIterator[dict]:
        """
        异步迭代接收音频数据

        Yields:
            dict: {"audio": base64_string, "duration": float, "status": str}
        """
        while True:
            item = await self._audio_queue.get()
            if item is None:
                break
            yield item

    async def close(self):
        """关闭 WebSocket 连接"""
        self._connected = False

        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        logger.info("TTS streaming session closed")

    @property
    def is_connected(self) -> bool:
        return self._connected
