from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, AsyncGenerator

from sse_starlette.sse import ServerSentEvent

from app.logger import logger
from app.main import run_query
from backend.services.status_emitter import StatusEmitter
from backend.utils import make_serializable


async def stream_query_events(
    query: str,
    thread_id: str | None,
    user_semantic_context: str | None = None,
    uploaded_file_data: list[dict[str, Any]] | None = None,
    recursion_limit: int = 25,
    version: str = "v3",
) -> AsyncGenerator[ServerSentEvent, None]:
    loop = asyncio.get_running_loop()

    emitter = StatusEmitter(loop=loop)
    on_status = emitter.make_tracer_callback()
    on_token = emitter.make_token_callback()

    yield ServerSentEvent(
        data=json.dumps({"event": "started", "node": None, "data": {"query": query}}),
        event="started",
    )

    decoded_file_data: list[dict[str, Any]] | None = None
    if uploaded_file_data:
        decoded_file_data = []
        for f in uploaded_file_data:
            raw = f.get("data", b"")
            if isinstance(raw, str):
                raw = base64.b64decode(raw)
            decoded_file_data.append({"name": f["name"], "data": raw})

    graph_done = asyncio.Event()

    async def _drain_events() -> AsyncGenerator[ServerSentEvent, None]:
        while True:
            try:
                event = await asyncio.wait_for(emitter.queue.get(), timeout=0.5)
                if event.token:
                    # Token streaming event
                    yield ServerSentEvent(
                        data=json.dumps({"event": "token", "token": event.token}),
                        event="token",
                    )
                    await asyncio.sleep(0.012)
                else:
                    # Status event
                    yield ServerSentEvent(
                        data=json.dumps(
                            {"event": "status", "node": event.node, "data": event.to_dict()}
                        ),
                        event="status",
                    )
            except asyncio.TimeoutError:
                if graph_done.is_set() and emitter.queue.empty():
                    return

    def _run_graph() -> dict[str, Any]:
        return run_query(
            user_query=query,
            thread_id=thread_id,
            user_semantic_context=user_semantic_context,
            uploaded_file_data=decoded_file_data,
            recursion_limit=recursion_limit,
            version=version,
            on_status=on_status,
            on_token=on_token,
        )

    graph_task = loop.run_in_executor(None, _run_graph)

    async def _run_and_signal() -> dict[str, Any]:
        result = await graph_task
        graph_done.set()
        return result

    runner = asyncio.ensure_future(_run_and_signal())

    async for sse_event in _drain_events():
        yield sse_event
        if graph_done.is_set() and emitter.queue.empty():
            break

    try:
        payload = runner.result()
    except Exception as exc:
        logger.exception("backend.sse_service error: {error}", error=str(exc))
        yield ServerSentEvent(
            data=json.dumps(
                {
                    "event": "error",
                    "node": None,
                    "data": {"message": str(exc), "category": "BACKEND_ERROR"},
                }
            ),
            event="error",
        )
        return

    logger.info(
        "backend.sse_service done run_id={run_id}",
        run_id=payload.get("run_id", "?"),
    )

    serializable = make_serializable(payload)

    yield ServerSentEvent(
        data=json.dumps({"event": "result", "node": None, "data": serializable}),
        event="result",
    )
