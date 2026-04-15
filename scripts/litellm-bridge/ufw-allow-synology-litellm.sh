#!/usr/bin/env bash
# Open LiteLLM port for the Synology reverse proxy (and optional LAN).
# Run on the VM once:
#   sudo bash scripts/litellm-bridge/ufw-allow-synology-litellm.sh
#
# Env overrides:
#   SYNOLOGY_IP=192.168.0.198 LITELLM_PORT=4000 sudo bash ...

set -euo pipefail

SYNOLOGY_IP="${SYNOLOGY_IP:-192.168.0.198}"
LITELLM_PORT="${LITELLM_PORT:-4000}"
LAN_SUBNET="${LAN_SUBNET:-192.168.0.0/24}"

if [[ "${EUID:-0}" -ne 0 ]]; then
  echo "Run with sudo: sudo bash $0" >&2
  exit 1
fi

command -v ufw >/dev/null || {
  echo "ufw not found" >&2
  exit 1
}

# Idempotent: ufw skips duplicate rules with same spec on recent UFW versions.
ufw allow from "${SYNOLOGY_IP}" to any port "${LITELLM_PORT}" proto tcp comment 'Synology reverse proxy to LiteLLM' 2>/dev/null || \
  ufw allow from "${SYNOLOGY_IP}" to any port "${LITELLM_PORT}" proto tcp

# Optional: full LAN (set ALLOW_LAN=1 if you need direct access from other machines).
if [[ "${ALLOW_LAN:-0}" == "1" ]]; then
  ufw allow from "${LAN_SUBNET}" to any port "${LITELLM_PORT}" proto tcp comment 'LAN access to LiteLLM' 2>/dev/null || \
    ufw allow from "${LAN_SUBNET}" to any port "${LITELLM_PORT}" proto tcp
fi

ufw reload
echo "--- ufw status (numbered) ---"
ufw status numbered
