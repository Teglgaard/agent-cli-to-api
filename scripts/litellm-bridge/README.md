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

**Paths:** These scripts live in **agent-cli-to-api**. Running `./scripts/litellm-bridge/...` only works when your current directory is that repo. From another directory, call the script by **absolute path** (as below) or `cd` to `agent-cli-to-api` first.

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

## OpenAI Codex CLI

[OpenAI Codex CLI](https://github.com/openai/codex) uses the **OpenAI-compatible** API. Point it at **LiteLLM** (not the gateway port directly). This repo’s `litellm_config.yaml` uses **`hosted_vllm/composer-2-fast`** so LiteLLM forwards to the gateway on **`/v1/chat/completions`** (avoids `/v1/responses` + `stream: true` errors on this gateway).

**Easiest — one command (starts bridge in the background if it is not already up)**

```bash
/path/to/agent-cli-to-api/scripts/litellm-bridge/codex-local.sh
```

Same args as `codex` (optional project dir first), e.g. `codex-local.sh resume <session-id>`. Bridge logs when auto-started go to `/tmp/litellm-bridge.log` unless you set `LITELLM_BRIDGE_LOG`.

**Terminal 2 — Codex (bridge already running)**

```bash
/path/to/agent-cli-to-api/scripts/litellm-bridge/codex-via-bridge.sh
```

Or set env yourself (same as `codex-via-bridge.sh`):

```bash
# Must SOURCE (running the file without `source` does not export into your shell):
source /path/to/agent-cli-to-api/scripts/litellm-bridge/env-for-codex.sh
codex --model composer-2-fast
```

If LiteLLM uses `master_key` auth, **`OPENAI_BASE_URL` alone is not enough** — you need a Bearer token matching `LITELLM_MASTER_KEY` in the repo `.env`. `env-for-codex.sh` sets `OPENAI_API_KEY` and `LITELLM_API_KEY` from that when present.

**Config file:** merge `codex-config.composer-2-fast.toml.example` into `~/.codex/config.toml` (or project `.codex/config.toml`) so `openai_base_url` and `model` persist. The URL must stay **`http://127.0.0.1:4000/v1`** (LiteLLM), not the gateway on `:11435`.

**Troubleshooting — empty Codex chat with `wire_api = "responses"`:** Codex streams the Responses API through LiteLLM to the gateway. LiteLLM validates each SSE event; the gateway shim must emit the same ordering as OpenAI/LiteLLM: after **`response.created`**, **`response.in_progress`** and **`response.output_item.added`**, then deltas with **`content_index`** and a top-level **`model`** field on each event (matching LiteLLM’s stream). If assistant text disappears after an upgrade, pull the latest `agent-cli-to-api` and restart **both** the gateway and the LiteLLM child process (not only one of them).

**Verify the bridge (health + streamed Responses):**

```bash
/path/to/agent-cli-to-api/scripts/litellm-bridge/verify-codex-bridge.sh
```

## Optional: short shell aliases

Add to `~/.zshrc` (adjust `AGENT_CLI_API_HOME`):

```bash
export AGENT_CLI_API_HOME="$HOME/Krown-Development/agent-cli-to-api"
alias bridge-start='$AGENT_CLI_API_HOME/scripts/litellm-bridge/start-bridge.sh'
alias claude-bridge='$AGENT_CLI_API_HOME/scripts/litellm-bridge/claude-via-bridge.sh'
alias codex-bridge='$AGENT_CLI_API_HOME/scripts/litellm-bridge/codex-via-bridge.sh'
alias codex-local='$AGENT_CLI_API_HOME/scripts/litellm-bridge/codex-local.sh'
```

Then: **`codex-local`** for one-shot Codex (auto-starts bridge if needed), or `bridge-start` in one terminal and `claude-bridge ~/your/repo` / `codex-bridge` in another.

**Orchestration UIs:** Multi-agent wrappers (for example **Oh-my-codex**) are **separate repositories** — nothing in this folder installs or runs them. For Codex in the terminal with this gateway, use **`codex-local.sh`** / **`codex-via-bridge.sh`** and `env-for-codex.sh` only.

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
| `env-for-codex.sh` | `OPENAI_BASE_URL` / `OPENAI_API_KEY` for Codex → LiteLLM |
| `codex-via-bridge.sh` | Health check + env + `codex` (default model `composer-2-fast`) |
| `codex-local.sh` | Start bridge if down, then env + `codex` (single command) |
| `codex-config.composer-2-fast.toml.example` | Example `openai_base_url` + `model` for `~/.codex/config.toml` |
| `requirements-bridge.txt` | Optional pinned deps (`litellm[proxy]`, `httpx`) |
