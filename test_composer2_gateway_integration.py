#!/usr/bin/env python3
"""
End-to-end (mocked CLI) proof that HTTP /v1/chat/completions with model `composer-2`
routes through agent-cli-to-api to the Cursor agent subprocess with `--model composer-2`.

Requires: httpx (project dependency). Does not call real Cursor or the network.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _write_mock_cursor_agent(path: Path, expected_model: str) -> None:
    # Mock receives the same argv shape as real cursor-agent (including --model <id>).
    tmpl = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

EXPECTED = {expected_literal}

record = Path(os.environ["COMPOSER2_GATEWAY_TEST_RECORD"])
argv = sys.argv[:]
model = None
if "--model" in argv:
    i = argv.index("--model")
    if i + 1 < len(argv):
        model = argv[i + 1]

record.write_text(
    json.dumps({{"argv": argv, "observed_model_flag": model}}, indent=2),
    encoding="utf-8",
)

if model != EXPECTED:
    print("MOCK_FAIL: expected", repr(EXPECTED), "got", repr(model), file=sys.stderr)
    sys.exit(2)

prompt = sys.stdin.read()
_ = prompt  # stdin consumed like real cursor-agent

for evt in (
    {{"type": "system", "subtype": "init", "model": EXPECTED}},
    {{"type": "assistant", "message": {{"content": "ok-from-gateway"}}}},
    {{
        "type": "result",
        "result": "ok-from-gateway",
        "usage": {{
            "inputTokens": 3,
            "outputTokens": 4,
            "cacheReadTokens": 0,
            "cacheWriteTokens": 0,
        }},
    }},
):
    print(json.dumps(evt), flush=True)
"""
    script = tmpl.format(expected_literal=json.dumps(expected_model))
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


async def _wait_health(base: str, timeout_s: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_s
    async with httpx.AsyncClient(timeout=2.0) as client:
        while time.monotonic() < deadline:
            try:
                r = await client.get(f"{base}/healthz")
                if r.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.2)
    raise RuntimeError(f"server not healthy at {base} within {timeout_s}s")


async def test_chat_completions_routes_composer2_to_cursor_cli_with_model_flag() -> None:
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        mock_bin = tmp_path / "mock-cursor-agent"
        record = tmp_path / "record.json"
        _write_mock_cursor_agent(mock_bin, "composer-2")

        env = os.environ.copy()
        env.pop("CODEX_GATEWAY_TOKEN", None)
        env["CURSOR_AGENT_BIN"] = str(mock_bin)
        env["CURSOR_AGENT_WORKSPACE"] = str(tmp_path)
        env["COMPOSER2_GATEWAY_TEST_RECORD"] = str(record)
        env["CODEX_PROVIDER"] = "auto"

        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "codex_gateway.server:app",
                "--host",
                "127.0.0.1",
                f"--port",
                str(port),
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(Path(__file__).resolve().parent),
        )
        try:
            await _wait_health(base)
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    f"{base}/v1/chat/completions",
                    json={
                        "model": "composer-2",
                        "messages": [{"role": "user", "content": "ping"}],
                        "stream": False,
                    },
                )
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["choices"][0]["message"]["content"] == "ok-from-gateway"
            assert data.get("usage", {}).get("prompt_tokens") == 3
            assert data.get("usage", {}).get("completion_tokens") == 4

            recorded = json.loads(record.read_text(encoding="utf-8"))
            assert recorded["observed_model_flag"] == "composer-2", recorded
            argv = recorded["argv"]
            assert str(mock_bin) == argv[0]
            assert "--model" in argv
            assert argv[argv.index("--model") + 1] == "composer-2"
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def main() -> int:
    asyncio.run(test_chat_completions_routes_composer2_to_cursor_cli_with_model_flag())
    print("OK: composer-2 request reached mock cursor-agent with --model composer-2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
