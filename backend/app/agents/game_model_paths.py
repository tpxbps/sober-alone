"""Shared game inference paths used by both role agents and lightweight health probes."""

from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain.messages import AIMessageChunk

from app.agents.reaction import REACTION_MODEL_TIMEOUT_SECONDS, SpeechReactionPayload
from app.agents.stage_policy import StagePolicyMiddleware
from app.agents.state import GameAgentState
from app.agents.tools import get_tools
from app.core.config import settings
from app.core.llm_factory import create_llm
from app.core.model_registry import get_model_spec

SUMMARY_TRIGGER_TOKENS = 200000


def create_game_model(
    model: str,
    purpose: Literal["speech", "reaction"],
    *,
    api_key: str | None = None,
    timeout: int | None = None,
    max_retries: int | None = None,
):
    qwen_speech = purpose == "speech" and get_model_spec(model.lower()).id == "qwen3.8-flash"
    llm = create_llm(
        model=model.lower(),
        api_key=api_key,
        temperature=0.8 if purpose == "speech" else 0.5,
        timeout=timeout
        if timeout is not None
        else (90 if purpose == "speech" else REACTION_MODEL_TIMEOUT_SECONDS),
        # Gameplay supervisors own the entire attempt budget, including retries.
        max_retries=max_retries if max_retries is not None else 0,
        disable_thinking=not qwen_speech,
    )
    if qwen_speech:
        # Keep this policy specific to role speech (including its health probe).
        # Reactions, summaries and creator agents keep their existing settings.
        return llm.model_copy(
            update={"extra_body": {"enable_thinking": True, "reasoning_effort": "low"}}
        )
    return llm


def bind_reaction_output(model, model_id: str, schema=SpeechReactionPayload):
    spec = get_model_spec(model_id)
    if (
        settings.INFERENCE_BACKEND == "tokendance"
        and spec.provider == "deepseek"
        and spec.tier != "frontier"
    ):
        return model.with_structured_output(schema, method="function_calling")
    return model.with_structured_output(schema, method=spec.reaction_output_method)


def build_role_agent(
    model,
    summary_model,
    *,
    system_prompt: str,
    rag_enabled: bool,
    checkpointer: Any,
    middleware: list[Any],
):
    return create_agent(
        model=model,
        tools=get_tools(rag_enabled=rag_enabled),
        middleware=[
            SummarizationMiddleware(
                model=summary_model,
                trigger=("tokens", SUMMARY_TRIGGER_TOKENS),
                keep=("messages", 20),
            ),
            *middleware,
            StagePolicyMiddleware(),
        ],
        checkpointer=checkpointer,
        system_prompt=system_prompt,
        state_schema=GameAgentState,
    )


def visible_speech_text(token: Any) -> list[str]:
    if not isinstance(token, AIMessageChunk) or token.tool_calls or token.tool_call_chunks:
        return []
    if token.content_blocks:
        return [
            block["text"]
            for block in token.content_blocks
            if block.get("type") == "text" and block.get("text")
        ]
    return [token.text] if token.text else []


def visible_role_speech_text(token: Any, metadata: dict[str, Any]) -> list[str]:
    """Expose role-model text, never internal middleware model calls.

    `model` identifies the role invocation, not necessarily its final message:
    tool preambles without tool-call metadata are still streamed unchanged.
    This boundary only controls display; graph state and tools are untouched.
    """
    if metadata.get("langgraph_node") != "model":
        return []
    return visible_speech_text(token)
