#!/usr/bin/env python3
"""
Run agent-cli-to-api and LiteLLM together so Claude Code can use Anthropic-compatible URLs
while routing Cursor/Composer models to the OpenAI-compatible gateway.

The bridge starts its own agent-cli-to-api on :11435 by default with **no** CODEX_GATEWAY_TOKEN
(Cursor auth is via the Cursor CLI, not HTTP Bearer). OpenClaw often mounted on :11434 *with* a
token is unchanged — LiteLLM talks to the bridge gateway only.

Usage:
  pip install "litellm[proxy]>=1.55.8" httpx
  # or: pip install -e ".[bridge]"
  export CODEX_PRESET=multi-composer2   # optional
  python scripts/litellm-bridge/run_bridge.py

  # To use an existing gateway instead (e.g. same :11434 as OpenClaw with a token):
  python scripts/litellm-bridge/run_bridge.py --skip-gateway --gateway-port 11434
  # and ensure CODEX_GATEWAY_TOKEN is set for LiteLLM → gateway requests.

Claude Code (example):
  export ANTHROPIC_BASE_URL=http://127.0.0.1:4000
  export ANTHROPIC_AUTH_TOKEN=$LITELLM_PROXY_KEY    # if you set LITELLM_MASTER_KEY below
  export ANTHROPIC_API_KEY=""                         # use token auth per Claude Code docs
  export ANTHROPIC_CUSTOM_MODEL_OPTION=cursor-composer-2-fast
  export ANTHROPIC_CUSTOM_MODEL_OPTION_NAME="Composer 2 Fast (gateway)"
  claude
"""

from __future__ import annotations

import argparse
import os
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = BRIDGE_DIR / "litellm_config.yaml"


def _venv_bin(*parts: str) -> Path:
    return REPO_ROOT.joinpath(".venv", "bin", *parts)


def _find_gateway_executable() -> str | None:
    """Prefer repo .venv (works without `source .venv/bin/activate`)."""
    for candidate in (_venv_bin("agent-cli-to-api"),):
        if candidate.is_file():
            return str(candidate)
    return shutil.which("agent-cli-to-api")


def _find_litellm_executable() -> str | None:
    for candidate in (_venv_bin("litellm"),):
        if candidate.is_file():
            return str(candidate)
    return shutil.which("litellm") or shutil.which("litellm-proxy")


def _install_hint() -> str:
    return (
        f"Install into this repo's venv (once):\n"
        f"  cd {REPO_ROOT}\n"
        f"  python3 -m venv .venv\n"
        f'  .venv/bin/pip install -e ".[bridge]"\n'
        f"Then:\n"
        f"  .venv/bin/python scripts/litellm-bridge/run_bridge.py\n"
        f"Or: source .venv/bin/activate && python scripts/litellm-bridge/run_bridge.py"
    )


def _load_codex_gateway_token_from_dotenv() -> None:
    """If CODEX_GATEWAY_TOKEN is unset, pick it up from repo .env (same as many gateway installs)."""
    if os.environ.get("CODEX_GATEWAY_TOKEN", "").strip():
        return
    path = REPO_ROOT / ".env"
    if not path.is_file():
        return
    key = "CODEX_GATEWAY_TOKEN"
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        k, sep, val = line.partition("=")
        if not sep or k.strip() != key:
            continue
        val = val.strip()
        if val and val[0] in {"'", '"'} and val[-1] == val[0]:
            val = val[1:-1]
        if val:
            os.environ[key] = val
        break


def _gateway_child_env(*, strip_codex_bearer: bool) -> dict[str, str]:
    """Environment for the gateway subprocess. Cursor CLI OAuth/session is separate from HTTP Bearer."""
    out = dict(os.environ)
    if strip_codex_bearer:
        out.pop("CODEX_GATEWAY_TOKEN", None)
    return out


def _wait_http(url: str, timeout_s: float = 60.0, interval_s: float = 0.3) -> None:
    deadline = time.monotonic() + timeout_s
    last_err = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=2.0)
            if r.status_code < 500:
                return
        except Exception as e:
            last_err = e
        time.sleep(interval_s)
    raise RuntimeError(f"Timeout waiting for {url} (last error: {last_err})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Start agent-cli-to-api + LiteLLM bridge")
    parser.add_argument("--gateway-host", default="127.0.0.1")
    parser.add_argument(
        "--gateway-port",
        type=int,
        default=None,
        help="Bridge child defaults to 11435; with --skip-gateway defaults to 11434 (your existing gateway).",
    )
    parser.add_argument("--litellm-port", type=int, default=4000)
    parser.add_argument(
        "--gateway-cmd",
        default="auto",
        help="CLI subcommand for agent-cli-to-api (e.g. auto, cursor-agent, multi-composer2 via env)",
    )
    parser.add_argument("--litellm-config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--skip-gateway",
        action="store_true",
        help="Only start LiteLLM (gateway already running on --gateway-port)",
    )
    parser.add_argument(
        "--inherit-gateway-token",
        action="store_true",
        help="Pass CODEX_GATEWAY_TOKEN into the gateway child (default: strip — HTTP Bearer off for Composer/Cursor)",
    )
    parser.add_argument(
        "--master-key",
        default=os.environ.get("LITELLM_MASTER_KEY", ""),
        help="Optional: set LITELLM_MASTER_KEY in the environment and add general_settings.master_key "
        "to a copied config — the upstream CLI may not support --master_key on all versions.",
    )
    args = parser.parse_args()

    if args.gateway_port is None:
        args.gateway_port = 11434 if args.skip_gateway else 11435

    _load_codex_gateway_token_from_dotenv()

    gateway_bin = None if args.skip_gateway else _find_gateway_executable()
    litellm_bin = _find_litellm_executable()

    if not args.skip_gateway and not gateway_bin:
        print("agent-cli-to-api not found (checked PATH and .venv/bin/).\n", file=sys.stderr)
        print(_install_hint(), file=sys.stderr)
        return 1
    if not litellm_bin:
        print(
            "litellm CLI not found (checked PATH and .venv/bin/).\n"
            + _install_hint(),
            file=sys.stderr,
        )
        return 1

    # LiteLLM hosted_vllm client uses api_base as server origin (it appends /v1/chat/completions).
    # Always set this for LiteLLM's subprocess — a stale AGENT_CLI_API_BASE (e.g. from an old test
    # on port 57777) would break routing if we used setdefault().
    origin = f"http://{args.gateway_host}:{args.gateway_port}"
    os.environ["AGENT_CLI_API_BASE"] = origin
    print(f"[bridge] AGENT_CLI_API_BASE={origin}", flush=True)

    # Dedicated child gateway: no HTTP Bearer; Composer uses Cursor CLI login.
    dedicated_no_bearer = not args.skip_gateway and not args.inherit_gateway_token

    if dedicated_no_bearer:
        os.environ["AGENT_CLI_API_KEY"] = "not-used"
        print(
            "[bridge] LiteLLM → gateway without Bearer auth (default). "
            "Gateway child has no CODEX_GATEWAY_TOKEN; Cursor CLI handles model login.",
            flush=True,
        )
    elif args.skip_gateway:
        gw_tok = os.environ.get("CODEX_GATEWAY_TOKEN", "").strip()
        if gw_tok:
            os.environ["AGENT_CLI_API_KEY"] = gw_tok
            print("[bridge] CODEX_GATEWAY_TOKEN → AGENT_CLI_API_KEY for LiteLLM (skip-gateway mode).", flush=True)
        else:
            os.environ.setdefault("AGENT_CLI_API_KEY", "not-used")
            print(
                "[bridge] skip-gateway: CODEX_GATEWAY_TOKEN not set — using placeholder Bearer.",
                flush=True,
            )
            print(
                f"[bridge] If you get 403 Invalid token on :{args.gateway_port}, set CODEX_GATEWAY_TOKEN for this shell.",
                flush=True,
            )
    else:
        gw_tok = os.environ.get("CODEX_GATEWAY_TOKEN", "").strip()
        if gw_tok:
            os.environ["AGENT_CLI_API_KEY"] = gw_tok
            print("[bridge] inherit-gateway-token: child gateway will enforce CODEX_GATEWAY_TOKEN.", flush=True)
        else:
            os.environ.setdefault("AGENT_CLI_API_KEY", "not-used")
            print(
                "[bridge] inherit-gateway-token set but CODEX_GATEWAY_TOKEN empty — child has no Bearer.",
                flush=True,
            )

    gw_proc: subprocess.Popen[str] | None = None
    if not args.skip_gateway:
        gw_cmd = [
            gateway_bin,
            args.gateway_cmd,
            "--host",
            args.gateway_host,
            "--port",
            str(args.gateway_port),
        ]
        child_env = _gateway_child_env(strip_codex_bearer=dedicated_no_bearer)
        print("[bridge] starting gateway:", " ".join(gw_cmd), flush=True)
        gw_proc = subprocess.Popen(gw_cmd, cwd=str(REPO_ROOT), env=child_env)
        try:
            _wait_http(f"http://{args.gateway_host}:{args.gateway_port}/healthz", timeout_s=90.0)
        except Exception:
            if gw_proc.poll() is not None:
                print("[bridge] gateway exited early; check logs.", file=sys.stderr)
            gw_proc.terminate()
            raise
        print("[bridge] gateway healthy", flush=True)

    if args.master_key:
        os.environ["LITELLM_MASTER_KEY"] = args.master_key

    litellm_argv = [
        litellm_bin,
        "--config",
        str(args.litellm_config),
        "--host",
        "127.0.0.1",
        "--port",
        str(args.litellm_port),
    ]

    print("[bridge] starting LiteLLM:", " ".join(litellm_argv), flush=True)
    ll_proc = subprocess.Popen(litellm_argv, cwd=str(REPO_ROOT))
    try:
        _wait_http(f"http://127.0.0.1:{args.litellm_port}/health/liveliness", timeout_s=90.0)
    except Exception:
        ll_proc.terminate()
        if gw_proc:
            gw_proc.terminate()
        raise
    print("[bridge] LiteLLM up", flush=True)

    print(
        "\n--- Claude Code (example env) ---\n"
        f"export ANTHROPIC_BASE_URL=http://127.0.0.1:{args.litellm_port}\n"
        + (
            f'export ANTHROPIC_AUTH_TOKEN="{args.master_key}"\n'
            if args.master_key
            else "# No LITELLM_MASTER_KEY — omit bearer if proxy is open\n"
        )
        + "export ANTHROPIC_API_KEY=\"\"\n"
        + "export ANTHROPIC_CUSTOM_MODEL_OPTION=cursor-composer-2-fast\n"
        + 'export ANTHROPIC_CUSTOM_MODEL_OPTION_NAME="Composer 2 Fast (local gateway)"\n'
        + "claude\n",
        flush=True,
    )

    def _stop(*_: object) -> None:
        print("\n[bridge] shutting down...", flush=True)
        ll_proc.terminate()
        try:
            ll_proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            ll_proc.kill()
        if gw_proc:
            gw_proc.terminate()
            try:
                gw_proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                gw_proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    rc = ll_proc.wait()
    if gw_proc:
        gw_proc.terminate()
    return int(rc or 0)


if __name__ == "__main__":
    raise SystemExit(main())
