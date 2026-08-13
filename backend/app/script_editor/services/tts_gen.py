"""
TTS Generation Service — 为剧本生成语音资源
使用 mimo-v2.5-tts，支持冰糖/茉莉/苏打音色
所有任务并行执行
"""

import asyncio
import logging
import re
from collections.abc import Callable, Coroutine

from app.services.tts_service import TTSService

logger = logging.getLogger(__name__)

# 系统消息音色
SYSTEM_VOICE = "冰糖"
SYSTEM_STYLE = "以悬疑主持人的口吻朗读，语气紧张引人入胜"

# 角色音色映射
CHARACTER_VOICES = {
    "女": ("茉莉", "以角色的口吻，自然地叙述自己的故事背景，情感沉浸"),
    "女性": ("茉莉", "以角色的口吻，自然地叙述自己的故事背景，情感沉浸"),
    "female": ("茉莉", "以角色的口吻，自然地叙述自己的故事背景，情感沉浸"),
}

DEFAULT_VOICE = "苏打"
DEFAULT_STYLE = "以角色的口吻，自然地叙述自己的故事背景，情感沉浸"


def _get_char_voice_and_style(gender: str) -> tuple[str, str]:
    g = (gender or "").strip()
    return CHARACTER_VOICES.get(g, (DEFAULT_VOICE, DEFAULT_STYLE))


def preprocess_tts_text(text: str) -> str:
    """将 Markdown 文本转为适合 TTS 朗读的纯文本。

    - 去除标题标记（#）
    - 去除加粗/斜体标记（** *）
    - 去除链接，只保留显示文字
    - 去除图片标记
    - 去除代码块和行内代码
    - 去除引用标记（>）
    - 去除分隔线（---）
    - 去除列表标记（- * 1.）
    - 压缩连续空白行
    """
    if not text:
        return ""
    # 代码块
    text = re.sub(r"```[\s\S]*?```", "", text)
    # 行内代码
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # 图片
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", "", text)
    # 链接 → 只保留文字
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    # 标题（# 开头）
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # 加粗/斜体
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)
    # 分隔线
    text = re.sub(r"^-{3,}$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\*{3,}$", "", text, flags=re.MULTILINE)
    # 引用
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
    # 有序列表
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)
    # 无序列表
    text = re.sub(r"^[-*+]\s+", "", text, flags=re.MULTILINE)
    # 清理残留的 Markdown 标记
    text = re.sub(r"[#`>|]", "", text)
    # 压缩空白
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def get_system_style_for_stage(stage_type: str, child_index: int = 0) -> str:
    """根据阶段类型返回对应的 TTS 风格提示词。"""
    if stage_type == "initial":
        return SYSTEM_STYLE
    elif stage_type == "advancement":
        return SYSTEM_STYLE if child_index == 0 else "以中性的方式朗读系统消息"
    elif stage_type == "vote":
        return "以庄重的口吻朗读"
    elif stage_type == "review":
        return "以揭秘的口吻朗读，语气逐渐加重"
    return SYSTEM_STYLE


async def generate_single_system_audio(
    script_id: str,
    identifier: str,
    text: str,
    stage_type: str = "initial",
    child_index: int = 0,
) -> str | None:
    """重新生成单条系统消息音频（供 retry 使用）。"""
    clean_text = preprocess_tts_text(text)
    if not clean_text:
        return None
    style = get_system_style_for_stage(stage_type, child_index)
    url = await TTSService.generate_and_save_static(
        text=clean_text,
        style_prompt=style,
        script_id=script_id,
        audio_type="system_messages",
        identifier=identifier,
        voice=SYSTEM_VOICE,
    )
    if url:
        return url
    raise RuntimeError(f"TTS retry failed for system message '{identifier}'")


async def generate_single_char_audio(
    script_id: str,
    name: str,
    char_id: str,
    script_text: str,
    gender: str = "",
) -> str | None:
    """重新生成单个角色个人剧本音频（供 retry 使用）。"""
    clean_text = preprocess_tts_text(script_text)
    if not clean_text:
        return None
    voice, style = _get_char_voice_and_style(gender)
    url = await TTSService.generate_and_save_static(
        text=clean_text,
        style_prompt=f"{style}。以角色'{name}'的口吻叙述。",
        script_id=script_id,
        audio_type="character_scripts",
        identifier=char_id,
        voice=voice,
    )
    if url:
        return url
    raise RuntimeError(f"TTS retry failed for character '{name}'")


async def generate_script_tts(
    script_id: str,
    character_scripts: dict[str, str],
    characters: list[dict],
    game_full_process: list[dict],
    task_callback: Callable | None = None,
) -> dict:
    """
    为新剧本生成所有 TTS 音频（全量并行）

    Args:
        script_id: 剧本ID
        character_scripts: {角色名: 个人剧本文本}
        characters: 角色列表（含 character_id, gender）
        game_full_process: 游戏流程数据
        task_callback: 可选的进度回调 (task_id, status)

    Returns:
        生成的音频 URL 映射
    """
    results = {"character_scripts": {}, "system_messages": {}}

    # 构建角色名 -> {character_id, gender} 映射
    name_to_info = {
        c.get("name"): {
            "character_id": c.get("character_id", ""),
            "gender": c.get("gender", ""),
        }
        for c in characters
    }

    # 收集所有任务
    tasks: list[tuple[str, Coroutine]] = []

    # 1. 系统消息任务
    for i, stage in enumerate(game_full_process):
        stage_type = stage.get("type", "")

        if stage_type == "initial":
            notice = stage.get("system_notice", "")
            if notice:
                task_id = f"tts_sys_{i}"
                tasks.append(
                    (
                        task_id,
                        _generate_system_audio(
                            script_id,
                            f"stage_{i}",
                            notice,
                            SYSTEM_STYLE,
                            SYSTEM_VOICE,
                            results,
                        ),
                    )
                )

        elif stage_type == "advancement":
            children = stage.get("children", [])
            for j, child in enumerate(children):
                notice = child.get("system_notice", "")
                if notice:
                    task_id = f"tts_sys_{i}_{j}"
                    style = get_system_style_for_stage("advancement", j)
                    tasks.append(
                        (
                            task_id,
                            _generate_system_audio(
                                script_id,
                                f"stage_{i}_child_{j}",
                                notice,
                                style,
                                SYSTEM_VOICE,
                                results,
                            ),
                        )
                    )

        elif stage_type == "vote":
            children = stage.get("children", [])
            for j, child in enumerate(children):
                notice = child.get("system_notice", "")
                if notice:
                    task_id = f"tts_sys_{i}_{j}"
                    tasks.append(
                        (
                            task_id,
                            _generate_system_audio(
                                script_id,
                                f"stage_{i}_child_{j}",
                                notice,
                                "以庄重的口吻朗读",
                                SYSTEM_VOICE,
                                results,
                            ),
                        )
                    )

        elif stage_type == "review":
            notice = stage.get("system_notice", "")
            if notice:
                task_id = f"tts_sys_{i}"
                tasks.append(
                    (
                        task_id,
                        _generate_system_audio(
                            script_id,
                            f"stage_{i}",
                            notice,
                            "以揭秘的口吻朗读，语气逐渐加重",
                            SYSTEM_VOICE,
                            results,
                        ),
                    )
                )

    # 2. 角色个人剧本任务
    for name, script_text in character_scripts.items():
        info = name_to_info.get(name, {})
        char_id = info.get("character_id", "")
        gender = info.get("gender", "")
        if not char_id or not script_text:
            continue

        tts_char_task_id = f"tts_{char_id}"
        tasks.append(
            (
                tts_char_task_id,
                _generate_char_audio(
                    script_id,
                    name,
                    char_id,
                    script_text,
                    voice=None,
                    style=None,
                    gender=gender,
                    results=results,
                ),
            )
        )

    # 3. 全量并行执行（带错开延迟，避免 API 限频）
    async def _run_with_callback(task_id: str, coro, delay: float = 0):
        if task_callback:
            task_callback(task_id, "running")
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            await coro
            if task_callback:
                task_callback(task_id, "complete")
        except Exception:
            if task_callback:
                task_callback(task_id, "failed")

    await asyncio.gather(
        *[_run_with_callback(tid, coro, delay=i * 0.2) for i, (tid, coro) in enumerate(tasks)],
        return_exceptions=True,
    )

    return results


async def _generate_char_audio(
    script_id: str,
    name: str,
    char_id: str,
    script_text: str,
    voice: str | None = None,
    style: str | None = None,
    gender: str = "",
    results: dict | None = None,
):
    """生成单个角色个人剧本音频"""
    clean_text = preprocess_tts_text(script_text)
    if not clean_text:
        raise RuntimeError(f"Empty text after preprocessing for character '{name}'")
    if voice is None or style is None:
        voice, style = _get_char_voice_and_style(gender)
    url = await TTSService.generate_and_save_static(
        text=clean_text,
        style_prompt=f"{style}。以角色'{name}'的口吻叙述。",
        script_id=script_id,
        audio_type="character_scripts",
        identifier=char_id,
        voice=voice,
    )
    if url:
        if results is not None:
            results["character_scripts"][char_id] = url
    else:
        raise RuntimeError(f"TTS generation failed for character '{name}'")


async def _generate_system_audio(
    script_id: str,
    key: str,
    text: str,
    style_prompt: str,
    voice: str,
    results: dict,
):
    """生成单条系统消息音频"""
    clean_text = preprocess_tts_text(text)
    if not clean_text:
        raise RuntimeError(f"Empty text after preprocessing for system message '{key}'")
    url = await TTSService.generate_and_save_static(
        text=clean_text,
        style_prompt=style_prompt,
        script_id=script_id,
        audio_type="system_messages",
        identifier=key,
        voice=voice,
    )
    if url:
        results["system_messages"][key] = url
    else:
        raise RuntimeError(f"TTS generation failed for system message '{key}'")
