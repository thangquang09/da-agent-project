"""Artifact file serving router — serves files from the local artifacts/ directory."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import load_settings

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _get_artifact_root() -> Path:
    settings = load_settings()
    return Path(settings.artifact_root).resolve()


@router.get("/{file_path:path}")
async def get_artifact_file(file_path: str) -> FileResponse:
    """Serve an artifact file from the local filesystem.

    The file_path is relative to ARTIFACT_ROOT, e.g.:
      /artifacts/{thread_id}/{turn_number}/chart_abc123.png
      /artifacts/{thread_id}/{turn_number}/report.md
      /artifacts/{thread_id}/{turn_number}/section_xyz_def456.png
    """
    if not file_path:
        raise HTTPException(status_code=400, detail="No file path provided")

    # Security: prevent path traversal
    if ".." in file_path or file_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid file path")

    artifact_root = _get_artifact_root()
    full_path = (artifact_root / file_path).resolve()

    # Ensure the resolved path is still under artifact_root
    if not str(full_path).startswith(str(artifact_root)):
        raise HTTPException(status_code=403, detail="Access denied")

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found")

    if not full_path.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")

    # Determine content type from extension
    ext = full_path.suffix.lower()
    content_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".svg": "image/svg+xml",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".md": "text/markdown; charset=utf-8",
        ".csv": "text/csv; charset=utf-8",
        ".json": "application/json",
        ".html": "text/html; charset=utf-8",
    }
    media_type = content_types.get(ext, "application/octet-stream")

    return FileResponse(
        path=str(full_path),
        media_type=media_type,
        filename=full_path.name,
    )
