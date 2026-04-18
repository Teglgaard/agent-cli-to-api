"""Tests for chat-completions SSE -> Responses SSE translation."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from codex_gateway.responses_stream_shim import translate_chat_completion_sse_to_responses_sse


async def _chunks(lines: list[str]) -> AsyncIterator[bytes]:
    for line in lines:
        yield line.encode("utf-8")


async def _run() -> None:
    sse = [
        'data: {"id":"chatcmpl-x","object":"chat.completion.chunk","created":1,"model":"composer-2-fast",'
        '"choices":[{"index":0,"delta":{"content":"Hi"},"finish_reason":null}]}\n\n',
        'data: {"id":"chatcmpl-x","object":"chat.completion.chunk","created":1,"model":"composer-2-fast",'
        '"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":2,"total_tokens":3}}\n\n',
        "data: [DONE]\n\n",
    ]
    out: list[bytes] = []
    async for chunk in translate_chat_completion_sse_to_responses_sse(_chunks(sse), model="composer-2-fast"):
        out.append(chunk)
    text = b"".join(out).decode("utf-8")
    assert "response.created" in text
    assert "response.in_progress" in text
    assert "response.output_item.added" in text
    assert "response.output_text.delta" in text
    assert '"content_index": 0' in text
    assert '"model": "composer-2-fast"' in text
    assert "response.completed" in text
    assert "[DONE]" in text
    payloads = []
    for block in text.split("data: "):
        line = block.split("\n")[0].strip()
        if not line or line == "[DONE]":
            continue
        payloads.append(json.loads(line))
    types = [x.get("type") for x in payloads if isinstance(x, dict)]
    assert "response.completed" in types
    completed = [x for x in payloads if x.get("type") == "response.completed"][0]
    u = completed["response"]["usage"]
    assert u["input_tokens"] == 1
    assert u["output_tokens"] == 2


def test_translates_stream_includes_completed() -> None:
    asyncio.run(_run())


async def _chunks_str(lines: list[str]) -> AsyncIterator[str]:
    """Mimic Starlette yielding str from body_iterator."""
    for line in lines:
        yield line


def test_accepts_string_chunks_from_iterator() -> None:
    sse = [
        (
            'data: {"id":"chatcmpl-x","object":"chat.completion.chunk","created":1,"model":"m",'
            '"choices":[{"index":0,"delta":{"content":"x"},"finish_reason":"stop"}]}\n\n'
        ),
        "data: [DONE]\n\n",
    ]

    async def run() -> None:
        out: list[bytes] = []
        async for chunk in translate_chat_completion_sse_to_responses_sse(_chunks_str(sse), model="m"):
            out.append(chunk)
        text = b"".join(out).decode("utf-8")
        assert "response.completed" in text

    asyncio.run(run())
