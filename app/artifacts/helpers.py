"""Helper functions for saving visualization/chart data to files and building URL references.

Used by graph nodes to offload heavy data (PNG bytes, report markdown) from
LangGraph state to the local filesystem, keeping state lightweight.
"""

from __future__ import annotations

from app.artifacts.file_store import get_artifact_file_store
from app.logger import logger


def save_chart_to_file(
    image_data: bytes | None,
    image_format: str = "png",
    thread_id: str = "default",
    turn_number: int = 0,
) -> str | None:
    """Save PNG/SVG chart bytes to file and return a relative path.

    Returns None if image_data is empty/None (no file saved).
    """
    if not image_data:
        return None
    try:
        store = get_artifact_file_store()
        rel_path = store.save_chart(
            thread_id=thread_id,
            turn_number=turn_number,
            image_data=image_data,
            image_format=image_format,
        )
        logger.debug("Chart saved to artifact file: {path}", path=rel_path)
        return rel_path
    except Exception as exc:
        logger.warning("Failed to save chart to file: {err}", err=str(exc))
        return None


def chart_url_from_path(relative_path: str | None) -> str | None:
    """Convert a relative path to a URL path served by the backend."""
    if not relative_path:
        return None
    store = get_artifact_file_store()
    return store.get_artifact_url(relative_path)


def save_report_markdown_to_file(
    markdown: str,
    thread_id: str = "default",
    turn_number: int = 0,
) -> str | None:
    """Save report markdown to file and return a relative path."""
    if not markdown:
        return None
    try:
        store = get_artifact_file_store()
        rel_path = store.save_report_markdown(
            thread_id=thread_id,
            turn_number=turn_number,
            markdown=markdown,
        )
        logger.debug("Report markdown saved: {path}", path=rel_path)
        return rel_path
    except Exception as exc:
        logger.warning("Failed to save report markdown: {err}", err=str(exc))
        return None


def save_section_chart_to_file(
    image_data: bytes | None,
    section_id: str = "unknown",
    image_format: str = "png",
    thread_id: str = "default",
    turn_number: int = 0,
) -> str | None:
    """Save a report section chart image to file and return a relative path."""
    if not image_data:
        return None
    try:
        store = get_artifact_file_store()
        rel_path = store.save_report_section_chart(
            thread_id=thread_id,
            turn_number=turn_number,
            section_id=section_id,
            image_data=image_data,
            image_format=image_format,
        )
        logger.debug("Section chart saved: {path}", path=rel_path)
        return rel_path
    except Exception as exc:
        logger.warning("Failed to save section chart: {err}", err=str(exc))
        return None


def read_chart_bytes(relative_path: str | None) -> bytes | None:
    """Read chart image bytes from file (e.g. for LLM multimodal input).

    Returns None if path is None or file doesn't exist.
    """
    if not relative_path:
        return None
    try:
        store = get_artifact_file_store()
        abs_path = store.resolve_path(relative_path)
        if abs_path.exists():
            return abs_path.read_bytes()
        return None
    except Exception as exc:
        logger.warning("Failed to read chart bytes: {err}", err=str(exc))
        return None


def build_viz_dict_from_result(
    result,
    thread_id: str = "default",
    turn_number: int = 0,
) -> dict:
    """Build a visualization state dict from a VisualizationResult, saving image to file.

    Replaces the old pattern of:
        {"success": ..., "image_url": rel_path, "image_format": ...}

    With:
        {"success": ..., "image_url": "/artifacts/...", "image_format": ..., "image_size_bytes": ...}
    """
    image_url = None
    image_size_bytes = 0
    if result.image_data:
        rel_path = save_chart_to_file(
            image_data=result.image_data,
            image_format=result.image_format or "png",
            thread_id=thread_id,
            turn_number=turn_number,
        )
        if rel_path:
            image_url = chart_url_from_path(rel_path)
            image_size_bytes = len(result.image_data)

    return {
        "success": result.success,
        "image_url": image_url,
        "image_format": result.image_format or "png",
        "image_size_bytes": image_size_bytes,
        "error": result.error,
        "code_executed": result.code_executed if hasattr(result, "code_executed") else None,
        "execution_time_ms": result.execution_time_ms,
    }
