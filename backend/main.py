from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import load_settings
from app.logger import logger
from backend.routers import artifacts, data, evals, health, query, threads, traces, users


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
    app.include_router(traces.router)
    app.include_router(evals.router)
    app.include_router(data.router)
    app.include_router(artifacts.router)
    app.include_router(users.router)

    @app.on_event("startup")
    async def _startup() -> None:
        settings = load_settings()
        logger.info(
            "DA Agent backend starting up (port={port}, mode={mode})",
            port=os.getenv("BACKEND_PORT", "8001"),
            mode=settings.app_mode,
        )

        # Ensure artifact root directory exists
        try:
            from app.artifacts.file_store import get_artifact_file_store

            get_artifact_file_store()
            logger.info("Artifact file store ready")
        except Exception as exc:
            logger.warning("Artifact file store init failed (non-fatal): {err}", err=str(exc))

        # Pre-warm ConversationMemoryStore singleton (PostgreSQL-backed)
        from app.memory.conversation_store import get_conversation_memory_store

        get_conversation_memory_store()

        # Optional embedding prewarm: keep disabled in demo mode unless explicitly enabled.
        if settings.enable_qdrant and settings.enable_startup_embedding_prewarm:
            try:
                from app.memory.qdrant_client import get_embedding_model, is_qdrant_library_installed

                if is_qdrant_library_installed():
                    logger.info("Pre-warming embedding model...")
                    get_embedding_model()
                    logger.info("Embedding model ready")
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Embedding model pre-warm failed (non-fatal): {err}", err=str(exc)
                )
        else:
            logger.info(
                "Skipping embedding pre-warm (enable_qdrant={qdrant}, prewarm={prewarm})",
                qdrant=settings.enable_qdrant,
                prewarm=settings.enable_startup_embedding_prewarm,
            )

        logger.info("DA Agent backend ready")

    return app


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
