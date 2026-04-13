from __future__ import annotations

from pathlib import Path

import psycopg
from fastapi import APIRouter, Response, status

from app.config import load_settings
from backend.models.responses import HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Cheap liveness probe for deploy platforms and smoke tests."""
    settings = load_settings()
    return HealthResponse(
        status="ok",
        version="1.0.0",
        graph_version="v3",
        app_mode=settings.app_mode,
    )


@router.get("/ready", response_model=ReadyResponse)
async def ready(response: Response) -> ReadyResponse:
    """Readiness probe for demo runbooks and CI smoke tests."""
    settings = load_settings()
    checks: dict[str, str] = {}

    try:
        with psycopg.connect(settings.database_url) as conn:
            conn.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error:{exc}"

    artifact_root = Path(settings.artifact_root)
    checks["artifact_root"] = "ok" if artifact_root.exists() else "missing"
    checks["visualization"] = "enabled" if settings.enable_visualization else "disabled"
    checks["qdrant"] = "enabled" if settings.enable_qdrant else "disabled"
    checks["langfuse"] = "enabled" if settings.enable_langfuse else "disabled"

    failed_checks = [name for name, result in checks.items() if result not in {"ok", "enabled", "disabled"}]
    if failed_checks:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        overall_status = "degraded"
    else:
        overall_status = "ready"

    return ReadyResponse(
        status=overall_status,
        version="1.0.0",
        graph_version="v3",
        app_mode=settings.app_mode,
        demo_mode=settings.demo_mode,
        artifact_mode=settings.artifact_mode,
        checks=checks,
    )
