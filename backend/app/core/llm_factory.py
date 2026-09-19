"""
LLM Factory - LangChain模型初始化统一管理

当前接入的提供商:
- deepseek: DeepSeek (深度求索) — 使用 ChatDeepSeek
- stepfun: Step (阶跃星辰) — 使用 ChatOpenAI
- alibaba: 千问 (阿里巴巴) — 使用 ChatOpenAI
- bytedance: 豆包 (字节跳动) — 使用 ChatOpenAI
- mimo: 小米 MiMo — 使用 ChatOpenAI
- hunyuan: 腾讯混元 — 使用 ChatOpenAI
- zhipuai: 智谱 GLM — 使用 ChatOpenAI

规则:
- deepseek 提供商统一使用 ChatDeepSeek
- 其他提供商统一使用 ChatOpenAI（兼容 OpenAI 协议）
- 思考策略由调用场景和提供商能力决定；Agent 并不普遍要求关闭思考。
  游戏角色发言的策略在 game_model_paths 中维护。
"""

import logging
from typing import cast

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.core.config import settings
from app.core.model_registry import MODEL_BY_ID, get_model_spec

logger = logging.getLogger(__name__)

# 支持的模型类型
SupportedModel = str

# 模型 -> 提供商 映射
MODEL_PROVIDER_MAP: dict[str, str] = {
    model_id: spec.provider for model_id, spec in MODEL_BY_ID.items()
}


def create_llm(
    model: SupportedModel = "deepseek-flash",
    temperature: float = 0.8,
    api_key: str | None = None,
    timeout: int | None = None,
    max_retries: int | None = None,
    disable_thinking: bool = False,
) -> BaseChatModel:
    """统一的 LLM 创建入口。

    - deepseek 提供商: 使用 ChatDeepSeek
    - 其他提供商: 使用 ChatOpenAI（兼容 OpenAI 协议）

    Args:
        disable_thinking: 请求提供商支持的低延迟配置；不代表所有模型都能关闭思考。
            是否启用思考、是否保留工具轮次的推理历史，应按模型和调用场景决定。
    """
    model_lower = model.lower()
    # Existing gateway games can resume after the selectable Step model retires.
    if settings.INFERENCE_BACKEND == "tokendance" and model_lower == "step-3.5-flash":
        model_lower = "deepseek-flash"
    spec = get_model_spec(model_lower)
    model_lower = spec.id
    if not settings.is_model_enabled(model_lower):
        raise ValueError(f"模型 {spec.name} 暂停服务，请选择其他模型")
    provider = spec.provider

    if settings.INFERENCE_BACKEND == "tokendance":
        from app.core.inference import (
            gateway_async_client,
            gateway_client,
            gateway_model,
            gateway_url,
        )
        from app.core.reasoning_chat import ReasoningChatOpenAI

        extra = None
        if spec.reasoning_effort:
            extra = {"reasoning_effort": spec.reasoning_effort}
            if provider == "deepseek":
                extra["thinking"] = {"type": "enabled"}
        elif disable_thinking:
            if provider == "deepseek":
                extra = {"thinking": {"type": "disabled"}}
            elif spec.disable_thinking_extra == "qwen":
                extra = {"enable_thinking": False}
            elif spec.disable_thinking_extra == "glm_low":
                extra = {"reasoning_effort": "low"}
            elif spec.disable_thinking_extra in {"ling", "doubao"}:
                extra = {"thinking": {"type": "disabled"}}
        return ReasoningChatOpenAI(
            model=gateway_model(model_lower),
            api_key=SecretStr("scoped-at-dispatch"),
            base_url=gateway_url("v1"),
            temperature=None if provider == "moonshot" else temperature,
            timeout=timeout or 90,
            # SDK retries wrap recovery errors as network failures. Agent retry
            # middleware owns the bounded transport retry and preserves recovery.
            max_retries=0,
            extra_body=extra,
            # K3 low reserves 8192 reasoning tokens at some gateway endpoints.
            max_tokens=(12288 if provider == "moonshot" else 8192)
            if spec.tier == "frontier"
            else None,
            http_client=gateway_client(
                timeout=timeout or 90, deepseek_fallback=provider == "deepseek"
            ),
            http_async_client=gateway_async_client(
                timeout=timeout or 90, deepseek_fallback=provider == "deepseek"
            ),
            stream_usage=True,
        )

    resolved_key = api_key or settings.get_api_key(provider)
    if not resolved_key:
        raise ValueError(f"未配置 {provider} 的 API Key")

    base_url = settings.get_base_url(provider)
    if not base_url:
        raise ValueError(f"未配置 {provider} 的 API Base URL")

    if provider == "deepseek":
        return _create_deepseek(
            model_lower,
            resolved_key,
            base_url,
            temperature,
            timeout,
            max_retries,
            disable_thinking,
        )

    return _create_openai_compatible(
        model_lower,
        resolved_key,
        base_url,
        temperature,
        timeout,
        max_retries,
        extra_body=(
            {"enable_thinking": False}
            if disable_thinking and spec.disable_thinking_extra == "qwen"
            # GLM-5.3-Flash rejects thinking.type=disabled. Its supported low
            # effort avoids the default long reasoning pass in latency-sensitive paths.
            else {"reasoning_effort": "low"}
            if disable_thinking and spec.disable_thinking_extra == "glm_low"
            else {"thinking": {"type": "disabled"}}
            if disable_thinking and spec.disable_thinking_extra == "doubao"
            else None
        ),
    )


def _create_deepseek(
    model: str,
    api_key: str,
    base_url: str,
    temperature: float,
    timeout: int | None,
    max_retries: int | None,
    disable_thinking: bool,
) -> BaseChatModel:
    """使用 ChatDeepSeek 创建 DeepSeek 模型"""
    try:
        from langchain_deepseek import ChatDeepSeek
    except ImportError:
        logger.warning("langchain-deepseek not installed, falling back to ChatOpenAI")
        return _create_openai_compatible(
            model,
            api_key,
            base_url,
            temperature,
            timeout,
            max_retries,
        )

    kwargs: dict = dict(
        model=model,
        api_key=api_key,
        api_base=base_url,
        temperature=temperature,
    )
    if disable_thinking:
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    if timeout is not None:
        kwargs["timeout"] = timeout
    if max_retries is not None:
        kwargs["max_retries"] = max_retries

    return ChatDeepSeek(**kwargs)


def _create_openai_compatible(
    model: str,
    api_key: str,
    base_url: str,
    temperature: float,
    timeout: int | None,
    max_retries: int | None,
    extra_body: dict | None = None,
) -> BaseChatModel:
    """使用 ChatOpenAI 创建兼容 OpenAI 协议的模型"""
    kwargs: dict = dict(
        model=model,
        api_key=SecretStr(api_key),
        base_url=base_url,
        temperature=temperature,
    )
    if timeout is not None:
        kwargs["timeout"] = timeout
    if max_retries is not None:
        kwargs["max_retries"] = max_retries
    if extra_body:
        kwargs["extra_body"] = extra_body

    if model == "qwen3.8-flash":
        from app.core.reasoning_chat import ReasoningChatOpenAI

        # Direct Qwen calls need the same non-visible tool reasoning history as the gateway.
        return ReasoningChatOpenAI(**kwargs)
    return ChatOpenAI(**kwargs)  # type: ignore[arg-type]


def create_chat_model_for_agent(
    model: str = "deepseek-flash",
) -> BaseChatModel:
    """创建用于 Agent（如创作小助手）的聊天模型。

    创作小助手保持现有低延迟策略；角色发言使用独立的场景策略。
    """
    return create_llm(model=model, temperature=0.7, disable_thinking=True)  # type: ignore[arg-type]


def create_summary_llm() -> BaseChatModel:
    """Create the summary model, falling back to the configured primary model."""
    if settings.INFERENCE_BACKEND == "tokendance":
        return create_llm(
            model="qwen3.8-flash",
            temperature=0.3,
            timeout=90,
            max_retries=2,
            disable_thinking=True,
        )
    api_key = settings.get_api_key("stepfun")
    base_url = settings.get_base_url("stepfun")
    if not api_key or not base_url:
        return create_llm(
            model=cast(SupportedModel, settings.get_llm_model_name().lower()),
            temperature=0.3,
            timeout=90,
            max_retries=2,
            disable_thinking=True,
        )

    return ChatOpenAI(
        model="step-3.5-flash",
        api_key=SecretStr(api_key),
        base_url=base_url,
        temperature=0.3,
        timeout=90,
        max_retries=2,
        max_tokens=100000,  # type: ignore[arg-type]
    )
