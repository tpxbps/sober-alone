"""
LLM Factory - LangChain模型初始化统一管理

支持的提供商:
- zhipuai: GLM 系列 (智谱)
- deepseek: DeepSeek (深度求索)
- stepfun: StepFun (阶跃星辰)
- alibaba: 通义千问 (阿里)
- bytedance: 豆包 (字节跳动)

规则:
- DeepSeek 使用 ChatDeepSeek 构建
- 其他提供商均使用 ChatOpenAI 构建 (兼容 OpenAI 协议)
"""

from typing import Literal, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain.chat_models import init_chat_model
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.core.config import settings

# 支持的模型类型
SupportedModel = Literal[
    "glm-4.7",
    "deepseek-chat",
    "deepseek-reasoner",
    "step-3.5-flash",
    "qwen3.5-flash-2026-02-23",
    "doubao-seed-2-0-mini-260215",
]

# 模型 -> 提供商 映射
MODEL_PROVIDER_MAP: dict[str, str] = {
    "glm-4.7": "zhipuai",
    "deepseek-chat": "deepseek",
    "deepseek-reasoner": "deepseek",
    "step-3.5-flash": "stepfun",
    "qwen3.5-flash-2026-02-23": "alibaba",
    "doubao-seed-2-0-mini-260215": "bytedance",
}


def create_llm(
    model: SupportedModel = "step-3.5-flash",
    temperature: float = 0.8,
    api_key: Optional[str] = None,
) -> BaseChatModel:
    """
    创建LangChain聊天模型

    根据模型名称自动判断提供商，选择对应的构建方式:
    - deepseek 系列 -> ChatDeepSeek
    - 其他 -> ChatOpenAI (使用提供商的 base_url)

    Args:
        model: 模型名称
        temperature: 温度参数
        api_key: API密钥，不提供则从 settings 获取

    Returns:
        BaseChatModel: LangChain聊天模型实例
    """
    model_lower = model.lower()
    provider = MODEL_PROVIDER_MAP.get(model_lower)

    if not provider:
        raise ValueError(
            f"不支持的模型: {model}。"
            f"支持的模型: {', '.join(sorted(MODEL_PROVIDER_MAP.keys()))}"
        )

    # 获取 API Key
    resolved_key = api_key or settings.get_api_key(provider)
    if not resolved_key:
        raise ValueError(f"未配置 {provider} 的 API Key")

    # DeepSeek 使用专用 ChatDeepSeek
    if provider == "deepseek":
        return ChatDeepSeek(
            model=model_lower,
            api_key=SecretStr(resolved_key),
            api_base=settings.get_base_url("deepseek") or "",
            temperature=temperature,
        )

    # 其他提供商使用 ChatOpenAI (均兼容 OpenAI 协议)
    base_url = settings.get_base_url(provider)
    if not base_url:
        raise ValueError(f"未配置 {provider} 的 API Base URL")

    return ChatOpenAI(
        model=model_lower,
        api_key=SecretStr(resolved_key),
        base_url=base_url,
        temperature=temperature,
    )


def create_summary_llm() -> BaseChatModel:
    """
    创建用于摘要的轻量级模型, 默认采用 step-3.5-flash。

    Returns:
        BaseChatModel: 轻量级聊天模型
    """

    return init_chat_model(
        model="step-3.5-flash",
        model_provider="openai",
        temperature=0.3,
        timeout=45,
        max_retries=6,
        max_tokens=100000,
        api_key=settings.get_api_key("stepfun"),
        base_url=settings.get_base_url("stepfun"),
    )
