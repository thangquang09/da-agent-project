from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.logger import logger
from app.memory.conversation_store import get_conversation_memory_store
from backend.models.responses import ConversationTurnResponse, ThreadInfo

router = APIRouter(prefix="/threads", tags=["threads"])


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


@router.delete("/{thread_id}", status_code=204)
async def delete_thread(thread_id: str) -> None:
    """
    Clear all memory for a thread.

    Idempotent: deleting a non-existent thread returns 204 (no error).
    """
    store = get_conversation_memory_store()
    store.clear_thread(thread_id)
    logger.info("backend.threads deleted thread={thread}", thread=thread_id[:8])
