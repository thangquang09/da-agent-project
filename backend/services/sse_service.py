from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, AsyncGenerator

from sse_starlette.sse import ServerSentEvent

from app.logger import logger
from app.main import run_query


async def stream_query_events(
    query: str,
    thread_id: str | None,
    user_semantic_context: str | None = None,
    uploaded_file_data: list[dict[str, Any]] | None = None,
    recursion_limit: int = 25,
) -> AsyncGenerator[ServerSentEvent, None]:
    """
    Yields SSE events for a query execution.

    Wire protocol (3 event types):
      started  → fires immediately, signals work began (client shows "thinking")
      result   → fires after graph completes (~7-10s), full QueryResponse payload
      error    → fires on exception, includes message + category

    This is "synthetic" streaming: we fire `started` immediately so the
    frontend is responsive, then run the synchronous graph in a thread pool,
    then emit `result`. The SSE contract is stable — when graph.astream()
    is adopted later, intermediate node events can be added without breaking
    existing clients.
    """
    # Fire immediately → frontend shows spinner
    yield ServerSentEvent(
        data=json.dumps({"event": "started", "node": None, "data": {"query": query}}),
        event="started",
    )

    # Decode base64 file data if present
    decoded_file_data: list[dict[str, Any]] | None = None
    if uploaded_file_data:
        decoded_file_data = []
        for f in uploaded_file_data:
            raw = f.get("data", b"")
            if isinstance(raw, str):
                raw = base64.b64decode(raw)
            decoded_file_data.append({"name": f["name"], "data": raw})

    try:
        loop = asyncio.get_event_loop()
        payload: dict[str, Any] = await loop.run_in_executor(
            None,
            lambda: run_query(
                user_query=query,
                thread_id=thread_id,
                user_semantic_context=user_semantic_context,
                uploaded_file_data=decoded_file_data,
                recursion_limit=recursion_limit,
            ),
        )

        logger.info(
            "backend.sse_service done run_id={run_id}",
            run_id=payload.get("run_id", "?"),
        )

        # Serialize payload — convert bytes to base64 for JSON transport
        serializable = _make_serializable(payload)

        yield ServerSentEvent(
            data=json.dumps({"event": "result", "node": None, "data": serializable}),
            event="result",
        )

    except Exception as exc:  # noqa: BLE001
        logger.exception("backend.sse_service error: {error}", error=str(exc))
        yield ServerSentEvent(
            data=json.dumps({
                "event": "error",
                "node": None,
                "data": {"message": str(exc), "category": "BACKEND_ERROR"},
            }),
            event="error",
        )


def _make_serializable(obj: Any) -> Any:
    """Recursively convert bytes → base64 str for JSON serialization."""
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode()
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_serializable(i) for i in obj]
    return obj
