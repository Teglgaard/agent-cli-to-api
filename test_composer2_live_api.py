#!/usr/bin/env python3
"""
Live HTTP test: real `agent` / `cursor-agent` behind agent-cli-to-api.

- Starts a short-lived gateway (or uses AGENT_CLI_LIVE_BASE if set).
- POST /v1/chat/completions with model composer-2 (non-streaming).
- Asserts 200 and non-empty assistant content.

Skip: COMPOSER2_LIVE_SKIP=1, or neither agent nor cursor-agent on PATH
(when not using AGENT_CLI_LIVE_BASE).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent


def _auth_headers() -> dict[str, str]:
    """Bearer token if operator uses a gated gateway (local or AGENT_CLI_LIVE_BASE)."""
    t = (os.environ.get("AGENT_CLI_LIVE_TOKEN") or os.environ.get("CODEX_GATEWAY_TOKEN") or "").strip()
    if t:
        return {"Authorization": f"Bearer {t}"}
    return {}


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _find_cursor_cli() -> str | None:
    for name in ("cursor-agent", "agent"):
        p = shutil.which(name)
        if p:
            return p
    return None


async def _wait_health(base: str, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    async with httpx.AsyncClient(timeout=3.0) as client:
        while time.monotonic() < deadline:
            try:
                r = await client.get(f"{base}/healthz")
                if r.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.25)
    raise RuntimeError(f"server not healthy at {base} within {timeout_s}s")


async def _live_chat_completion(base: str) -> httpx.Response:
    prompt = (
        "You are a minimal test harness. Reply with exactly one line: LIVE_API_OK\n"
        "Do not add markdown or explanation."
    )
    payload: dict = {
        "model": "composer-2",
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    # Allow long runs: Cursor CLI + model can take minutes.
    timeout = httpx.Timeout(600.0, connect=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.post(
            f"{base}/v1/chat/completions",
            json=payload,
            headers=_auth_headers(),
        )


async def _read_sse_completion(resp: object) -> str:
    parts: list[str] = []
    async for line in resp.aiter_lines():
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data: "):
            continue
        data = line[6:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        choices = chunk.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        c = delta.get("content")
        if isinstance(c, str) and c:
            parts.append(c)
    return "".join(parts)


async def main() -> int:
    if os.environ.get("COMPOSER2_LIVE_SKIP", "").strip() in ("1", "true", "yes"):
        print("SKIP: COMPOSER2_LIVE_SKIP set")
        return 0

    existing = (os.environ.get("AGENT_CLI_LIVE_BASE") or "").strip().rstrip("/")
    base: str

    if existing:
        base = existing
        print(f"[live] using existing gateway {base}")
    else:
        cli = _find_cursor_cli()
        if not cli:
            print("SKIP: no cursor-agent/agent on PATH (install Cursor CLI or set AGENT_CLI_LIVE_BASE)")
            return 0

        port = _free_port()
        base = f"http://127.0.0.1:{port}"
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            env = os.environ.copy()
            env.pop("CODEX_GATEWAY_TOKEN", None)
            env["CURSOR_AGENT_BIN"] = cli
            env["CURSOR_AGENT_WORKSPACE"] = str(ws)
            env["CODEX_PROVIDER"] = "auto"
            env.setdefault("CODEX_TIMEOUT_SECONDS", "600")

            print(f"[live] cursor CLI: {cli}")
            print(f"[live] starting gateway {base} (workspace={ws})")
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "codex_gateway.server:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=str(REPO_ROOT),
            )
            try:
                await _wait_health(base)
                await _run_cases(base)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            return 0

    await _wait_health(base)
    await _run_cases(base)
    return 0


async def _run_cases(base: str) -> None:
    print("\n[live] POST /v1/chat/completions (stream=false, model=composer-2) …")
    r = await _live_chat_completion(base)
    if r.status_code != 200:
        raise SystemExit(f"non-streaming failed: HTTP {r.status_code}\n{r.text[:2000]}")
    data = r.json()
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    if not str(content).strip():
        raise SystemExit(f"empty content: {data!r}")
    usage = data.get("usage") or {}
    print("[live] non-streaming OK")
    print(f"  content preview: {content[:200]!r}…")
    print(f"  usage: {usage}")

    print("\n[live] POST /v1/chat/completions (stream=true, model=composer-2) …")
    timeout = httpx.Timeout(600.0, connect=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        payload = {
            "model": "composer-2",
            "messages": [
                {
                    "role": "user",
                    "content": "Reply with one word only: STREAM_OK",
                }
            ],
            "stream": True,
        }
        async with client.stream(
            "POST",
            f"{base}/v1/chat/completions",
            json=payload,
            headers=_auth_headers(),
        ) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise SystemExit(
                    f"streaming failed: HTTP {resp.status_code}\n{body[:2000]!r}"
                )
            streamed = await _read_sse_completion(resp)
    if not str(streamed).strip():
        raise SystemExit("streaming produced empty content")
    print("[live] streaming OK")
    print(f"  assembled preview: {streamed[:200]!r}…")


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
