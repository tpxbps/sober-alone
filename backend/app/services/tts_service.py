"""
TTSService - TTS 语音合成服务
提供静态音频合成（mimo-v2-tts）和按需合成（step-tts-mini）
"""

import httpx
import logging
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

# 音频文件存储根目录
AUDIO_ROOT = Path(__file__).parent.parent.parent / "data" / "audio"


class TTSService:
    """TTS 服务统一封装"""

    @staticmethod
    async def synthesize_static(text: str, style_prompt: str = "") -> bytes | None:
        """
        使用 mimo-v2-tts 生成静态音频

        mimo-v2-tts 通过 /v1/chat/completions 端点调用，
        text 放在 assistant message 中，style_prompt 放在 user message 中。

        Args:
            text: 要合成的文本内容
            style_prompt: 风格指导（如"以悬疑主持人的口吻朗读"）

        Returns:
            mp3 音频字节，失败返回 None
        """
        api_key = settings.MIMO_API_KEY
        if not api_key:
            logger.warning("MIMO_API_KEY not configured, skipping TTS")
            return None

        base_url = settings.MIMO_API_BASE_URL or "https://api.xiaomimimo.com/v1"

        messages = []
        if style_prompt:
            messages.append({"role": "user", "content": style_prompt})
        else:
            messages.append(
                {"role": "user", "content": "请自然地朗读以下内容，语速适中，语气自然。"}
            )
        messages.append({"role": "assistant", "content": text})

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "mimo-v2-tts",
                        "messages": messages,
                    },
                )
                response.raise_for_status()

                data = response.json()

                # mimo-v2-tts 返回格式:
                # choices[0].message.audio.data 为 base64 编码的音频数据 (WAV 格式)
                import base64 as _b64

                choices = data.get("choices", [])
                if not choices:
                    logger.warning(f"mimo-v2-tts: no choices in response")
                    return None

                message = choices[0].get("message", {})
                audio_obj = message.get("audio")

                if isinstance(audio_obj, dict) and "data" in audio_obj:
                    # 标准格式: choices[0].message.audio.data (base64 string)
                    return _b64.b64decode(audio_obj["data"])
                elif isinstance(audio_obj, str):
                    # 简化格式: choices[0].message.audio 直接是 base64
                    return _b64.b64decode(audio_obj)
                else:
                    logger.warning(f"Unexpected mimo-v2-tts audio field: {type(audio_obj)}")
                    return None

        except httpx.HTTPStatusError as e:
            logger.error(f"MiMo TTS HTTP error: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"MiMo TTS error: {e}")
            return None

    @staticmethod
    async def synthesize_on_demand(text: str, voice_id: str) -> bytes | None:
        """
        使用 step-tts-mini HTTP API 生成单条音频（用于历史消息按需生成）

        Args:
            text: 要合成的文本
            voice_id: 音色 ID（如 "cixingnansheng"）

        Returns:
            mp3 音频字节，失败返回 None
        """
        api_key = settings.STEPFUN_API_KEY
        if not api_key:
            logger.warning("STEPFUN_API_KEY not configured, skipping TTS")
            return None

        base_url = settings.STEPFUN_API_BASE_URL or "https://api.stepfun.com/v1"

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{base_url}/audio/speech",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "step-tts-mini",
                        "input": text,
                        "voice": voice_id,
                    },
                )
                response.raise_for_status()

                if response.content:
                    return response.content
                return None

        except httpx.HTTPStatusError as e:
            logger.error(
                f"StepFun TTS HTTP error: {e.response.status_code} - {e.response.text}"
            )
            return None
        except Exception as e:
            logger.error(f"StepFun TTS error: {e}")
            return None

    @staticmethod
    def get_static_audio_path(
        script_id: str, audio_type: str, identifier: str
    ) -> Path:
        """
        获取静态音频文件路径

        Args:
            script_id: 剧本 ID
            audio_type: "character_scripts" 或 "system_messages"
            identifier: 角色 ID 或消息 key

        Returns:
            音频文件路径
        """
        path = AUDIO_ROOT / "scripts" / script_id / audio_type / f"{identifier}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def get_static_audio_url(
        script_id: str, audio_type: str, identifier: str
    ) -> str:
        """
        获取静态音频文件的 URL

        Args:
            script_id: 剧本 ID
            audio_type: "character_scripts" 或 "system_messages"
            identifier: 角色 ID 或消息 key

        Returns:
            音频文件 URL（相对于 API 域名）
        """
        return f"/audio/scripts/{script_id}/{audio_type}/{identifier}.wav"

    @staticmethod
    async def generate_and_save_static(
        text: str,
        style_prompt: str,
        script_id: str,
        audio_type: str,
        identifier: str,
    ) -> str | None:
        """
        生成静态音频并保存到文件

        Returns:
            音频文件 URL，失败返回 None
        """
        file_path = TTSService.get_static_audio_path(script_id, audio_type, identifier)

        # 幂等：已存在则跳过
        if file_path.exists() and file_path.stat().st_size > 0:
            logger.info(f"Audio already exists: {file_path}")
            return TTSService.get_static_audio_url(script_id, audio_type, identifier)

        audio_data = await TTSService.synthesize_static(text, style_prompt)
        if audio_data:
            file_path.write_bytes(audio_data)
            logger.info(f"Saved audio: {file_path} ({len(audio_data)} bytes)")
            return TTSService.get_static_audio_url(script_id, audio_type, identifier)

        return None
