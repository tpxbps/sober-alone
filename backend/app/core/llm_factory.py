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
- DeepSeek 思考模式在多轮场景（agent 工具调用、结构化输出）中会导致
  reasoning_content 回传失败（API 返回 400），因此这些场景必须禁用思考模式。
  传入 disable_thinking=True 即可。
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
        disable_thinking: 是否使用低延迟推理配置（GLM-5.3-Flash 仅支持 low，不能关闭思考）。需要的场景：
            1. agent 工具调用（create_agent）— 思考模式导致多轮 reasoning_content 回传失败
            2. 结构化输出（with_structured_output）— 思考模式与 function_calling 不兼容
    """
    model_lower = model.lower()
    spec = get_model_spec(model_lower)
    model_lower = spec.id
    provider = spec.provider

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

    return ChatOpenAI(**kwargs)  # type: ignore[arg-type]


def create_chat_model_for_agent(
    model: str = "deepseek-flash",
) -> BaseChatModel:
    """创建用于 Agent（如创作小助手）的聊天模型。

    DeepSeek 思考模式在多轮工具调用时会导致 reasoning_content 回传失败，
    因此 agent 场景必须禁用思考模式。
    """
    return create_llm(model=model, temperature=0.7, disable_thinking=True)  # type: ignore[arg-type]


def create_summary_llm() -> BaseChatModel:
    """Create the summary model, falling back to the configured primary model."""
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
