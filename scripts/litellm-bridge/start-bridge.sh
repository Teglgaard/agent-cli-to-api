#!/usr/bin/env bash
# Start agent-cli-to-api + LiteLLM (default: gateway :11435, LiteLLM :4000).
#
# OpenClaw / Dench: your primary model URL must match this gateway port. The server often uses
# http://127.0.0.1:11434/v1 — if your Mac OpenClaw config still points at :11434 but you start the
# bridge with the default :11435, requests miss the gateway and OpenClaw falls back (e.g. Sonnet).
# Fix: ./scripts/litellm-bridge/start-bridge.sh --gateway-port 11434
#   or: export OPENCLAW_GATEWAY_PORT=11434   # convenience (same as --gateway-port)
# For OpenClaw-only (no LiteLLM), use ./scripts/start-openclaw-gateway.sh instead.
#
# If Composer runs longer than OpenClaw's embedded timeout (often ~120s), raise timeoutSeconds in
# ~/.openclaw-dench/openclaw.json so the primary can finish before failover.
#
# Vision routing: litellm_config.yaml registers vision_route_hook (Composer 2 Fast for text,
# cursor:auto when messages include images). PYTHONPATH must include this directory so LiteLLM
# can import the hook — run_bridge.py sets that for the litellm child; we also export it here
# so the same behavior holds if you run tools from this shell or adjust run_bridge.
#
# Usage:
#   ./scripts/litellm-bridge/start-bridge.sh
#   ./scripts/litellm-bridge/start-bridge.sh --litellm-port 4001
#   ./scripts/litellm-bridge/start-bridge.sh --gateway-port 11434
#
# Optional zsh alias:
#   alias bridge-start='~/Krown-Development/agent-cli-to-api/scripts/litellm-bridge/start-bridge.sh'
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

PY="${REPO_ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "Missing venv: $PY" >&2
  echo "  cd $REPO_ROOT && python3 -m venv .venv && .venv/bin/pip install -e '.[bridge]'" >&2
  exit 1
fi

unset AGENT_CLI_API_BASE
export CODEX_PRESET="${CODEX_PRESET:-multi-composer2}"

# LiteLLM callbacks: import vision_route_hook from this folder (see litellm_config.yaml).
export PYTHONPATH="${SCRIPT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

# Match scripts/start-openclaw-gateway.sh + Linux user systemd so cursor-agent and workspace match
# the Dench box (avoids flaky Composer path and unnecessary OpenClaw failover).
if [[ -z "${CURSOR_AGENT_BIN:-}" ]]; then
  if [[ -x "${HOME}/.local/bin/cursor-agent" ]]; then
    export CURSOR_AGENT_BIN="${HOME}/.local/bin/cursor-agent"
  elif command -v cursor-agent >/dev/null 2>&1; then
    export CURSOR_AGENT_BIN="$(command -v cursor-agent)"
  fi
fi
export CURSOR_AGENT_WORKSPACE="${CURSOR_AGENT_WORKSPACE:-${HOME}/.cursor-agent-workspace}"
mkdir -p "$CURSOR_AGENT_WORKSPACE"

# Avoid "${arr[@]}" when arr is empty: with `set -u`, some Bash versions (e.g. macOS 3.2) treat it as unbound.
if [[ -n "${OPENCLAW_GATEWAY_PORT:-}" ]]; then
  have_gp=0
  for a in "$@"; do
    if [[ "$a" == --gateway-port || "$a" == --gateway-port=* ]]; then
      have_gp=1
      break
    fi
  done
  if [[ "$have_gp" -eq 0 ]]; then
    exec "$PY" scripts/litellm-bridge/run_bridge.py --gateway-port "$OPENCLAW_GATEWAY_PORT" "$@"
  fi
fi
exec "$PY" scripts/litellm-bridge/run_bridge.py "$@"
