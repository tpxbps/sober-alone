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
        if settings.INFERENCE_BACKEND not in spec.backends:
            continue
        enabled = settings.is_model_enabled(spec.id)
        has_key = bool(settings.get_api_key(spec.provider)) and enabled
        if not enabled:
            reason = "模型暂停服务，请选择其他模型"
        elif not has_key:
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

    rag = bool(settings.get_api_key("zhipuai"))
    image = bool(settings.get_api_key("bytedance"))
    static_tts = bool(settings.get_api_key("mimo"))
    streaming_tts = bool(settings.get_api_key("stepfun"))
    gateway = settings.INFERENCE_BACKEND == "tokendance"
    missing_gateway = "未连接可用的 TokenDance 凭据"

    return {
        "mode": "local-first-single-user-single-process",
        "inference_backend": settings.INFERENCE_BACKEND,
        "models": models,
        "features": {
            "rag": _feature(
                rag,
                "Qwen 向量已配置" if gateway else "智谱 Embedding 已配置",
                missing_gateway
                if gateway
                else "未配置 ZHIPUAI_API_KEY；使用角色完整个人剧本上下文",
            ),
            "image": _feature(
                image,
                "Seedream 图片生成已配置",
                missing_gateway if gateway else "未配置 DOUBAO_API_KEY",
            ),
            "static_tts": _feature(
                static_tts,
                "MiMo 静态语音已配置",
                missing_gateway if gateway else "未配置 MIMO_API_KEY",
            ),
            "streaming_tts": _feature(
                streaming_tts,
                "MiniMax 流式语音已配置" if gateway else "StepFun 流式语音已配置",
                missing_gateway if gateway else "未配置 STEPFUN_API_KEY",
            ),
        },
    }
