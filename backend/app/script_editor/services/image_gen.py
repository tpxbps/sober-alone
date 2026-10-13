"""
Image Generation Service — doubao-seedream-4-0
用于生成剧本封面图和角色头像
"""

import asyncio
import logging
from pathlib import Path

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.inference import InferenceRecoveryError, raise_for_inference_recovery

logger = logging.getLogger(__name__)


class ImageGenerationRejected(ValueError):
    """The provider explicitly rejected this input; repeating it cannot repair it."""


# 图片存储目录
IMAGE_ROOT = settings.image_dir / "scripts"


def _get_doubao_client() -> AsyncOpenAI:
    if settings.INFERENCE_BACKEND == "tokendance":
        from app.core.inference import gateway_async_client, gateway_url

        return AsyncOpenAI(
            api_key="scoped-at-dispatch",
            base_url=gateway_url("ark/v3"),
            http_client=gateway_async_client(timeout=180),
            max_retries=0,
        )
    return AsyncOpenAI(
        base_url=settings.DOUBAO_API_BASE_URL,
        api_key=settings.DOUBAO_API_KEY,
        max_retries=0,
        timeout=180,
    )


def _build_character_avatar_prompt(
    name: str,
    appearance: str,
    gender: str,
    visual_direction: str,
    age: int | None = None,
    occupation: str = "",
) -> str:
    from app.script_editor.services.portrait_direction import fallback_direction

    identity = "，".join(
        str(value)
        for value in (name, gender, f"{age}岁" if age is not None else "", occupation)
        if value
    )
    direction = visual_direction.strip() or fallback_direction({}).prompt()
    return (
        "生成一张剧本游戏角色的单人人物半身立绘，正方形画面。\n"
        f"[整组共享美术说明]\n{direction}\n"
        "[系列一致性] 本剧本所有人物使用上述同一处背景、同一时段、同一光源、色调和画风。"
        "人物自然融入环境，不因角色身份或性格改变背景与绘制方式。\n"
        f"[当前角色] {identity}\n"
        f"[人物外貌] {appearance or '按公开身份描绘自然可信的外貌。'}\n"
        "[人物辨识] 准确呈现已描述的年龄感、脸型、五官比例、肤色、发际线、发型、体态、"
        "服装剪裁与材质，让差异来自人物本身。表情与姿态自然克制，"
        "不夸张美化或给所有人套用同一张脸，不凭空添加伤痕、可疑道具或身份秘密。"
        "外貌段仅用于人物设计；其中若有背景、灯光或滤镜描述，以上方共享美术说明为准。\n"
        "[构图] 统一平视半身景别，头部与完整五官位于中央区域，头顶留有余量，"
        "肩颈比例自然；允许轻微转身与神态差异，背景适度虚化且仍保留共同环境特征。"
        "面部照明清晰自然，不添加装饰性的明暗切割、图案投影或夸张轮廓光。\n"
        "[画面要求] 只画当前角色，不出现其他人物、文字、水印、边框或拼贴。"
    )


async def generate_cover_image(
    script_id: str,
    story_synopsis: str,
    title: str = "",
    force: bool = False,
    *,
    visual_direction: str = "",
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
    from app.script_editor.services.portrait_direction import fallback_direction

    direction = (
        visual_direction.strip()
        or fallback_direction({"description": story_synopsis[:1000]}).prompt()
    )
    prompt = (
        "生成一张剧本杀游戏的横向剧本封面预览图，画面宽高比5:3。\n"
        f"[背景描述] {story_synopsis[:300]}\n"
        "[构图与裁切] 此图同时用于横向卡片和竖向拱门封面，拱门会从中心裁掉大量左右画面。"
        "将最能识别故事的主要建筑、关键物体或人物主体集中在横向中央30%的范围内"
        "（画面x=35%至65%），主体重点位于高度38%至78%之间；"
        "中心构图要自然，有前中后景的纵深和视觉引导，避免主体拥挤或细节堆砌。"
        "左右两侧用可裁切的环境、场景材质和自然景深补全宽幅画面，"
        "不在左右边缘放置关键人物、线索或视觉主体。"
        "顶部留出拱形裁切余量，顶部18%不放文字和不可缺失的细节；"
        "确保仅保留画面中央约三分之一时，标题完整、主要场景仍然可辨。\n"
        f"{title_instruction}"
        "[注意] 画面以场景氛围为主，不画真实门框、边框、拼贴、UI或排版安全线；"
        "除指定标题外，严禁出现任何其他文字、水印或字母。\n"
        f"[整组共享美术说明]\n{direction}"
    )

    save_dir = IMAGE_ROOT / script_id
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / "cover.png"

    if not force and save_path.exists() and save_path.stat().st_size > 0:
        from app.services.image_variants import prepare_variants

        await asyncio.to_thread(prepare_variants, save_path, "cover")
        return f"/images/scripts/{script_id}/cover.png"

    result = await _generate_image(prompt, save_path, "1280x768")
    if result:
        from app.services.image_variants import prepare_variants

        await asyncio.to_thread(prepare_variants, save_path, "cover")
        return f"/images/scripts/{script_id}/cover.png"
    return None


async def generate_character_avatar(
    script_id: str,
    character_id: str,
    name: str,
    appearance: str = "",
    gender: str = "",
    force: bool = False,
    *,
    visual_direction: str = "",
    age: int | None = None,
    occupation: str = "",
) -> str | None:
    """
    生成角色头像 (1024x1024)

    Returns:
        头像 URL（相对路径），失败返回 None
    """
    prompt = _build_character_avatar_prompt(
        name, appearance, gender, visual_direction, age, occupation
    )

    save_dir = IMAGE_ROOT / script_id / "avatars"
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / f"{character_id}.png"

    if not force and save_path.exists() and save_path.stat().st_size > 0:
        from app.services.image_variants import prepare_variants

        await asyncio.to_thread(prepare_variants, save_path, "avatar")
        return f"/images/scripts/{script_id}/avatars/{character_id}.png"

    result = await _generate_image(prompt, save_path, "1024x1024")
    if result:
        from app.services.image_variants import prepare_variants

        await asyncio.to_thread(prepare_variants, save_path, "avatar")
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
    if not settings.get_api_key("bytedance"):
        logger.warning("DOUBAO_API_KEY not configured, skipping image generation")
        return False

    try:
        import httpx

        client = _get_doubao_client()
        response = await client.images.generate(
            model="seedream-5.0-lite"
            if settings.INFERENCE_BACKEND == "tokendance"
            else "doubao-seedream-4-0-250828",
            prompt=prompt,
            size=("2560x1536" if size == "1280x768" else "2048x2048")
            if settings.INFERENCE_BACKEND == "tokendance"
            else size,  # type: ignore[arg-type]
            response_format="url",
            extra_body={"watermark": False, "output_format": "png"}
            if settings.INFERENCE_BACKEND == "tokendance"
            else {"watermark": True},
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

    except InferenceRecoveryError:
        raise
    except Exception as e:
        raise_for_inference_recovery(e)
        body = getattr(e, "body", None) or {}
        error = body.get("error", body) if isinstance(body, dict) else {}
        code = error.get("code", "") if isinstance(error, dict) else ""
        if code in {"InputTextSensitiveContentDetected", "OutputImageSensitiveContentDetected"}:
            logger.warning("Image request rejected by provider: %s", code)
            raise ImageGenerationRejected("图片服务未接受本次内容，已改用默认展示") from e
        logger.error("Image generation failed: %s", type(e).__name__)
        return False
