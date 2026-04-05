# ────────────────────────────────────────────────────────────────
# DA Agent — Frontend (Streamlit thin client)
# Only needs: streamlit, httpx, loguru, python-dotenv
# No ML deps → smaller image than backend
# ────────────────────────────────────────────────────────────────
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# ── Install ALL deps (uv is fast enough; avoids a separate thin lockfile) ──
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

# ── Only the files Streamlit thin client needs ───────────────────
COPY streamlit_app.py ./
# backend HTTP client
COPY backend/__init__.py backend/http_client.py ./backend/
# app logger (imported by http_client and streamlit_app)
COPY app/__init__.py app/logger.py app/config.py ./app/
# .env so loguru / config can load without errors in container
COPY .env.docker.frontend ./.env

# ── Non-root user ────────────────────────────────────────────────
RUN useradd -m -u 1000 -s /bin/bash appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["uv", "run", "streamlit", "run", "streamlit_app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
