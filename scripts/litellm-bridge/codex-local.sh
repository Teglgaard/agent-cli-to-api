#!/usr/bin/env bash
# Back-compat wrapper: same as codex-via-bridge.sh (does NOT start the bridge).
# Start LiteLLM in another terminal: scripts/litellm-bridge/start-bridge.sh
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/codex-via-bridge.sh" "$@"
