from __future__ import annotations

import asyncio
import difflib
import json
import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from .openai_compat import normalize_message_content


def _max_suffix_prefix_overlap(a: str, b: str) -> int:
    """Largest k where a.endswith(b[:k]); used when the CLI repeats a tail then continues."""
    max_k = min(len(a), len(b))
    for k in range(max_k, 0, -1):
        if a.endswith(b[:k]):
            return k
    return 0


@dataclass(frozen=True)
class StreamJsonResult:
    text: str
    usage: dict[str, int] | None


class TextAssembler:
    """
    Some CLIs emit partial deltas and later emit a full final message.
    This helper turns mixed streams into clean deltas (and a final assembled text).
    """

    def __init__(self) -> None:
        self.text = ""

    def feed(self, incoming: str) -> str:
        incoming = incoming or ""
        if not incoming:
            return ""
        if incoming == self.text:
            return ""
        if incoming.startswith(self.text):
            delta = incoming[len(self.text) :]
            self.text = incoming
            return delta
        # Fallback: treat as delta chunk.
        self.text += incoming
        return incoming

    def feed_cursor(
        self,
        incoming: str,
        *,
        dedupe: bool = True,
        dedupe_ratio: float = 0.88,
        dedupe_min_chars: int = 400,
        suffix_overlap_min: int = 48,
    ) -> str:
        """
        Merge cursor-agent stream-json assistant payloads for live SSE without double-printing.

        - Monotonic cumulative snapshots: only the suffix is emitted (same as feed()).
        - Repeated tail + continuation: suffix/prefix overlap (…X already streamed, new chunk XY).
        - Second full snapshot ~identical to the first (plan re-emitted): suppress (SequenceMatcher).
        """
        incoming = incoming or ""
        if not incoming:
            return ""
        if incoming == self.text:
            return ""
        if incoming.startswith(self.text):
            delta = incoming[len(self.text) :]
            self.text = incoming
            return delta
        # Entire incoming already streamed as a suffix (duplicate tail).
        if len(incoming) >= suffix_overlap_min and self.text.endswith(incoming):
            return ""
        k = _max_suffix_prefix_overlap(self.text, incoming)
        if k >= suffix_overlap_min:
            delta = incoming[k:]
            self.text = self.text + delta
            return delta
        if (
            dedupe
            and dedupe_ratio > 0
            and len(incoming) >= dedupe_min_chars
            and len(self.text) >= dedupe_min_chars
        ):
            r = difflib.SequenceMatcher(a=self.text, b=incoming).ratio()
            if r >= dedupe_ratio:
                if len(incoming) > len(self.text):
                    self.text = incoming
                return ""
        self.text += incoming
        return incoming


async def iter_stream_json_events(
    *,
    cmd: list[str],
    stdin_data: str | None = None,
    env: dict[str, str] | None,
    timeout_seconds: int,
    stream_limit: int,
    event_callback: Callable[[dict], None] | None = None,
    stderr_callback: Callable[[str], None] | None = None,
) -> AsyncIterator[dict]:
    """
    Execute a CLI command and stream JSON events from stdout.
    
    Args:
        cmd: Command and arguments (WITHOUT the prompt at the end)
        stdin_data: Data to write to stdin (typically the prompt)
        env: Environment variables
        timeout_seconds: Timeout for reading each line
        stream_limit: Buffer limit for stdout/stderr
        event_callback: Optional callback for each event
        stderr_callback: Optional callback for stderr lines
    
    This version writes data to stdin instead of passing it as a command-line argument,
    avoiding the ARG_MAX limit (typically 128KB on Linux).
    
    Note: This is a FULL REPLACEMENT of the original argv-based approach.
    All prompts are now passed via stdin for unlimited size support.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin_data else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=stream_limit,
        env=env or os.environ.copy(),
    )

    stderr_buf: bytearray = bytearray()
    last_hint: str | None = None

    async def _drain_stderr() -> None:
        if proc.stderr is None:
            return
        text_buf = ""
        while True:
            chunk = await proc.stderr.read(4096)
            if not chunk:
                if stderr_callback and text_buf.strip():
                    for line in text_buf.splitlines():
                        line = line.strip()
                        if line:
                            stderr_callback(line)
                return
            stderr_buf.extend(chunk)
            if len(stderr_buf) > 64_000:
                del stderr_buf[:-64_000]
            if stderr_callback:
                text_buf += chunk.decode(errors="ignore")
                if "\n" in text_buf:
                    lines = text_buf.splitlines(keepends=False)
                    if not text_buf.endswith("\n"):
                        text_buf = lines.pop() if lines else ""
                    else:
                        text_buf = ""
                    for line in lines:
                        line = line.strip()
                        if line:
                            stderr_callback(line)

    # Write stdin data asynchronously
    async def _write_stdin() -> None:
        if proc.stdin is None or stdin_data is None:
            return
        try:
            proc.stdin.write(stdin_data.encode("utf-8"))
            await proc.stdin.drain()
        finally:
            proc.stdin.close()
            await proc.stdin.wait_closed()

    drain_task = asyncio.create_task(_drain_stderr())
    stdin_task = asyncio.create_task(_write_stdin())
    
    try:
        if proc.stdout is None:
            raise RuntimeError("subprocess stdout not available")

        while True:
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout_seconds)
            except (asyncio.TimeoutError, TimeoutError):
                proc.kill()
                await proc.wait()
                raise
            except ValueError as e:
                proc.kill()
                await proc.wait()
                msg = bytes(stderr_buf).decode(errors="ignore").strip()
                hint = (
                    f"subprocess output line exceeded asyncio stream limit ({stream_limit} bytes). "
                    "Increase CODEX_SUBPROCESS_STREAM_LIMIT."
                )
                raise RuntimeError(f"{hint}\n{msg}".strip()) from e

            if not line:
                break
            raw = line.strip()
            if not raw:
                continue
            try:
                evt = json.loads(raw.decode(errors="ignore"))
            except Exception:
                # Some CLIs print non-JSON lines even in stream-json mode.
                continue
            if evt.get("type") == "result" and isinstance(evt.get("result"), str) and evt.get("result"):
                last_hint = str(evt.get("result")).strip() or last_hint
            if evt.get("type") == "error" and isinstance(evt.get("message"), str) and evt.get("message"):
                last_hint = str(evt.get("message")).strip() or last_hint
            if event_callback:
                event_callback(evt)
            yield evt

        # Wait for stdin write to complete
        await stdin_task
        
        rc = await proc.wait()
        await drain_task
        if rc != 0:
            msg = bytes(stderr_buf).decode(errors="ignore").strip()
            raise RuntimeError(msg or last_hint or f"subprocess failed: {rc}")
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        if not drain_task.done():
            drain_task.cancel()
        if not stdin_task.done():
            stdin_task.cancel()


def extract_text_from_content(content: object) -> str:
    return normalize_message_content(content)


def extract_cursor_agent_delta(evt: dict, assembler: TextAssembler) -> str:
    if evt.get("type") != "assistant":
        return ""
    message = evt.get("message") or {}
    if not isinstance(message, dict):
        return ""
    incoming = extract_text_from_content(message.get("content"))
    # Local import avoids circular import at module load.
    from .config import settings

    if not settings.cursor_stream_dedupe:
        return assembler.feed(incoming)
    return assembler.feed_cursor(
        incoming,
        dedupe=True,
        dedupe_ratio=settings.cursor_stream_dedupe_ratio,
        dedupe_min_chars=settings.cursor_stream_dedupe_min_chars,
        suffix_overlap_min=settings.cursor_stream_suffix_overlap_min,
    )


def extract_claude_delta(evt: dict, assembler: TextAssembler) -> str:
    if evt.get("type") != "assistant":
        return ""
    message = evt.get("message") or {}
    if not isinstance(message, dict):
        return ""
    incoming = extract_text_from_content(message.get("content"))
    return assembler.feed(incoming)


def extract_gemini_delta(evt: dict, assembler: TextAssembler) -> str:
    if evt.get("type") != "message":
        return ""
    if evt.get("role") != "assistant":
        return ""
    incoming = extract_text_from_content(evt.get("content"))
    return assembler.feed(incoming)


def extract_usage_from_claude_result(evt: dict) -> dict[str, int] | None:
    if evt.get("type") != "result":
        return None
    usage = evt.get("usage")
    if not isinstance(usage, dict):
        return None
    in_tokens = int(usage.get("input_tokens") or 0)
    out_tokens = int(usage.get("output_tokens") or 0)
    return {
        "prompt_tokens": in_tokens,
        "completion_tokens": out_tokens,
        "total_tokens": in_tokens + out_tokens,
    }


def extract_usage_from_gemini_result(evt: dict) -> dict[str, int] | None:
    if evt.get("type") != "result":
        return None
    stats = evt.get("stats")
    if not isinstance(stats, dict):
        return None
    in_tokens = int(stats.get("input_tokens") or 0)
    out_tokens = int(stats.get("output_tokens") or 0)
    total = int(stats.get("total_tokens") or (in_tokens + out_tokens))
    return {
        "prompt_tokens": in_tokens,
        "completion_tokens": out_tokens,
        "total_tokens": total,
    }


def extract_usage_from_cursor_agent_result(evt: dict) -> dict[str, int] | None:
    """
    Extract token usage from cursor-agent result events.
    
    cursor-agent returns usage in camelCase format:
    {
        "type": "result",
        "result": "...",
        "usage": {
            "inputTokens": 123,
            "outputTokens": 456,
            "cacheReadTokens": 789,
            "cacheWriteTokens": 0
        }
    }
    """
    if evt.get("type") != "result":
        return None
    usage = evt.get("usage")
    if not isinstance(usage, dict):
        return None
    
    in_tokens = int(usage.get("inputTokens") or 0)
    out_tokens = int(usage.get("outputTokens") or 0)
    cache_read = int(usage.get("cacheReadTokens") or 0)
    cache_write = int(usage.get("cacheWriteTokens") or 0)
    
    result = {
        "prompt_tokens": in_tokens,
        "completion_tokens": out_tokens,
        "total_tokens": in_tokens + out_tokens,
    }
    
    # Include cache details if present (cursor-specific fields)
    if cache_read > 0 or cache_write > 0:
        result["prompt_tokens_details"] = {
            "cached_tokens": cache_read,
        }
        if cache_write > 0:
            result["cache_creation_input_tokens"] = cache_write
    
    return result
