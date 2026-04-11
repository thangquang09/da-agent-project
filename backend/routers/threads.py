from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.logger import logger
from app.memory.conversation_store import get_conversation_memory_store
from backend.models.responses import ConversationTurnResponse, ThreadInfo, TurnArtifactResponse

router = APIRouter(prefix="/threads", tags=["threads"])


@router.get("", response_model=list[ThreadInfo])
async def list_threads(limit: int = 50) -> list[ThreadInfo]:
    """List all conversation threads, ordered by most recently updated."""
    store = get_conversation_memory_store()
    rows = store.list_threads(limit=limit)
    return [ThreadInfo(**row) for row in rows]


@router.get("/{thread_id}", response_model=ThreadInfo)
async def get_thread(thread_id: str) -> ThreadInfo:
    """Get thread summary info. Returns 404 if the thread has no turns."""
    store = get_conversation_memory_store()
    turn_count = store.get_turn_count(thread_id)
    if turn_count == 0:
        raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found")

    summary = store.get_summary(thread_id)
    return ThreadInfo(
        thread_id=thread_id,
        turn_count=turn_count,
        summary=summary.summary if summary else None,
        last_updated=summary.last_updated if summary else None,
        key_entities=summary.key_entities if summary else [],
    )


@router.get("/{thread_id}/history", response_model=list[ConversationTurnResponse])
async def get_thread_history(
    thread_id: str,
    limit: int = 20,
) -> list[ConversationTurnResponse]:
    """Get recent conversation turns for a thread in chronological order."""
    store = get_conversation_memory_store()
    turns = store.get_recent_turns(thread_id, limit=limit)
    return [
        ConversationTurnResponse(**t.to_dict())
        for t in turns
    ]


@router.get("/{thread_id}/artifacts", response_model=list[TurnArtifactResponse])
async def get_thread_artifacts(thread_id: str) -> list[TurnArtifactResponse]:
    """Get all persisted artifacts (reports, charts) for a thread."""
    from app.memory.artifact_store import get_artifact_store

    store = get_artifact_store()
    artifacts = store.get_thread_artifacts(thread_id)
    return [
        TurnArtifactResponse(
            thread_id=a.thread_id,
            turn_number=a.turn_number,
            artifact_type=a.artifact_type,
            payload=a.payload,
        )
        for a in artifacts
    ]


@router.delete("/{thread_id}", status_code=204)
async def delete_thread(thread_id: str) -> None:
    """
    Clear all memory for a thread.

    Idempotent: deleting a non-existent thread returns 204 (no error).
    Also cleans up artifact files from disk and artifact metadata from PostgreSQL.
    """
    store = get_conversation_memory_store()
    store.clear_thread(thread_id)

    # Clean up artifact metadata (PostgreSQL) and files (disk)
    from app.memory.artifact_store import get_artifact_store
    artifact_store = get_artifact_store()
    deleted = artifact_store.delete_thread_artifacts(thread_id, cleanup_files=True)
    if deleted:
        logger.info(
            "backend.threads cleaned up {n} artifacts for thread={thread}",
            n=deleted,
            thread=thread_id[:8],
        )

    logger.info("backend.threads deleted thread={thread}", thread=thread_id[:8])
