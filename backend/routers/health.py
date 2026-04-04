from __future__ import annotations

from fastapi import APIRouter

from backend.models.responses import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint for Docker Compose healthcheck and monitoring."""
    return HealthResponse(status="ok", version="1.0.0", graph_version="v3")
