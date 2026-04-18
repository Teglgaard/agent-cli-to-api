#!/usr/bin/env bash
# One-shot Codex against this repo's LiteLLM bridge: ensure bridge is up, then run codex.
# If http://127.0.0.1:${LITELLM_BRIDGE_PORT:-4000}/health/liveliness is already OK, skips starting.
#
# Usage:
#   ./scripts/litellm-bridge/codex-local.sh
#   ./scripts/litellm-bridge/codex-local.sh resume <session-id>
#   ./scripts/litellm-bridge/codex-local.sh ~/my/repo -- model composer-2-fast
#
# Logs when this script starts the bridge: ${LITELLM_BRIDGE_LOG:-/tmp/litellm-bridge.log}
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PORT="${LITELLM_BRIDGE_PORT:-4000}"
HEALTH="http://127.0.0.1:${PORT}/health/liveliness"
LOG="${LITELLM_BRIDGE_LOG:-/tmp/litellm-bridge.log}"

if ! curl -sf "$HEALTH" >/dev/null 2>&1; then
  echo "LiteLLM not up; starting bridge in background → $LOG" >&2
  nohup "$REPO_ROOT/scripts/litellm-bridge/start-bridge.sh" >>"$LOG" 2>&1 &
  disown 2>/dev/null || true
  for _ in $(seq 1 90); do
    if curl -sf "$HEALTH" >/dev/null 2>&1; then
      echo "Bridge ready at $HEALTH" >&2
      break
    fi
    sleep 1
  done
fi

if ! curl -sf "$HEALTH" >/dev/null 2>&1; then
  echo "Bridge still not reachable at $HEALTH. Last lines of $LOG:" >&2
  tail -n 30 "$LOG" 2>/dev/null || true
  exit 1
fi

# shellcheck source=/dev/null
source "$SCRIPT_DIR/env-for-codex.sh"

if [[ $# -gt 0 && -d "$1" ]]; then
  cd "$1"
  shift
fi

if [[ $# -eq 0 ]]; then
  exec codex --model composer-2-fast
fi
exec codex "$@"
