# Source before `claude` when LiteLLM bridge runs on this machine (LiteLLM default :4000).
# Easiest: scripts/litellm-bridge/claude-via-bridge.sh (checks health + sources this file).
# Or: source scripts/litellm-bridge/env-for-claude.sh
#
# run_bridge.py starts a second agent-cli-to-api on :11435 with NO CODEX_GATEWAY_TOKEN
# (Composer uses Cursor CLI login). OpenClaw on :11434 with a token is separate.
#
# If you exported AGENT_CLI_API_BASE for experiments, unset it before restarting the bridge:
#   unset AGENT_CLI_API_BASE
# Optional: LITELLM_BRIDGE_PORT=4001 ./claude-via-bridge.sh  (must match run_bridge.py --litellm-port)
export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-http://127.0.0.1:${LITELLM_BRIDGE_PORT:-4000}}"
export ANTHROPIC_API_KEY=""
export ANTHROPIC_CUSTOM_MODEL_OPTION=cursor-composer-2-fast
export ANTHROPIC_CUSTOM_MODEL_OPTION_NAME="Composer 2 Fast (local gateway)"
# If you enable LiteLLM master_key / proxy auth, set the same value here:
# export ANTHROPIC_AUTH_TOKEN="your-litellm-key"
#
# 403 "Invalid token": you pointed LiteLLM at a gateway that enforces CODEX_GATEWAY_TOKEN
# (e.g. --skip-gateway --gateway-port 11434). Either pass the token into that setup, or use the
# default bridge (no skip-gateway) so the child on :11435 has no HTTP Bearer.
