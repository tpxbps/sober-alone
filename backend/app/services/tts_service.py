"""
TTSService - TTS 语音合成服务
提供静态音频合成（mimo-v2.5-tts）和按需合成（step-tts-mini）
"""

import logging
import struct
from pathlib import Path

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# 音频文件存储根目录
AUDIO_ROOT = settings.audio_dir

# === 文本分块工具 ===

# mimo-v2.5-tts: 8K token 上下文
MIMO_MAX_CHARS = 4000
# step-tts-mini: 1000 字限制
STEP_MAX_CHARS = 900

# 中文句末标点
_SENTENCE_ENDS = set("。！？；\n")


def split_text_for_tts(text: str, max_chars: int = MIMO_MAX_CHARS) -> list[str]:
    """将长文本按句子边界拆分为适合 TTS 的块。

    优先在句号、感叹号、问号等句末标点处拆分，
    若单个句子超过 max_chars 则在逗号处拆分。
    """
    if not text or not text.strip():
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break

        # 在 max_chars 范围内找最后一个句末标点
        cut = -1
        for i in range(min(len(remaining), max_chars) - 1, max_chars // 3, -1):
            if remaining[i] in _SENTENCE_ENDS:
                cut = i + 1
                break

        # 没有句末标点，找逗号
        if cut <= 0:
            for i in range(min(len(remaining), max_chars) - 1, max_chars // 3, -1):
                if remaining[i] in "，、,;":
                    cut = i + 1
                    break

        # 仍然没有，强制切割
        if cut <= 0:
            cut = max_chars

        chunks.append(remaining[:cut])
        remaining = remaining[cut:]

    return [c for c in chunks if c.strip()]


# === WAV 音频拼接工具 ===


def concatenate_wav(wav_chunks: list[bytes], silence_ms: int = 300) -> bytes:
    """将多个 WAV 字节流拼接为一个 WAV 文件。

    Args:
        wav_chunks: WAV 文件的字节列表（均需相同采样格式）
        silence_ms: 块之间插入的静音时长（毫秒），0 表示无静音

    Returns:
        拼接后的 WAV 字节流
    """
    if not wav_chunks:
        return b""
    if len(wav_chunks) == 1:
        return wav_chunks[0]

    # 解析第一个 chunk 的 WAV 头获取格式参数
    header = wav_chunks[0][:44]
    sample_rate = struct.unpack_from("<I", header, 24)[0]
    block_align = struct.unpack_from("<H", header, 32)[0]

    # 提取所有 chunk 的 PCM 数据（跳过 44 字节 WAV 头）
    pcm_parts: list[bytes] = []
    silence_bytes = b""

    if silence_ms > 0:
        silence_samples = int(sample_rate * silence_ms / 1000)
        silence_bytes = b"\x00" * (silence_samples * block_align)

    for i, chunk in enumerate(wav_chunks):
        if len(chunk) <= 44:
            continue
        pcm_parts.append(chunk[44:])
        if silence_bytes and i < len(wav_chunks) - 1:
            pcm_parts.append(silence_bytes)

    combined_pcm = b"".join(pcm_parts)

    # 构建新 WAV 文件
    data_size = len(combined_pcm)
    file_size = 36 + data_size

    new_header = bytearray(header)
    struct.pack_into("<I", new_header, 4, file_size)  # ChunkSize
    struct.pack_into("<I", new_header, 40, data_size)  # Subchunk2Size

    return bytes(new_header) + combined_pcm


def concatenate_mp3(mp3_chunks: list[bytes]) -> bytes:
    """拼接多个 MP3 字节流（MP3 帧独立，可直接拼接）。"""
    return b"".join(mp3_chunks)


def get_wav_duration(wav_path: Path) -> float | None:
    """从 WAV 文件头读取时长（秒）。文件不存在或格式异常返回 None。"""
    try:
        with open(wav_path, "rb") as f:
            header = f.read(44)
            if len(header) < 44:
                return None
            sample_rate = struct.unpack_from("<I", header, 24)[0]
            data_size = struct.unpack_from("<I", header, 40)[0]
            bits_per_sample = struct.unpack_from("<H", header, 34)[0]
            num_channels = struct.unpack_from("<H", header, 22)[0]
            byte_rate = sample_rate * num_channels * bits_per_sample // 8
            if byte_rate <= 0:
                return None
            return data_size / byte_rate
    except Exception:
        return None


def estimate_tts_duration(text: str) -> float:
    """估算文本 TTS 合成的预期时长（秒）。

    中文 TTS 典型语速约 3~5 字/秒，取保守估计 3 字/秒。
    """
    char_count = len(text.strip())
    return char_count / 3.0


class TTSService:
    """TTS 服务统一封装"""

    @staticmethod
    async def synthesize_static(
        text: str,
        style_prompt: str = "",
        voice: str = "冰糖",
    ) -> bytes | None:
        """
        使用 mimo-v2.5-tts 生成静态音频（支持自动分块拼接）

        mimo-v2.5-tts 通过 /v1/chat/completions 端点调用，
        audio 参数指定 voice 和 format，text 放在 assistant message 中，
        style_prompt 放在 user message 中。

        Args:
            text: 要合成的文本内容
            style_prompt: 风格指导（如"以悬疑主持人的口吻朗读"）
            voice: 音色名称（冰糖、茉莉、苏打等）

        Returns:
            WAV 音频字节，失败返回 None
        """
        if not text or not text.strip():
            logger.debug("synthesize_static: empty text, skipping")
            return None

        api_key = settings.MIMO_API_KEY
        if not api_key:
            logger.warning("MIMO_API_KEY not configured, skipping TTS")
            return None

        base_url = settings.MIMO_API_BASE_URL or "https://api.xiaomimimo.com/v1"

        chunks = split_text_for_tts(text, MIMO_MAX_CHARS)

        if len(chunks) == 0:
            return None

        if len(chunks) == 1:
            return await _mimo_single_call(chunks[0], style_prompt, voice, base_url, api_key)

        # 多块：逐块生成，然后拼接 WAV
        wav_parts: list[bytes] = []
        for i, chunk in enumerate(chunks):
            logger.info(f"synthesize_static: chunk {i + 1}/{len(chunks)} ({len(chunk)} chars)")
            wav = await _mimo_single_call(chunk, style_prompt, voice, base_url, api_key)
            if wav is None:
                logger.error(f"synthesize_static: chunk {i + 1}/{len(chunks)} failed")
                return None
            wav_parts.append(wav)

        return concatenate_wav(wav_parts, silence_ms=300)

    @staticmethod
    async def synthesize_on_demand(text: str, voice_id: str) -> bytes | None:
        """
        使用 step-tts-mini HTTP API 生成单条音频（支持自动分块拼接）

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

        chunks = split_text_for_tts(text, STEP_MAX_CHARS)

        if len(chunks) == 0:
            return None

        if len(chunks) == 1:
            return await _step_single_call(chunks[0], voice_id, base_url, api_key)

        # 多块：逐块生成，然后拼接 MP3
        mp3_parts: list[bytes] = []
        for i, chunk in enumerate(chunks):
            mp3 = await _step_single_call(chunk, voice_id, base_url, api_key)
            if mp3 is None:
                logger.error(f"synthesize_on_demand: chunk {i + 1}/{len(chunks)} failed")
                return None
            mp3_parts.append(mp3)

        return concatenate_mp3(mp3_parts)

    @staticmethod
    def get_static_audio_path(script_id: str, audio_type: str, identifier: str) -> Path:
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
    def get_static_audio_url(script_id: str, audio_type: str, identifier: str) -> str:
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
        voice: str = "冰糖",
    ) -> str | None:
        """
        生成静态音频并保存到文件

        Args:
            text: 要合成的文本
            style_prompt: 风格指导
            script_id: 剧本 ID
            audio_type: "character_scripts" 或 "system_messages"
            identifier: 角色 ID 或消息 key
            voice: 音色名称（冰糖、茉莉、苏打等）

        Returns:
            音频文件 URL，失败返回 None
        """
        file_path = TTSService.get_static_audio_path(script_id, audio_type, identifier)

        # 幂等：已存在且大小合理、时长正常则跳过
        if file_path.exists() and file_path.stat().st_size > 1000:
            actual_duration = get_wav_duration(file_path)
            expected_duration = estimate_tts_duration(text)
            max_duration = expected_duration * 4
            if (
                actual_duration is not None
                and actual_duration > max_duration
                and actual_duration > 30
            ):
                logger.warning(
                    f"Existing audio has abnormal duration {actual_duration:.1f}s "
                    f"(expected ~{expected_duration:.1f}s). Regenerating: {file_path}"
                )
                file_path.unlink(missing_ok=True)
            else:
                logger.info(f"Audio already exists: {file_path}")
                return TTSService.get_static_audio_url(script_id, audio_type, identifier)

        audio_data = await TTSService.synthesize_static(text, style_prompt, voice=voice)
        if audio_data:
            file_path.write_bytes(audio_data)
            logger.info(f"Saved audio: {file_path} ({len(audio_data)} bytes)")

            # Validate audio duration — reject abnormally long files (model hallucination)
            actual_duration = get_wav_duration(file_path)
            if actual_duration is not None:
                expected_duration = estimate_tts_duration(text)
                max_duration = expected_duration * 4  # generous upper bound
                if actual_duration > max_duration and actual_duration > 30:
                    logger.warning(
                        f"Audio duration abnormal: {actual_duration:.1f}s "
                        f"(expected ~{expected_duration:.1f}s, max {max_duration:.1f}s). "
                        f"Deleting corrupt file: {file_path}"
                    )
                    file_path.unlink(missing_ok=True)
                    return None

            return TTSService.get_static_audio_url(script_id, audio_type, identifier)

        return None


# === 内部调用函数 ===


async def _mimo_single_call(
    text: str, style_prompt: str, voice: str, base_url: str, api_key: str
) -> bytes | None:
    """单次 mimo-v2.5-tts API 调用"""
    messages = []
    if style_prompt:
        messages.append({"role": "user", "content": style_prompt})
    else:
        messages.append({"role": "user", "content": "请自然地朗读以下内容，语速适中，语气自然。"})
    messages.append({"role": "assistant", "content": text})

    # 长文本生成耗时更久，按字符数动态调整超时
    timeout = max(60, min(300, len(text) // 5))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "mimo-v2.5-tts",
                    "messages": messages,
                    "audio": {
                        "format": "wav",
                        "voice": voice,
                    },
                },
            )
            response.raise_for_status()

            data = response.json()
            import base64 as _b64

            choices = data.get("choices", [])
            if not choices:
                logger.warning("mimo-v2.5-tts: no choices in response")
                return None

            message = choices[0].get("message", {})
            audio_obj = message.get("audio")

            if isinstance(audio_obj, dict) and "data" in audio_obj:
                return _b64.b64decode(audio_obj["data"])
            elif isinstance(audio_obj, str):
                return _b64.b64decode(audio_obj)
            else:
                logger.warning(f"Unexpected mimo-v2.5-tts audio field: {type(audio_obj)}")
                return None

    except httpx.HTTPStatusError as e:
        logger.error(f"MiMo TTS HTTP error: {e.response.status_code} - {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"MiMo TTS error: {e}")
        return None


async def _step_single_call(text: str, voice_id: str, base_url: str, api_key: str) -> bytes | None:
    """单次 step-tts-mini HTTP API 调用"""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
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
        logger.error(f"StepFun TTS HTTP error: {e.response.status_code} - {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"StepFun TTS error: {e}")
        return None
