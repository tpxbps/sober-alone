"""One text model and one bounded structured-call policy for the workshop."""

import asyncio
import json
import logging
import re
from collections.abc import Callable
from weakref import WeakKeyDictionary

from pydantic import ValidationError

from app.core.config import settings
from app.core.inference import raise_for_inference_recovery
from app.core.llm_factory import _create_deepseek, create_llm

MODEL = "deepseek-flash"
_limits: WeakKeyDictionary = WeakKeyDictionary()


def structured_call_limit() -> asyncio.Semaphore:
    """Bound nested conversion fan-out across workflows in this worker."""
    loop = asyncio.get_running_loop()
    if loop not in _limits:
        _limits[loop] = asyncio.Semaphore(4)
    return _limits[loop]


logger = logging.getLogger(__name__)


def create_editor_llm(
    *, model=None, temperature=0.35, timeout=240, max_retries=0, disable_thinking=True
):
    """Ignore legacy model overrides; route only text, never media or embeddings."""
    if not settings.is_model_enabled(MODEL):
        raise ValueError("创作服务暂时不可用，请稍后重试")
    if settings.SCRIPT_EDITOR_INFERENCE_BACKEND == "deepseek_official":
        if not settings.DEEPSEEK_API_KEY:
            raise ValueError("创作服务尚未配置，请稍后重试")
        return _create_deepseek(
            MODEL,
            settings.DEEPSEEK_API_KEY,
            settings.DEEPSEEK_API_BASE_URL or "https://api.deepseek.com",
            temperature,
            timeout,
            0,
            True,
        )
    return create_llm(
        model=MODEL, temperature=temperature, timeout=timeout, max_retries=0, disable_thinking=True
    )


class StructuredOutputTruncated(ValueError):
    pass


def validation_detail(error: Exception) -> str:
    if isinstance(error, ValidationError):
        return "; ".join(
            f"{'.'.join(map(str, item['loc'])) or 'result'}: {item['msg']}"
            for item in error.errors(include_input=False, include_url=False)
        )[:2400]
    return str(error)[:2400]


async def invoke_structured(
    base_llm, schema, system, material, *, validate: Callable | None = None, timeout=240
):
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": material
            if isinstance(material, str)
            else json.dumps(material, ensure_ascii=False),
        },
    ]
    from app.script_editor.outline.runtime import current_runtime
    from app.script_editor.services.execution import observe_model

    runtime = current_runtime.get()
    for attempt in range(2):
        raw = None
        previous = ""
        if runtime:
            runtime.calls += 1
        try:
            async with structured_call_limit():
                response = await asyncio.wait_for(
                    base_llm.with_structured_output(
                        schema,
                        method="function_calling",
                        include_raw=True,
                        tool_choice=schema.__name__,
                    ).ainvoke(messages),
                    timeout=timeout,
                )
            if isinstance(response, dict) and "raw" in response:
                raw = response["raw"]
                metadata = getattr(raw, "response_metadata", {}) or {}
                if metadata.get("finish_reason") == "length":
                    raise StructuredOutputTruncated("生成结果超出单次长度限制，需要拆分当前任务")
                calls = getattr(raw, "tool_calls", []) or []
                invalid = getattr(raw, "invalid_tool_calls", []) or []
                previous = json.dumps(calls or invalid, ensure_ascii=False, default=str)[:12000]
                if response.get("parsing_error"):
                    cause = response["parsing_error"]
                    while cause.__cause__ is not None:
                        cause = cause.__cause__
                    raise ValueError(validation_detail(cause)) from cause
                response = response.get("parsed")
                if response is None:
                    # Some compatible providers return the requested object as text.
                    # Accept only a whole JSON object, with the identical schema checks.
                    content = getattr(raw, "content", "")
                    if isinstance(content, str) and content.strip():
                        text = content.strip()
                        fenced = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", text, re.S)
                        response = schema.model_validate_json(fenced[1] if fenced else text)
                    else:
                        raise ValueError(f"请调用 {schema.__name__} 函数并提供完整参数")
            parsed = schema.model_validate(response)
            if validate:
                validate(parsed)
            if raw is not None:
                observe_model(raw, validation="passed", schema=schema.__name__)
            return parsed
        except Exception as error:
            if raw is not None:
                observe_model(raw, validation=type(error).__name__, schema=schema.__name__)
            raise_for_inference_recovery(error)
            status = getattr(error, "status_code", None)
            if isinstance(error, StructuredOutputTruncated) or status in (400, 401, 403, 404):
                raise
            logger.warning(
                "Structured %s attempt=%s error=%s detail=%s",
                schema.__name__,
                attempt + 1,
                type(error).__name__,
                validation_detail(error) if isinstance(error, ValueError) else "transport",
            )
            if attempt:
                raise ValueError(f"本轮生成未完成：{validation_detail(error)}") from error
            if isinstance(error, (ValueError, TypeError)):
                messages.append(
                    {
                        "role": "user",
                        "content": f"上次参数：{previous}\n具体校验问题：{validation_detail(error)}。"
                        "只修复这些问题，重新调用指定函数返回完整结果。",
                    }
                )
            else:
                await asyncio.sleep(5 if status == 429 else 1)
