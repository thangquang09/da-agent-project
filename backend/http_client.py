from __future__ import annotations

import json
import os
from typing import Any, Generator

import httpx

from app.logger import logger

# Backend URL — override via BACKEND_URL env var (Docker: http://backend:8001)
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8001")

# Timeout for long-running agent queries (graph can take 7-10s; 120s gives margin)
_QUERY_TIMEOUT = float(os.getenv("BACKEND_QUERY_TIMEOUT", "120"))
_SHORT_TIMEOUT = 10.0


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


def query_stream(
    query: str,
    thread_id: str,
    user_semantic_context: str | None = None,
    uploaded_file_data: list[dict[str, Any]] | None = None,
) -> Generator[dict[str, Any], None, None]:
    """
    Execute a query via the backend, yielding SSE event dicts.

    Each yielded dict has shape:
        {"event": "started" | "result" | "error", "data": {...}}

    When uploaded_file_data is present, falls back to POST /query/upload
    (multipart) which doesn't support streaming, then wraps result as events.

    Usage:
        for event in query_stream("DAU hôm qua?", "thread-abc"):
            if event["event"] == "result":
                payload = event["data"]
    """
    if uploaded_file_data:
        # Files must go via multipart — wrap response as SSE-style events
        yield {"event": "started", "data": {"query": query}}
        try:
            result = _query_with_files(
                query, thread_id, user_semantic_context, uploaded_file_data
            )
            yield {"event": "result", "data": result}
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "http_client._query_with_files failed: {err}", err=str(exc)
            )
            yield {
                "event": "error",
                "data": {"message": str(exc), "category": "CLIENT_ERROR"},
            }
        return

    # Normal SSE path
    params: dict[str, Any] = {"q": query, "thread_id": thread_id}
    if user_semantic_context:
        params["user_semantic_context"] = user_semantic_context

    logger.debug("http_client.query_stream → {url}/query/stream", url=BACKEND_URL)
    try:
        with httpx.Client(timeout=_QUERY_TIMEOUT) as client:
            with client.stream(
                "GET", f"{BACKEND_URL}/query/stream", params=params
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    raw = line[6:]  # strip "data: " prefix
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                        yield event
                    except json.JSONDecodeError:
                        logger.warning(
                            "http_client: could not parse SSE line: {line}",
                            line=raw[:100],
                        )
    except httpx.HTTPStatusError as exc:
        logger.error("http_client.query_stream HTTP error: {err}", err=str(exc))
        yield {
            "event": "error",
            "data": {"message": str(exc), "category": "HTTP_ERROR"},
        }
    except httpx.RequestError as exc:
        logger.error("http_client.query_stream connection error: {err}", err=str(exc))
        yield {
            "event": "error",
            "data": {
                "message": f"Cannot connect to backend at {BACKEND_URL}: {exc}",
                "category": "CONNECTION_ERROR",
            },
        }


def _query_with_files(
    query: str,
    thread_id: str,
    user_semantic_context: str | None,
    uploaded_file_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """POST /query/upload with multipart form data."""
    form_data: dict[str, Any] = {
        "query": query,
        "thread_id": thread_id,
    }
    if user_semantic_context:
        form_data["user_semantic_context"] = user_semantic_context

    # Serialize per-file business contexts as JSON form field
    contexts_dict = {f["name"]: f.get("context", "") for f in uploaded_file_data}
    if any(contexts_dict.values()):
        form_data["contexts_json"] = json.dumps(contexts_dict, ensure_ascii=False)

    files = [
        (
            "files",
            (
                f["name"],
                f["data"] if isinstance(f["data"], bytes) else f["data"].encode(),
                "text/csv",
            ),
        )
        for f in uploaded_file_data
    ]

    with httpx.Client(timeout=_QUERY_TIMEOUT) as client:
        resp = client.post(f"{BACKEND_URL}/query/upload", data=form_data, files=files)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------


def get_thread_history(thread_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Get conversation history for a thread. Returns [] if not found."""
    try:
        with httpx.Client(timeout=_SHORT_TIMEOUT) as client:
            resp = client.get(
                f"{BACKEND_URL}/threads/{thread_id}/history",
                params={"limit": limit},
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            return resp.json()
    except httpx.RequestError as exc:
        logger.warning("http_client.get_thread_history failed: {err}", err=str(exc))
        return []


def delete_thread(thread_id: str) -> None:
    """Delete all memory for a thread. Idempotent."""
    try:
        with httpx.Client(timeout=_SHORT_TIMEOUT) as client:
            client.delete(f"{BACKEND_URL}/threads/{thread_id}").raise_for_status()
    except httpx.RequestError as exc:
        logger.warning("http_client.delete_thread failed: {err}", err=str(exc))


def health_check() -> bool:
    """Quick liveness check. Returns True if backend is reachable."""
    try:
        with httpx.Client(timeout=3.0) as client:
            return client.get(f"{BACKEND_URL}/health").status_code == 200
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Traces
# ---------------------------------------------------------------------------


def get_trace(run_id: str) -> dict[str, Any] | None:
    """Get full trace data for a specific run_id. Returns None if not found."""
    try:
        with httpx.Client(timeout=_SHORT_TIMEOUT) as client:
            resp = client.get(f"{BACKEND_URL}/traces/{run_id}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
    except httpx.RequestError as exc:
        logger.warning("http_client.get_trace failed: {err}", err=str(exc))
        return None
