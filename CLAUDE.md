# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This repo currently contains a single project under `estimator/` — all commands below assume `cd estimator` first. The repo is part of a Master en AI Engineering and is intended to evolve module-by-module (CAG → RAG with vector DB in later modules).

## Common commands

Dependency / runtime management uses **uv** (Astral) and Python 3.11.

```bash
# Install deps (creates .venv)
uv sync

# Run the API locally with hot reload
uv run uvicorn app.main:app --reload

# Run the full test suite
uv run pytest

# Run a single test file or test
uv run pytest tests/test_health.py
uv run pytest tests/test_health.py::test_name -v

# Lint
uv run ruff check .
uv run ruff format .

# Docker (recommended dev path — bind-mounts app/ for live reload)
docker compose up --build
```

Service listens on `http://localhost:8000`; `/docs` (Swagger) and `/redoc` are enabled. Health probe at `GET /health`. Main API endpoint is `POST /api/v1/estimate`.

## Architecture

The estimator is a FastAPI service implementing **Cache Augmented Generation (CAG)**: reference estimations are inlined as static text inside the system prompt — no vector store, no retrieval step. This is a deliberate first-stage choice; later modules will migrate to RAG.

Request flow:

1. `app/routers/estimations.py` — `POST /api/v1/estimate` accepts an `EstimationRequest` (transcription, min 50 chars).
2. `app/services/llm_service.py::generate_estimation` — builds the system prompt by concatenating role instructions + formatted examples from `app/context/examples.py`, then dispatches to either `_call_openai` or `_call_anthropic` based on `LLM_PROVIDER`.
3. The LLM returns markdown; the service wraps it with `model`, `provider`, and token `usage` and the router returns `EstimationResponse`.

Key design points future changes should respect:

- **Provider abstraction lives in one file** (`llm_service.py`). Both branches return the same dict shape so the router stays provider-agnostic. Keep that contract when adding providers.
- **Settings are a cached singleton** via `app/config.py::get_settings` (`@lru_cache`). Pydantic Settings runs a `model_validator` that requires the API key matching `LLM_PROVIDER` to be set — changing provider also requires changing the key, or startup fails.
- **CAG examples** live in `app/context/examples.py` and are formatted into the prompt at request time. The example list is the system's "knowledge"; editing it directly changes model output. When this graduates to RAG, this module is the seam to replace.
- **Logging** is `structlog`, configured in `lifespan` (`main.py`): JSON in `production`, console in dev. Use `structlog.get_logger()` rather than stdlib `logging`.
- **Pricing assumptions** (62.50 EUR/h dev, 50 EUR/h designer) are hard-coded in the system prompt in `build_system_prompt`. Update there, not in examples.

## Configuration

`.env` (copied from `.env.example`) drives everything via `pydantic-settings`. Notable vars:

- `LLM_PROVIDER` — `openai` (default) or `anthropic`.
- `LLM_MODEL` — model id passed straight through to the SDK (e.g. `gpt-4o-mini`, `claude-...`).
- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` — only the one matching `LLM_PROVIDER` is required.
- `APP_ENV` — `development` | `staging` | `production` (controls log renderer).

## Docker

Multi-stage Dockerfile: `builder` installs prod-only deps with `uv sync --no-install-project --no-dev`, `runtime` is a clean `python:3.11-slim` that only carries `/app/.venv` and `app/`, runs as non-root `appuser`. There is a Docker-native HEALTHCHECK against `/health`. `docker-compose.yml` bind-mounts `./app` and adds `--reload` for dev — strip both for any production deployment.
