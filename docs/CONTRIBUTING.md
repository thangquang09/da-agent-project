# Contributing Guide

Welcome to the DA Agent Lab! We appreciate your interest in contributing.

## Development Environment Setup

1. Make sure you have Python 3.11+ installed.
2. Install `uv` for dependency management.
3. Create a virtual environment and install dependencies:
   ```bash
   uv sync
   ```
4. Copy `.env.docker.local` to `.env` and fill in your actual API keys.
5. Start PostgreSQL database:
   ```bash
   docker compose up -d postgres
   ```
6. Seed the database (first time only):
   ```bash
   uv run python data/seeds/create_seed_db.py
   ```

<!-- AUTO-GENERATED: SCRIPTS -->
## Available Commands

| Command | Description |
|---------|-------------|
| `uv run streamlit run streamlit_app.py` | Run the Streamlit web UI |
| `uv run python -m app.main "<query>"` | Run the CLI version of the agent |
| `uv run python -m mcp_server.server` | Run the MCP server |
| `uv run pytest` | Run the entire test suite |
| `uv run pytest --cov=app --cov-report=term-missing` | Run tests with coverage report |
| `uv run python data/seeds/create_seed_db.py` | Seed the local database with test data |
| `uv run python -m evals.runner` | Run the evaluation suite |
| `uv run python -m evals.manual_sql_smoke` | Run manual SQL smoke tests |
<!-- /AUTO-GENERATED: SCRIPTS -->

## Testing

- Write tests for any new functionality (TDD is preferred).
- Ensure all tests pass before submitting a PR: `uv run pytest`
- Maintain at least 80% test coverage.

## Code Style

- We use `ruff` (implied by `.ruff_cache` presence) for linting and formatting.
- See `docs/CODE_STYLE.md` for naming conventions and patterns.
- Keep the codebase deterministic where possible.

## PR Submission Checklist

- [ ] All tests pass (`uv run pytest`)
- [ ] Test coverage is maintained (>= 80%)
- [ ] Code is formatted and linted
- [ ] Documentation (`CLAUDE.md`, `AGENTS.md`) is updated if architecture changed
- [ ] No hardcoded secrets
