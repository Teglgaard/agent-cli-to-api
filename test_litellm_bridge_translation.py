#!/usr/bin/env python3
"""
End-to-end check: LiteLLM proxy accepts Anthropic /v1/messages and forwards to an
OpenAI-compatible /v1/chat/completions backend (mocked here — no cursor-agent needed).

Install LiteLLM for this test:
  pip install -r scripts/litellm-bridge/requirements-bridge.txt
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent
BRIDGE_CONFIG = REPO_ROOT / "scripts" / "litellm-bridge" / "litellm_config.yaml"


def _pick_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    _, port = s.getsockname()
    s.close()
    return int(port)


class _MockOpenAIHandler(BaseHTTPRequestHandler):
    expected_token = "mock-gateway-token"

    def log_message(self, fmt: str, *args: object) -> None:
        return  # quiet

    def do_POST(self) -> None:  # noqa: N802
        n = int(self.headers.get("Content-Length", "0"))
        _ = self.rfile.read(n) if n else b""
        auth = self.headers.get("Authorization", "")
        if self.expected_token and f"Bearer {self.expected_token}" not in auth:
            self.send_response(401)
            self.end_headers()
            return

        path = self.path.split("?", 1)[0]
        # LiteLLM may call either Chat Completions or Responses on OpenAI-compatible backends.
        if path in ("/v1/chat/completions", "/chat/completions") or path.endswith("/chat/completions"):
            body = {
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "composer-2-fast",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "BRIDGE_OK"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            }
        else:
            self.send_response(404)
            self.end_headers()
            return

        raw = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _wait(url: str, *, timeout_s: float = 90.0) -> None:
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=3.0)
            if r.status_code < 500:
                return
        except Exception as e:
            last = e
        time.sleep(0.25)
    raise RuntimeError(f"timeout {url!r} last_err={last!r}")


def main() -> int:
    litellm_bin = shutil.which("litellm")
    if not litellm_bin and (REPO_ROOT / ".venv" / "bin" / "litellm").is_file():
        litellm_bin = str(REPO_ROOT / ".venv" / "bin" / "litellm")
    if not litellm_bin:
        print("SKIP: litellm not installed. pip install -r scripts/litellm-bridge/requirements-bridge.txt")
        return 0

    if not BRIDGE_CONFIG.is_file():
        print("FAIL: missing", BRIDGE_CONFIG)
        return 1

    mock_port = _pick_port()
    ll_port = _pick_port()

    _MockOpenAIHandler.expected_token = "mock-gateway-token"
    mock = ThreadingHTTPServer(("127.0.0.1", mock_port), _MockOpenAIHandler)
    thread = threading.Thread(target=mock.serve_forever, daemon=True)
    thread.start()

    # hosted_vllm: api_base is origin only (client adds /v1/chat/completions).
    os.environ["AGENT_CLI_API_BASE"] = f"http://127.0.0.1:{mock_port}"
    os.environ["AGENT_CLI_API_KEY"] = "mock-gateway-token"

    cfg_dst = Path(tempfile.mkdtemp()) / "litellm_bridge_test.yaml"
    cfg_dst.write_text(BRIDGE_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")

    proc = subprocess.Popen(
        [
            litellm_bin,
            "--config",
            str(cfg_dst),
            "--host",
            "127.0.0.1",
            "--port",
            str(ll_port),
        ],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait(f"http://127.0.0.1:{ll_port}/health/liveliness", timeout_s=120.0)
        # Anthropic Messages API via LiteLLM proxy
        payload = {
            "model": "cursor-composer-2-fast",
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "ping"}],
        }
        r = httpx.post(
            f"http://127.0.0.1:{ll_port}/v1/messages",
            headers={
                "content-type": "application/json",
                "anthropic-version": "2023-06-01",
                "x-api-key": "sk-ant-mock-litellm-test",
            },
            json=payload,
            timeout=120.0,
        )
        if r.status_code != 200:
            print("FAIL: status", r.status_code, r.text[:2000])
            return 1
        data = r.json()
        if "error" in data and data["error"]:
            print("FAIL: proxy error", json.dumps(data, indent=2)[:2500])
            return 1
        blocks = data.get("content") or []
        texts = [
            str(b.get("text", ""))
            for b in blocks
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        joined = "".join(texts)
        if "BRIDGE_OK" not in joined:
            print("FAIL: unexpected body", json.dumps(data, indent=2)[:3000])
            return 1
        print("OK: Anthropic /v1/messages -> OpenAI backend -> BRIDGE_OK")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=12)
        except subprocess.TimeoutExpired:
            proc.kill()
        mock.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
