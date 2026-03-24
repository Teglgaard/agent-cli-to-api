# agent-cli-to-api

OpenAI-compatible HTTP gateway that exposes agent CLIs (Codex, Cursor, Claude, Gemini) as `/v1/chat/completions`.

## Quick Start

```bash
uv sync                          # install deps
uv run agent-cli-to-api codex    # start with a provider
```

## Project Structure

- `codex_gateway/` - Main package
  - `server.py` - FastAPI app, routes, SSE streaming
  - `cli.py` - CLI entrypoint (argparse)
  - `openai_compat.py` - OpenAI API format translation
  - `codex_cli.py` - Codex CLI backend
  - `codex_responses.py` - Codex /responses API backend
  - `claude_oauth.py` - Claude OAuth/direct API backend
  - `gemini_cloudcode.py` - Gemini CloudCode backend
  - `http_client.py` - Shared HTTP client
  - `rich_logging.py` - Rich terminal logging
  - `doctor.py` - Diagnostic checks
- `main.py` - Alternative entrypoint
- `scripts/` - Helper scripts (launchd, smoke test, litellm-bridge)
- `test_*.py` - Tests (root-level)

## Development

```bash
# Run tests
uv run pytest

# Type check
uv run mypy codex_gateway/

# Smoke test (start gateway first)
BASE_URL=http://127.0.0.1:8000/v1 ./scripts/smoke.sh
```

## Key Conventions

- Python 3.10+, FastAPI + uvicorn
- Pydantic v2 models for request/response validation
- SSE streaming for chat completions
- Provider backends are selected at startup or via model prefix (`cursor:`, `claude:`, `gemini:`)
- No `.env` loaded by default; use `--env-file` or `--auto-env` explicitly
- Auth token via `CODEX_GATEWAY_TOKEN` env var (optional)
