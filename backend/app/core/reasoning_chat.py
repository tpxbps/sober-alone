"""OpenAI-compatible chat with preserved, non-visible reasoning history.

Kimi K3 and other reasoning models require this field across tool turns.
Keep it in message metadata, never concatenate it into player-visible speech.
"""

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_openai import ChatOpenAI


class ReasoningChatOpenAI(ChatOpenAI):
    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(messages, stop=stop, **kwargs)
        for source, target in zip(messages, payload["messages"], strict=True):
            if isinstance(source, AIMessage):
                reasoning = source.additional_kwargs.get("reasoning_content")
                if isinstance(reasoning, str):
                    target["reasoning_content"] = reasoning
        return payload

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)
        body = response if isinstance(response, dict) else response.model_dump()
        for choice, generation in zip(body.get("choices", []), result.generations, strict=True):
            reasoning = choice.get("message", {}).get("reasoning_content")
            if isinstance(reasoning, str):
                generation.message.additional_kwargs["reasoning_content"] = reasoning
        return result

    def _convert_chunk_to_generation_chunk(self, chunk, default_chunk_class, base_generation_info):
        result = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if result and isinstance(result.message, AIMessageChunk) and chunk.get("choices"):
            reasoning = chunk["choices"][0].get("delta", {}).get("reasoning_content")
            if isinstance(reasoning, str):
                result.message.additional_kwargs["reasoning_content"] = reasoning
        return result
