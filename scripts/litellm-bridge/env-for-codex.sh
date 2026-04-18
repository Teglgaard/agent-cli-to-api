#!/usr/bin/env sh
#
# MUST be SOURCED. For OpenAI Codex CLI (and other OpenAI-compatible clients) against this repo's LiteLLM bridge.
#
#   source /path/to/agent-cli-to-api/scripts/litellm-bridge/env-for-codex.sh
#
# Codex expects the API root to include /v1 (same as OpenAI's public API shape).
# LiteLLM listens on :4000 by default (run_bridge.py / start-bridge.sh).
#
# Optional: LITELLM_BRIDGE_PORT=4001 if you started the bridge with --litellm-port 4001
#
# If the LiteLLM proxy uses master_key auth, this script loads LITELLM_MASTER_KEY from this
# repo's .env when unset, then exports OPENAI_API_KEY, LITELLM_API_KEY (some stacks expect this name),
# and LITELLM_MASTER_KEY so Bearer matches the running bridge.
#
# shellcheck disable=SC2034

REPO_ROOT_ENV_CODEX="${AGENT_CLI_API_HOME:-}"
if [ -z "$REPO_ROOT_ENV_CODEX" ]; then
  if [ -n "${BASH_VERSION:-}" ]; then
    SCRIPT_DIR_ENV_CODEX="$(CDPATH= cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  else
    SCRIPT_DIR_ENV_CODEX="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
  fi
  REPO_ROOT_ENV_CODEX="$(CDPATH= cd -- "$SCRIPT_DIR_ENV_CODEX/../.." && pwd)"
fi

if [ -z "${LITELLM_MASTER_KEY:-}" ] && [ -f "$REPO_ROOT_ENV_CODEX/.env" ]; then
  while IFS= read -r _line || [ -n "$_line" ]; do
    _line="${_line#"${_line%%[![:space:]]*}"}"
    case "$_line" in
    ''|'#'*) continue ;;
    esac
    case "$_line" in
    export\ LITELLM_MASTER_KEY=*) _line="${_line#export }" ;;
    esac
    case "$_line" in
    LITELLM_MASTER_KEY=*)
      _val="${_line#LITELLM_MASTER_KEY=}"
      _val="${_val#\"}"
      _val="${_val%\"}"
      _val="${_val#\'}"
      _val="${_val%\'}"
      export LITELLM_MASTER_KEY="$_val"
      break
      ;;
    esac
  done <"$REPO_ROOT_ENV_CODEX/.env"
fi

export OPENAI_BASE_URL="${OPENAI_BASE_URL:-http://127.0.0.1:${LITELLM_BRIDGE_PORT:-4000}/v1}"
if [ -n "${LITELLM_MASTER_KEY:-}" ]; then
  export OPENAI_API_KEY="${OPENAI_API_KEY:-$LITELLM_MASTER_KEY}"
  export LITELLM_API_KEY="${LITELLM_API_KEY:-$LITELLM_MASTER_KEY}"
else
  export OPENAI_API_KEY="${OPENAI_API_KEY:-}"
fi

# If this file was executed (not sourced), exports are lost when the process exits — Codex then has
# no API key for LiteLLM. Detection: bash BASH_SOURCE vs $0; zsh funcstack
# (non-empty when sourced); POSIX sh/dash $0 is the script path only when executed.
if [ -n "${ZSH_VERSION:-}" ]; then
  if [ -z "${funcstack:-}" ]; then
    printf '%s\n' "ERROR: env-for-codex.sh must be sourced so OPENAI_BASE_URL / API keys apply to codex:" >&2
    printf '%s\n' "  source \"${(%):-%x}\"" >&2
    printf '%s\n' "Running it without 'source' does nothing in your current shell (common cause of empty chat)." >&2
    exit 1
  fi
elif [ -n "${BASH_VERSION:-}" ]; then
  if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    printf '%s\n' "ERROR: env-for-codex.sh must be sourced so OPENAI_BASE_URL / API keys apply to codex:" >&2
    printf '%s\n' "  source \"${BASH_SOURCE[0]}\"" >&2
    printf '%s\n' "Running it without 'source' does nothing in your current shell (common cause of empty chat)." >&2
    exit 1
  fi
else
  case "$0" in
  env-for-codex.sh | */env-for-codex.sh |   */env-for-codex)
    printf '%s\n' "ERROR: env-for-codex.sh must be sourced so OPENAI_BASE_URL / API keys apply to codex:" >&2
    printf '%s\n' "  source \"$0\"" >&2
    printf '%s\n' "Running it without 'source' does nothing in your current shell (common cause of empty chat)." >&2
    exit 1
    ;;
  esac
fi

# LiteLLM master_key auth: Bearer must match LITELLM_MASTER_KEY; we mirror it to OPENAI_API_KEY and LITELLM_API_KEY.
if [ -z "${LITELLM_API_KEY:-}" ] && [ -z "${OPENAI_API_KEY:-}" ]; then
  printf '%s\n' "WARN: env-for-codex: no LITELLM_API_KEY or OPENAI_API_KEY — LiteLLM may return 401 and Codex chat stays empty. Add LITELLM_MASTER_KEY to agent-cli-to-api/.env or export keys." >&2
fi
