"""Provider capability discovery without exposing credentials."""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.model_registry import MODEL_SPECS, public_model_spec


def _feature(enabled: bool, enabled_reason: str, disabled_reason: str) -> dict[str, Any]:
    return {"enabled": enabled, "reason": enabled_reason if enabled else disabled_reason}


def get_capabilities() -> dict[str, Any]:
    models = []
    for spec in MODEL_SPECS:
        has_key = bool(settings.get_api_key(spec.provider))
        if not has_key:
            reason = f"未配置 {spec.provider} API Key"
        else:
            reason = "已配置"
        models.append(
            {
                **public_model_spec(spec),
                "model": spec.id,
                "configured": has_key,
                "reason": reason,
            }
        )

    rag = bool(settings.ZHIPUAI_API_KEY)
    image = bool(settings.DOUBAO_API_KEY)
    static_tts = bool(settings.MIMO_API_KEY)
    streaming_tts = bool(settings.STEPFUN_API_KEY)

    return {
        "mode": "local-first-single-user-single-process",
        "models": models,
        "features": {
            "rag": _feature(
                rag, "智谱 Embedding 已配置", "未配置 ZHIPUAI_API_KEY；使用角色完整个人剧本上下文"
            ),
            "image": _feature(image, "豆包图片生成已配置", "未配置 DOUBAO_API_KEY"),
            "static_tts": _feature(static_tts, "MiMo 静态语音已配置", "未配置 MIMO_API_KEY"),
            "streaming_tts": _feature(
                streaming_tts, "StepFun 流式语音已配置", "未配置 STEPFUN_API_KEY"
            ),
        },
    }
