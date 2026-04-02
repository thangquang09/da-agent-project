# ────────────────────────────────────────────────────────────────
# DA Agent — Backend (FastAPI + uvicorn)
# Includes: LangGraph, sentence-transformers, torch, e2b, etc.
# ────────────────────────────────────────────────────────────────
FROM python:3.12-slim

# System deps: curl (healthcheck), git (some ML packages need it)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# ── Dependency layer (cache-friendly: copy lock files first) ────
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

# ── Application code ────────────────────────────────────────────
COPY app/ ./app/
COPY backend/ ./backend/
COPY mcp_server/ ./mcp_server/
COPY evals/ ./evals/
COPY data/seeds/ ./data/seeds/

# Pre-create runtime directories (will be mounted as volumes)
RUN mkdir -p data/warehouse evals/reports

# ── Non-root user for security ──────────────────────────────────
RUN useradd -m -u 1000 -s /bin/bash agentuser \
    && chown -R agentuser:agentuser /app

USER agentuser

EXPOSE 8001

# ── Healthcheck (used by Docker Compose depends_on) ─────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

CMD ["uv", "run", "uvicorn", "backend.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8001", \
     "--workers", "1", \
     "--timeout-graceful-shutdown", "10"]
