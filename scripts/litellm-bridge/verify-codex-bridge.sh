#!/usr/bin/env bash
# Smoke-test LiteLLM + agent-cli-to-api for Codex `wire_api = "responses"` streaming.
# Run from any cwd; requires bridge already up (start-bridge.sh).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${LITELLM_BRIDGE_PORT:-4000}"
HEALTH="http://127.0.0.1:${PORT}/health/liveliness"

echo "==> Health: $HEALTH"
curl -sf "$HEALTH" >/dev/null
echo "    OK (HTTP 200)"

# shellcheck source=/dev/null
source "$SCRIPT_DIR/env-for-codex.sh"

if [[ -z "${LITELLM_API_KEY:-}" && -z "${OPENAI_API_KEY:-}" ]]; then
  echo "WARN: LITELLM_API_KEY / OPENAI_API_KEY empty — LiteLLM may return 401 (empty Codex chat)." >&2
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

echo "==> POST /v1/responses (stream) via LiteLLM"
AUTH="${LITELLM_API_KEY:-${OPENAI_API_KEY:-}}"
code="$(
  curl -sS -o "$TMP" -w "%{http_code}" --max-time 60 \
    -X POST "http://127.0.0.1:${PORT}/v1/responses" \
    -H "Authorization: Bearer ${AUTH}" \
    -H "Content-Type: application/json" \
    -d '{"model":"composer-2-fast","stream":true,"input":"Reply with exactly the word: ok"}'
)"

if [[ "$code" != "200" ]]; then
  echo "    FAIL HTTP $code" >&2
  head -c 800 "$TMP" >&2 || true
  exit 1
fi

if ! grep -q "response.output_text.delta" "$TMP"; then
  echo "    FAIL: no response.output_text.delta in SSE body" >&2
  head -c 1200 "$TMP" >&2 || true
  exit 1
fi

if ! grep -q "data: \\[DONE\\]" "$TMP"; then
  echo "    FAIL: stream missing [DONE]" >&2
  head -c 1200 "$TMP" >&2 || true
  exit 1
fi

echo "    OK — saw assistant deltas and [DONE]"
echo "==> Sample (first 600 bytes):"
head -c 600 "$TMP" | sed 's/^/    /' || true
echo ""
echo "All checks passed."
