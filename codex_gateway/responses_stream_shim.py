"""
Translate OpenAI Chat Completions SSE (chat.completion.chunk + [DONE]) into
Responses API-style SSE events so Codex / LiteLLM clients receive
response.output_text.delta and response.completed.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any


def _chunk_to_text(chunk: str | bytes | memoryview) -> str:
    """Starlette's body_iterator may yield str or bytes depending on version / inner generator."""
    if isinstance(chunk, str):
        return chunk
    if isinstance(chunk, memoryview):
        return chunk.tobytes().decode("utf-8", errors="replace")
    return bytes(chunk).decode("utf-8", errors="replace")


def _delta_text_from_chunk(obj: dict[str, Any]) -> str:
    choices = obj.get("choices") or []
    if not choices or not isinstance(choices, list):
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    delta = first.get("delta") if isinstance(first, dict) else {}
    if not isinstance(delta, dict):
        return ""
    c = delta.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts: list[str] = []
        for p in c:
            if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str):
                parts.append(p["text"])
        return "".join(parts)
    return ""


def _usage_to_response_shape(u: dict[str, Any]) -> dict[str, Any]:
    pt = int(u.get("prompt_tokens") or u.get("input_tokens") or 0)
    ct = int(u.get("completion_tokens") or u.get("output_tokens") or 0)
    tot = u.get("total_tokens")
    return {
        "input_tokens": pt,
        "output_tokens": ct,
        "total_tokens": int(tot) if tot is not None else pt + ct,
    }




def _response_in_progress(resp_id: str, created_ts: int, model_out: str) -> dict[str, Any]:
    """Fields required so LiteLLM parses response.created into ResponsesAPIResponse (not raw dict)."""
    return {
        "id": resp_id,
        "object": "response",
        "created_at": created_ts,
        "model": model_out,
        "status": "in_progress",
        "output": [],
    }


def _response_completed(
    resp_id: str,
    created_ts: int,
    model_out: str,
    msg_id: str,
    assembled: str,
    last_usage: dict[str, Any] | None,
) -> dict[str, Any]:
    """Full response object for response.completed — must include `output` or LiteLLM falls back to
    model_construct() and leaves `response` as a dict, breaking logging (usage as attribute).
    """
    usage = _usage_to_response_shape(last_usage or {})
    text = assembled or ""
    return {
        "id": resp_id,
        "object": "response",
        "created_at": created_ts,
        "model": model_out,
        "status": "completed",
        "output": [
            {
                "type": "message",
                "id": msg_id,
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
        "usage": usage,
    }

def _sse_line(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


def _with_model(model_out: str, payload: dict[str, Any]) -> dict[str, Any]:
    """LiteLLM and some clients attach top-level ``model`` on every Responses SSE event."""
    out = dict(payload)
    out.setdefault("model", model_out)
    return out


async def translate_chat_completion_sse_to_responses_sse(
    body: AsyncIterator[str | bytes],
    *,
    model: str | None,
) -> AsyncIterator[bytes]:
    line_buf = ""
    seq = 0
    resp_id = f"resp_{uuid.uuid4().hex}"
    msg_id = f"msg_{uuid.uuid4().hex}"
    created_ts = int(time.time())
    assembled = ""
    model_out = (model or "").strip() or "unknown"
    last_usage: dict[str, Any] | None = None
    sent_created = False
    sent_lifecycle_preamble = False
    completed_emitted = False
    saw_done = False

    async def emit_lifecycle_after_created() -> AsyncIterator[bytes]:
        """Match LiteLLM/OpenAI ordering: in_progress + output_item.added before first text delta."""
        nonlocal seq, sent_lifecycle_preamble
        if sent_lifecycle_preamble:
            return
        sent_lifecycle_preamble = True
        seq += 1
        yield _sse_line(
            _with_model(
                model_out,
                {
                    "type": "response.in_progress",
                    "sequence_number": seq,
                    "response": _response_in_progress(resp_id, created_ts, model_out),
                },
            )
        )
        seq += 1
        yield _sse_line(
            _with_model(
                model_out,
                {
                    "type": "response.output_item.added",
                    "sequence_number": seq,
                    "output_index": 0,
                    "item": {
                        "id": msg_id,
                        "type": "message",
                        "role": "assistant",
                        "status": "in_progress",
                        "content": [],
                    },
                },
            )
        )

    async def emit_tail() -> AsyncIterator[bytes]:
        nonlocal completed_emitted, seq, sent_created
        if completed_emitted:
            return
        completed_emitted = True
        if not sent_created:
            sent_created = True
            yield _sse_line(
                _with_model(
                    model_out,
                    {
                        "type": "response.created",
                        "sequence_number": 0,
                        "response": _response_in_progress(resp_id, created_ts, model_out),
                    },
                )
            )
        async for b in emit_lifecycle_after_created():
            yield b
        seq += 1
        if assembled:
            yield _sse_line(
                _with_model(
                    model_out,
                    {
                        "type": "response.output_text.done",
                        "output_index": 0,
                        "content_index": 0,
                        "item_id": msg_id,
                        "sequence_number": seq,
                        "text": assembled,
                    },
                )
            )
        seq += 1
        yield _sse_line(
            _with_model(
                model_out,
                {
                    "type": "response.completed",
                    "sequence_number": seq,
                    "response": _response_completed(
                        resp_id, created_ts, model_out, msg_id, assembled, last_usage
                    ),
                },
            )
        )
        yield b"data: [DONE]\n\n"

    async for raw in body:
        line_buf += _chunk_to_text(raw)
        while "\n" in line_buf:
            line, line_buf = line_buf.split("\n", 1)
            line = line.rstrip("\r")
            if not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if not data:
                continue
            if data == "[DONE]":
                saw_done = True
                async for b in emit_tail():
                    yield b
                return
            try:
                obj = json.loads(data)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            if obj.get("object") != "chat.completion.chunk":
                continue
            if isinstance(obj.get("model"), str) and obj["model"].strip():
                model_out = obj["model"].strip()
            if not sent_created:
                sent_created = True
                yield _sse_line(
                    _with_model(
                        model_out,
                        {
                            "type": "response.created",
                            "sequence_number": 0,
                            "response": _response_in_progress(resp_id, created_ts, model_out),
                        },
                    )
                )
            async for b in emit_lifecycle_after_created():
                yield b
            txt = _delta_text_from_chunk(obj)
            if txt:
                seq += 1
                assembled += txt
                yield _sse_line(
                    _with_model(
                        model_out,
                        {
                            "type": "response.output_text.delta",
                            "delta": txt,
                            "output_index": 0,
                            "content_index": 0,
                            "item_id": msg_id,
                            "sequence_number": seq,
                        },
                    )
                )
            u = obj.get("usage")
            if isinstance(u, dict):
                last_usage = u
            choices = obj.get("choices") or []
            finish_reason = None
            if choices and isinstance(choices[0], dict):
                finish_reason = choices[0].get("finish_reason")
            if finish_reason:
                async for b in emit_tail():
                    yield b
                return

    if not saw_done and not completed_emitted:
        async for b in emit_tail():
            yield b
