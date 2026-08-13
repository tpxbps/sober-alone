"""
LLM helper for script generation workflow
带重试和速率限制处理
"""

import asyncio
import logging

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.core.llm_factory import create_llm

logger = logging.getLogger(__name__)

DEFAULT_SCRIPT_MODEL = "deepseek-v4-flash"

# 重试配置
MAX_RETRIES = 4
BASE_DELAY = 5  # 秒，指数退避基数


def get_script_llm() -> BaseChatModel:
    """获取剧本创作用的 LLM 实例"""
    model_name = getattr(settings, "SCRIPT_EDITOR_MODEL", None) or DEFAULT_SCRIPT_MODEL
    return create_llm(model=model_name, temperature=0.85)


async def call_llm(
    system_prompt: str,
    user_content: str,
    llm: BaseChatModel | None = None,
) -> str:
    """
    调用 LLM 生成内容，带速率限制重试

    Args:
        system_prompt: 系统提示词
        user_content: 用户消息内容
        llm: 可选的 LLM 实例（不传则使用默认）

    Returns:
        生成的文本内容
    """
    if llm is None:
        llm = get_script_llm()

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_content),
    ]

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = await llm.ainvoke(messages)
            content = response.content
            if isinstance(content, list):
                # Extract text from content blocks
                content = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )
            return content
        except Exception as e:
            last_error = e
            error_str = str(e)

            # 检查是否为速率限制错误
            is_rate_limit = (
                "429" in error_str
                or "rate" in error_str.lower()
                or "速率" in error_str
                or "频率" in error_str
            )

            if is_rate_limit and attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY * (2**attempt)  # 5s, 10s, 20s
                logger.warning(
                    f"Rate limit hit (attempt {attempt + 1}/{MAX_RETRIES}), "
                    f"waiting {delay}s before retry..."
                )
                await asyncio.sleep(delay)
            else:
                # 非速率限制错误，或已达到最大重试次数
                if attempt < MAX_RETRIES - 1:
                    delay = BASE_DELAY * (2**attempt)
                    logger.warning(
                        f"LLM call failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}, "
                        f"retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"LLM call failed after {MAX_RETRIES} attempts: {e}")

    raise last_error  # type: ignore
