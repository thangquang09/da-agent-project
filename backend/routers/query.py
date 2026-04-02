from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sse_starlette.sse import EventSourceResponse

from app.logger import logger
from backend.models.requests import QueryRequest
from backend.models.responses import QueryResponse
from backend.services.agent_service import run_query_async
from backend.services.sse_service import stream_query_events

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryResponse)
async def query(request: QueryRequest) -> QueryResponse:
    """
    Non-streaming query endpoint.

    Suitable for: eval runner, CLI clients, programmatic use.
    Returns full QueryResponse after agent completes (~7-10s).
    """
    effective_thread_id = request.thread_id or str(uuid.uuid4())
    logger.info(
        "backend.query POST thread={thread} query_len={qlen}",
        thread=effective_thread_id[:8],
        qlen=len(request.query),
    )

    file_data: list[dict[str, Any]] | None = None
    if request.uploaded_file_data:
        file_data = [{"name": f.name, "data": f.data} for f in request.uploaded_file_data]

    return await run_query_async(
        query=request.query,
        thread_id=effective_thread_id,
        user_semantic_context=request.user_semantic_context,
        uploaded_file_data=file_data,
        recursion_limit=request.recursion_limit,
        version=request.version,
    )


@router.post("/upload", response_model=QueryResponse)
async def query_with_upload(
    query: str = Form(...),
    thread_id: str | None = Form(None),
    user_semantic_context: str | None = Form(None),
    version: str = Form("v2"),
    recursion_limit: int = Form(25),
    files: list[UploadFile] = File(default=[]),
) -> QueryResponse:
    """
    Multipart file upload endpoint.

    Used by Streamlit when user uploads CSV files. Files are raw bytes
    read from the upload and passed directly to run_query().
    """
    effective_thread_id = thread_id or str(uuid.uuid4())
    logger.info(
        "backend.query POST /upload thread={thread} files={n}",
        thread=effective_thread_id[:8],
        n=len(files),
    )

    file_data: list[dict[str, Any]] | None = None
    if files:
        file_data = []
        for f in files:
            content = await f.read()
            file_data.append({"name": f.filename or "upload.csv", "data": content})

    return await run_query_async(
        query=query,
        thread_id=effective_thread_id,
        user_semantic_context=user_semantic_context,
        uploaded_file_data=file_data,
        recursion_limit=recursion_limit,
        version=version,
    )


@router.get("/stream")
async def query_stream(
    q: str,
    thread_id: str | None = None,
    user_semantic_context: str | None = None,
    recursion_limit: int = 25,
) -> EventSourceResponse:
    """
    SSE streaming endpoint.

    Used by the Streamlit thin client for real-time progress feedback.
    Fires 'started' immediately, then 'result' (or 'error') after graph completes.

    GET (not POST) because SSE is a GET-based protocol per W3C spec.
    File uploads go through POST /query/upload.
    """
    if not q or not q.strip():
        raise HTTPException(status_code=422, detail="Query parameter 'q' is required")

    effective_thread_id = thread_id or str(uuid.uuid4())
    logger.info(
        "backend.query GET /stream thread={thread}",
        thread=effective_thread_id[:8],
    )

    return EventSourceResponse(
        stream_query_events(
            query=q.strip(),
            thread_id=effective_thread_id,
            user_semantic_context=user_semantic_context,
            recursion_limit=recursion_limit,
        ),
        media_type="text/event-stream",
    )
