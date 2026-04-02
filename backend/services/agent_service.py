from __future__ import annotations

import asyncio
import base64
from typing import Any

from app.logger import logger
from app.main import run_query
from backend.models.responses import QueryResponse


async def run_query_async(
    query: str,
    thread_id: str | None,
    user_semantic_context: str | None = None,
    uploaded_file_data: list[dict[str, Any]] | None = None,
    recursion_limit: int = 25,
    version: str = "v2",
) -> QueryResponse:
    """
    Async wrapper around the synchronous run_query().

    LangGraph's graph.invoke() is blocking (~7-10s). FastAPI runs inside
    asyncio, so we offload the call to a ThreadPoolExecutor via
    run_in_executor() to avoid blocking the event loop.

    Thread-safety notes:
    - RunTracer uses ContextVar → isolated per executor thread.
    - ConversationMemoryStore singleton uses check_same_thread=False SQLite.
    - build_sql_v2_graph() creates a fresh graph per call → no cross-request state.
    """
    # Decode base64 file data coming from JSON body uploads
    decoded_file_data: list[dict[str, Any]] | None = None
    if uploaded_file_data:
        decoded_file_data = []
        for f in uploaded_file_data:
            raw = f.get("data", b"")
            if isinstance(raw, str):
                raw = base64.b64decode(raw)
            decoded_file_data.append({"name": f["name"], "data": raw})

    loop = asyncio.get_event_loop()
    payload: dict[str, Any] = await loop.run_in_executor(
        None,
        lambda: run_query(
            user_query=query,
            thread_id=thread_id,
            user_semantic_context=user_semantic_context,
            uploaded_file_data=decoded_file_data,
            recursion_limit=recursion_limit,
            version=version,
        ),
    )

    logger.info(
        "backend.agent_service done run_id={run_id} intent={intent}",
        run_id=payload.get("run_id", "?"),
        intent=payload.get("intent", "?"),
    )

    # Build QueryResponse — use only keys that exist in the payload
    return QueryResponse(**{k: v for k, v in payload.items() if v is not None and k in QueryResponse.model_fields})
