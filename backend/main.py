from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.logger import logger
from backend.routers import evals, health, query, threads


def create_app() -> FastAPI:
    """
    FastAPI app factory.

    Using factory pattern (not module-level app object) so tests can call
    create_app() and get a fresh instance without side effects.
    """
    app = FastAPI(
        title="DA Agent API",
        version="1.0.0",
        description="LangGraph Data Analyst Agent — HTTP API",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS: allow Streamlit frontend (localhost:8501) + wildcard for dev.
    # Tighten to specific origins in production via BACKEND_CORS_ORIGINS env var.
    cors_origins = os.getenv("BACKEND_CORS_ORIGINS", "*").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(query.router)
    app.include_router(threads.router)
    app.include_router(evals.router)

    @app.on_event("startup")
    async def _startup() -> None:
        import asyncio

        logger.info("DA Agent backend starting up (port={port})", port=os.getenv("BACKEND_PORT", "8001"))

        # Pre-warm ConversationMemoryStore singleton to avoid first-request latency
        from app.memory.conversation_store import get_conversation_memory_store
        get_conversation_memory_store()

        # Auto-seed analytics DB if missing (e.g., fresh Docker volume)
        db_path = Path(os.getenv("SQLITE_DB_PATH", "data/warehouse/analytics.db"))
        if not db_path.exists():
            logger.info("analytics.db not found — running seed script")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _seed_db)

        logger.info("DA Agent backend ready")

    return app


def _seed_db() -> None:
    """Run data/seeds/create_seed_db.py to populate analytics.db."""
    try:
        from data.seeds import create_seed_db  # type: ignore[import]
        if hasattr(create_seed_db, "main"):
            create_seed_db.main()
        else:
            import runpy
            runpy.run_module("data.seeds.create_seed_db", run_name="__main__")
    except Exception as exc:  # noqa: BLE001
        logger.warning("backend.startup seed failed (non-fatal): {err}", err=str(exc))


# Module-level app for uvicorn: uvicorn backend.main:app
app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=int(os.getenv("BACKEND_PORT", "8001")),
        reload=os.getenv("BACKEND_RELOAD", "false").lower() == "true",
        log_level="info",
    )
