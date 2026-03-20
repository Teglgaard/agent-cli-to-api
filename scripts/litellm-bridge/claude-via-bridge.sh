#!/usr/bin/env bash
# Run Claude Code against a local LiteLLM bridge (must already be running).
# Usage:
#   ./scripts/litellm-bridge/claude-via-bridge.sh
#   ./scripts/litellm-bridge/claude-via-bridge.sh ~/Krown-Development/krown-swift
#   ./scripts/litellm-bridge/claude-via-bridge.sh . -- some claude args
#
# Optional zsh alias:
#   alias claude-bridge='~/Krown-Development/agent-cli-to-api/scripts/litellm-bridge/claude-via-bridge.sh'
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PORT="${LITELLM_BRIDGE_PORT:-4000}"
HEALTH="http://127.0.0.1:${PORT}/health/liveliness"

if ! curl -sf "$HEALTH" >/dev/null 2>&1; then
  echo "LiteLLM bridge not reachable at $HEALTH" >&2
  echo "Start it in another terminal:" >&2
  echo "  $REPO_ROOT/scripts/litellm-bridge/start-bridge.sh" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "$SCRIPT_DIR/env-for-claude.sh"

if [[ $# -gt 0 && -d "$1" ]]; then
  cd "$1"
  shift
fi

exec claude "$@"
