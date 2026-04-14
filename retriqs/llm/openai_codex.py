from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx
from openai import AsyncOpenAI

from retriqs.api.openai_codex_auth import (
    OPENAI_CODEX_BASE_URL,
    get_openai_codex_auth_manager,
)
from retriqs.utils import logger

DEFAULT_OPENAI_CODEX_INSTRUCTIONS = (
    "You are Retriqs' document analysis and retrieval assistant. "
    "Follow the user's request and return only the requested output."
)


def _build_responses_input(
    prompt: str,
    history_messages: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for message in history_messages or []:
        role = str(message.get("role") or "user")
        content = str(message.get("content") or "")
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": prompt})
    return messages


def _response_format_to_text_config(response_format: Any) -> dict[str, Any] | None:
    if response_format is None:
        return None

    if isinstance(response_format, dict):
        schema = response_format
    else:
        model_json_schema = getattr(response_format, "model_json_schema", None)
        if not callable(model_json_schema):
            return None
        schema = model_json_schema()

    return {
        "format": {
            "type": "json_schema",
            "name": "retriqs_structured_output",
            "schema": schema,
            "strict": True,
        }
    }


async def openai_codex_complete_if_cache(
    model: str,
    prompt: str,
    system_prompt: str | None = None,
    history_messages: list[dict[str, Any]] | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    stream: bool | None = None,
    timeout: int | None = None,
    **kwargs: Any,
) -> str | AsyncIterator[str]:
    del api_key
    kwargs.pop("hashing_kv", None)
    response_format = kwargs.pop("response_format", None)
    max_output_tokens = kwargs.pop("max_completion_tokens", None) or kwargs.pop(
        "max_tokens", None
    )
    reasoning_effort = kwargs.pop("reasoning_effort", None)

    auth_manager = get_openai_codex_auth_manager()
    access_token = auth_manager.get_access_token()

    client = AsyncOpenAI(
        api_key=access_token,
        base_url=base_url or OPENAI_CODEX_BASE_URL,
        timeout=timeout,
        default_headers={
            "User-Agent": "Retriqs OpenAI Codex OAuth",
            "Content-Type": "application/json",
        },
    )

    request_payload: dict[str, Any] = {
        "model": model,
        "store": False,
        "stream": True,
        "instructions": system_prompt or DEFAULT_OPENAI_CODEX_INSTRUCTIONS,
        "input": _build_responses_input(
            prompt=prompt,
            history_messages=history_messages,
        ),
    }
    text_config = _response_format_to_text_config(response_format)
    if text_config:
        request_payload["text"] = text_config
    if max_output_tokens is not None:
        request_payload["max_output_tokens"] = max_output_tokens
    if reasoning_effort:
        request_payload["reasoning"] = {"effort": reasoning_effort}

    async def _single_result() -> str:
        try:
            stream_response = await client.responses.create(**request_payload)
            chunks: list[str] = []
            async for event in stream_response:
                if getattr(event, "type", None) == "response.output_text.delta":
                    delta = getattr(event, "delta", None)
                    if delta:
                        chunks.append(str(delta))
                elif getattr(event, "type", None) == "response.output_text.done":
                    text = getattr(event, "text", None)
                    if text and not chunks:
                        chunks.append(str(text))
                elif getattr(event, "type", None) == "response.completed":
                    response = getattr(event, "response", None)
                    output_text = getattr(response, "output_text", None)
                    if output_text and not chunks:
                        chunks.append(str(output_text))
            if chunks:
                return "".join(chunks)
            raise RuntimeError("OpenAI Codex returned no text output")
        except httpx.HTTPStatusError as exc:
            logger.error("OpenAI Codex HTTP error: %s", exc)
            raise
        finally:
            await client.close()

    async def _single_result_stream() -> AsyncIterator[str]:
        result = await _single_result()
        yield result

    if stream:
        return _single_result_stream()
    return await _single_result()
