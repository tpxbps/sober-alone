"""Shared game inference paths used by both role agents and lightweight health probes."""

from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelRetryMiddleware,
    SummarizationMiddleware,
    ToolRetryMiddleware,
)
from langchain.messages import AIMessageChunk

from app.agents.reaction import REACTION_MODEL_TIMEOUT_SECONDS, SpeechReactionPayload
from app.agents.state import GameAgentState
from app.agents.tools import get_tools
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
    return create_llm(
        model=model.lower(),
        api_key=api_key,
        temperature=0.8 if purpose == "speech" else 0.5,
        timeout=timeout
        if timeout is not None
        else (90 if purpose == "speech" else REACTION_MODEL_TIMEOUT_SECONDS),
        max_retries=max_retries if max_retries is not None else (2 if purpose == "speech" else 1),
        disable_thinking=True,
    )


def bind_reaction_output(model, model_id: str):
    return model.with_structured_output(
        SpeechReactionPayload, method=get_model_spec(model_id).reaction_output_method
    )


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
            ModelRetryMiddleware(max_retries=3, backoff_factor=2.0, initial_delay=1.0),
            ToolRetryMiddleware(max_retries=3, backoff_factor=2.0, initial_delay=1.0),
            *middleware,
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
