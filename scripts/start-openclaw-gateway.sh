#!/usr/bin/env bash
# Start agent-cli-to-api alone (no LiteLLM) for OpenClaw on :11434 — same Cursor defaults as
# scripts/litellm-bridge/start-bridge.sh (CODEX_PRESET=multi-composer2 → composer-2-fast).
#
# Usage:
#   ./scripts/start-openclaw-gateway.sh
#   ./scripts/start-openclaw-gateway.sh 127.0.0.1 11434
#
# Required: repo venv with `pip install -e .` (or `uv sync`).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

HOST="${1:-127.0.0.1}"
PORT="${2:-11434}"

# Match Mac bridge: Composer 2 Fast for Cursor routes; gpt-5.2 for Codex when clients use codex models.
export CODEX_PRESET="${CODEX_PRESET:-multi-composer2}"

# Ensure cursor-agent resolves (Linux systemd often has no ~/.local/bin on PATH).
if [[ -z "${CURSOR_AGENT_BIN:-}" ]]; then
  if [[ -x "${HOME}/.local/bin/cursor-agent" ]]; then
    export CURSOR_AGENT_BIN="${HOME}/.local/bin/cursor-agent"
  elif command -v cursor-agent >/dev/null 2>&1; then
    export CURSOR_AGENT_BIN="$(command -v cursor-agent)"
  fi
fi

# Writable workspace for the Cursor CLI (avoid permission errors under random CWD).
export CURSOR_AGENT_WORKSPACE="${CURSOR_AGENT_WORKSPACE:-${HOME}/.cursor-agent-workspace}"
mkdir -p "$CURSOR_AGENT_WORKSPACE"

# Token and other keys: use repo `.env` — codex_gateway loads it at import time (no shell `source` needed).

PY="${REPO_ROOT}/venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="${REPO_ROOT}/.venv/bin/python"
fi
if [[ ! -x "$PY" ]]; then
  echo "Missing venv at $REPO_ROOT/venv or $REPO_ROOT/.venv" >&2
  exit 1
fi

GW="${REPO_ROOT}/venv/bin/agent-cli-to-api"
if [[ ! -x "$GW" ]]; then
  GW="${REPO_ROOT}/.venv/bin/agent-cli-to-api"
fi
if [[ ! -x "$GW" ]]; then
  echo "Missing agent-cli-to-api in venv; run: pip install -e ." >&2
  exit 1
fi

exec "$GW" --host "$HOST" --port "$PORT"
