"""Safe, actionable game errors; never expose provider response bodies."""

import httpx
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError

from app.core.model_registry import get_model_spec

UNKNOWN_MESSAGE = "抱歉！服务发生未知错误，本轮暂时未能完成，请稍后重试。"
CHANGE_MODEL = "为继续游戏，建议返回大厅，重新选择其他可用模型开局。也可以稍后重试本轮。"


def mark_model_error(error: Exception, model: str | None):
    # Keep the original exception type so retry and funding policies are unchanged.
    if not getattr(error, "game_model", None):
        error.game_model = model


def error_chain(error):
    pending, seen = [error], set()
    while pending:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        pending.extend(e for e in (current.__cause__, current.__context__) if e is not None)
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions)


def turn_error_message(error: Exception, *, empty_output=False):
    chain = list(error_chain(error))
    label = "所选模型"
    for current in chain:
        model = getattr(current, "game_model", None)
        if model:
            try:
                label = get_model_spec(model).name + " 模型"
            except (ValueError, KeyError):
                pass
            break
    for current in chain:
        if isinstance(current, APIError):
            body = getattr(current, "body", None)
            if isinstance(body, dict) and isinstance(body.get("error"), dict):
                body = body["error"]
            codes = (
                {str(body.get(k, "")).lower() for k in ("code", "type")}
                if isinstance(body, dict)
                else set()
            )
            if codes & {"context_length_exceeded", "max_context_length_exceeded"}:
                return (
                    "model_context_limit",
                    f"{label}无法处理当前对话长度，本轮暂时无法继续。{CHANGE_MODEL}",
                )
            if codes & {"content_filter", "content_policy_violation", "safety_violation"}:
                return (
                    "model_content_rejected",
                    f"{label}的内容审核未通过，本轮暂时无法继续。可以稍后重试，或返回大厅选择其他模型开局。",
                )
            if codes & {"model_not_found", "model_not_available", "model_decommissioned"}:
                return "model_unavailable", f"{label}目前不可用。{CHANGE_MODEL}"
        if isinstance(current, (APITimeoutError, httpx.TimeoutException, TimeoutError)):
            return (
                "model_timeout",
                f"{label}响应超时，本轮暂时未能完成。可以稍后重试；若持续出现，建议返回大厅选择其他模型开局。",
            )
        if isinstance(current, (APIConnectionError, httpx.TransportError)):
            return (
                "model_connection",
                f"暂时无法连接{label}的服务，本轮暂时未能完成。可以稍后重试；若持续出现，建议返回大厅选择其他模型开局。",
            )
        if isinstance(current, (APIStatusError, httpx.HTTPStatusError)):
            status = getattr(current, "status_code", None) or current.response.status_code
            if status in (408, 504):
                return "model_timeout", f"{label}响应超时，本轮暂时未能完成。{CHANGE_MODEL}"
            if status == 429:
                return (
                    "model_rate_limited",
                    f"{label}当前请求较多，服务暂时限流。请稍后重试；若持续出现，建议返回大厅选择其他模型开局。",
                )
            if status in (401, 403):
                return (
                    "model_access_denied",
                    f"{label}的访问授权未通过，本轮暂时无法继续。请检查模型账户授权，或返回大厅选择其他可用模型开局。",
                )
            if status in (400, 422):
                return (
                    "model_request_rejected",
                    f"{label}的服务未能处理本次请求，本轮暂时无法继续。{CHANGE_MODEL}",
                )
            if status == 404:
                return "model_unavailable", f"{label}的服务暂不可用。{CHANGE_MODEL}"
            if 500 <= status <= 599:
                return (
                    "model_service_error",
                    f"{label}的服务暂时出现异常，本轮暂时无法继续。{CHANGE_MODEL}",
                )
    if empty_output:
        return "model_empty_output", f"{label}未返回有效发言，本轮暂时未能完成。{CHANGE_MODEL}"
    return "execution_failed", UNKNOWN_MESSAGE
