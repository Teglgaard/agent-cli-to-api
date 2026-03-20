# LiteLLM bridge: Claude Code → Composer (agent-cli-to-api)

Claude Code speaks the **Anthropic** HTTP API. **agent-cli-to-api** exposes **OpenAI-compatible** endpoints used by Cursor / Composer. This folder runs **LiteLLM** as a small proxy that translates Anthropic requests into OpenAI-style calls to your local gateway.

## Prerequisites

- Repo root: install the project and bridge extras:

  ```bash
  cd /path/to/agent-cli-to-api
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -e ".[bridge]"
  ```

- **Cursor CLI** (`cursor-agent` or `agent` on `PATH`) logged in for Composer models.

## Super quick run (two terminals)

**Terminal 1 — bridge (leave running)**

```bash
/path/to/agent-cli-to-api/scripts/litellm-bridge/start-bridge.sh
```

This script:

- Uses the repo `.venv` Python
- `unset AGENT_CLI_API_BASE` (avoids stale ports from old experiments)
- Sets `CODEX_PRESET=multi-composer2` by default
- Starts **agent-cli-to-api** on **`:11435`** (no HTTP Bearer on that child by default)
- Starts **LiteLLM** on **`:4000`**

Extra arguments are passed through to `run_bridge.py` (e.g. `--litellm-port 4001`).

**Terminal 2 — Claude Code**

```bash
/path/to/agent-cli-to-api/scripts/litellm-bridge/claude-via-bridge.sh ~/path/to/your-project
```

Or from your project directory (omit the path):

```bash
/path/to/agent-cli-to-api/scripts/litellm-bridge/claude-via-bridge.sh
```

This script:

- Checks LiteLLM at `http://127.0.0.1:${LITELLM_BRIDGE_PORT:-4000}/health/liveliness`
- Sources `env-for-claude.sh` (sets `ANTHROPIC_BASE_URL`, custom model option, clears `ANTHROPIC_API_KEY`)
- Optionally `cd`’s into the first argument if it is a directory
- Runs `claude` with any remaining args

In Claude, use **`/model`** and pick **Composer 2 Fast (local gateway)** (`cursor-composer-2-fast`).

## Optional: short shell aliases

Add to `~/.zshrc` (adjust `AGENT_CLI_API_HOME`):

```bash
export AGENT_CLI_API_HOME="$HOME/Krown-Development/agent-cli-to-api"
alias bridge-start='$AGENT_CLI_API_HOME/scripts/litellm-bridge/start-bridge.sh'
alias claude-bridge='$AGENT_CLI_API_HOME/scripts/litellm-bridge/claude-via-bridge.sh'
```

Then: `bridge-start` in one terminal, `claude-bridge ~/your/repo` in another.

## Custom LiteLLM port

If you start the bridge on a non-default port:

```bash
/path/to/agent-cli-to-api/scripts/litellm-bridge/start-bridge.sh --litellm-port 4001
```

Match it when opening Claude:

```bash
export LITELLM_BRIDGE_PORT=4001
/path/to/agent-cli-to-api/scripts/litellm-bridge/claude-via-bridge.sh
```

`env-for-claude.sh` builds `ANTHROPIC_BASE_URL` from `LITELLM_BRIDGE_PORT` when unset.

## Manual setup (without `claude-via-bridge.sh`)

```bash
source /path/to/agent-cli-to-api/scripts/litellm-bridge/env-for-claude.sh
claude
```

## Tokens and 403 “Invalid token”

- The **default** bridge starts a **dedicated** gateway on **`:11435`** **without** `CODEX_GATEWAY_TOKEN`, so LiteLLM does not need a gateway secret.
- If you use `--skip-gateway` and point LiteLLM at **`:11434`** (or another instance) that **enforces** Bearer auth, set `CODEX_GATEWAY_TOKEN` for LiteLLM (see `run_bridge.py` hints) or pass the token via `AGENT_CLI_LIVE_TOKEN` when testing.

## Tests (repo root)

| Script | Purpose |
|--------|---------|
| `test_litellm_bridge_translation.py` | Anthropic → OpenAI translation via LiteLLM (mock backend) |
| `test_composer2_gateway_integration.py` | HTTP → `composer-2` resolves to `--model composer-2` (mock `cursor-agent`) |
| `test_composer2_live_api.py` | Real `cursor-agent` + real `/v1/chat/completions` (non-stream + stream) |

Live test against an already running gateway:

```bash
export AGENT_CLI_LIVE_BASE=http://127.0.0.1:11435
# export AGENT_CLI_LIVE_TOKEN=...   # if the gateway requires Bearer
python test_composer2_live_api.py
```

## Files in this directory

| File | Role |
|------|------|
| `run_bridge.py` | Starts gateway + LiteLLM, prints example Claude env |
| `litellm_config.yaml` | LiteLLM model list → `hosted_vllm` → `AGENT_CLI_API_BASE` |
| `env-for-claude.sh` | Env vars for Claude Code → local LiteLLM |
| `start-bridge.sh` | One-command bridge from a clean shell |
| `claude-via-bridge.sh` | Health check + env + `claude` |
| `requirements-bridge.txt` | Optional pinned deps (`litellm[proxy]`, `httpx`) |
