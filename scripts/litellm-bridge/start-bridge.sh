#!/usr/bin/env bash
# Start agent-cli-to-api + LiteLLM (default: gateway :11435, LiteLLM :4000).
# Usage:
#   ./scripts/litellm-bridge/start-bridge.sh
#   ./scripts/litellm-bridge/start-bridge.sh --litellm-port 4001
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

exec "$PY" scripts/litellm-bridge/run_bridge.py "$@"
