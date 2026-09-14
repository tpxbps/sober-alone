"""
Image Generation Service — doubao-seedream-4-0
用于生成剧本封面图和角色头像
"""

import logging
from pathlib import Path

from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

# 图片存储目录
IMAGE_ROOT = settings.image_dir / "scripts"


def _get_doubao_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=settings.DOUBAO_API_BASE_URL,
        api_key=settings.DOUBAO_API_KEY,
    )


ATMOSPHERE = (
    "整体视觉氛围：偏暗冷色调，营造神秘悬疑感，光线昏暗朦胧，凸显迷茫与未知意味，电影级画面质感。"
)


async def generate_cover_image(
    script_id: str,
    story_synopsis: str,
    title: str = "",
    force: bool = False,
) -> str | None:
    """
    生成剧本封面图片 (1280x768)

    Returns:
        图片 URL（相对路径），失败返回 None
    """
    # The same landscape image is center-cropped into a narrow arched portal.
    # Keep its title and identifying subject inside the narrowest desktop crop.
    title_instruction = (
        f'[标题文字] 只添加剧本标题"{title}"，使用克制、清晰的艺术字体。'
        "标题水平居中，位于画面高度的24%至36%之间；"
        "完整标题的总宽度不超过画面宽度的26%，总高度不超过画面高度的12%。"
        "长标题可均衡分成两行，仍须遵守整体宽高限制；"
        "禁止放大铺满画面、贴边、超宽书法飞白或延伸装饰。\n"
        if title.strip()
        else "[标题文字] 本图不添加任何文字。\n"
    )
    prompt = (
        "生成一张剧本杀游戏的横向剧本封面预览图，画面宽高比5:3。\n"
        f"[背景描述] {story_synopsis[:300]}\n"
        "[构图与裁切] 此图同时用于横向卡片和竖向拱门封面，拱门会从中心裁掉大量左右画面。"
        "将最能识别故事的主要建筑、关键物体或人物主体集中在横向中央30%的范围内"
        "（画面x=35%至65%），主体重点位于高度38%至78%之间；"
        "中心构图要自然，有前中后景的纵深和视觉引导，避免主体拥挤或细节堆砌。"
        "左右两侧用可裁切的环境、雾气、暗部和延展纹理补全宽幅画面，"
        "不在左右边缘放置关键人物、线索或视觉主体。"
        "顶部留出拱形裁切余量，顶部18%不放文字和不可缺失的细节；"
        "确保仅保留画面中央约三分之一时，标题完整、主要场景仍然可辨。\n"
        f"{title_instruction}"
        "[注意] 画面以场景氛围为主，不画真实门框、边框、拼贴、UI或排版安全线；"
        "除指定标题外，严禁出现任何其他文字、水印或字母。\n"
        f"[视觉氛围] {ATMOSPHERE}"
    )

    save_dir = IMAGE_ROOT / script_id
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / "cover.png"

    if not force and save_path.exists() and save_path.stat().st_size > 0:
        return f"/images/scripts/{script_id}/cover.png"

    result = await _generate_image(prompt, save_path, "1280x768")
    if result:
        return f"/images/scripts/{script_id}/cover.png"
    return None


async def generate_character_avatar(
    script_id: str,
    character_id: str,
    name: str,
    appearance: str = "",
    gender: str = "",
    force: bool = False,
) -> str | None:
    """
    生成角色头像 (1024x1024)

    Returns:
        头像 URL（相对路径），失败返回 None
    """
    _ = gender  # reserved for future prompt customization
    prompt = (
        f"生成一张剧本杀游戏角色的人物半身像，人物相关描述为：\n"
        f"{appearance}\n"
        f"[注意] 人物头部需要位于画面中心的位置，图片应该聚焦人物本身，不要出现多余的文字等其他信息。\n"
        f"[视觉氛围] {ATMOSPHERE}"
    )

    save_dir = IMAGE_ROOT / script_id / "avatars"
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / f"{character_id}.png"

    if not force and save_path.exists() and save_path.stat().st_size > 0:
        return f"/images/scripts/{script_id}/avatars/{character_id}.png"

    result = await _generate_image(prompt, save_path, "1024x1024")
    if result:
        return f"/images/scripts/{script_id}/avatars/{character_id}.png"
    return None


async def _generate_image(
    prompt: str,
    save_path: Path,
    size: str = "1024x1024",
) -> bool:
    """
    调用 doubao-seedream-4-0 API 生成图片并下载保存

    Returns:
        是否成功
    """
    if not settings.DOUBAO_API_KEY:
        logger.warning("DOUBAO_API_KEY not configured, skipping image generation")
        return False

    try:
        import httpx

        client = _get_doubao_client()
        response = await client.images.generate(
            model="doubao-seedream-4-0-250828",
            prompt=prompt,
            size=size,  # type: ignore[arg-type]
            response_format="url",
            extra_body={"watermark": True},
        )

        if not response.data:
            logger.error("No data in doubao response")
            return False

        image_url = response.data[0].url
        if not image_url:
            logger.error("No image URL in doubao response")
            return False

        # Download and save
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            img_response = await http_client.get(image_url, timeout=30.0)
            img_response.raise_for_status()
            temp_path = save_path.with_suffix(f"{save_path.suffix}.tmp")
            temp_path.write_bytes(img_response.content)
            temp_path.replace(save_path)

        logger.info(f"Image saved: {save_path} ({save_path.stat().st_size} bytes)")
        return True

    except Exception as e:
        logger.error(f"Image generation error: {e}", exc_info=True)
        return False
