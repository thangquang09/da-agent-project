from __future__ import annotations

from typing import Any


def retrieve_rag_answer(query: str, top_k: int = 4) -> dict[str, Any]:
    """
    Placeholder RAG tool for future leader-agent orchestration.

    The current graph still uses dedicated retrieval nodes. This tool exists so a
    future tool-calling supervisor/leader can invoke a single RAG capability
    without depending on router-specific graph branches.
    """
    # TODO: Implement actual RAG retrieval
    context = []  # Will be populated by actual RAG implementation
    terminal = bool(context)

    return {
        "query": query,
        "top_k": top_k,
        "answer": "Không có thông tin",
        "sources": [],
        "status": "stub",
        # WorkerArtifact fields
        "artifact_type": "rag_context",
        "artifact_status": "partial" if context else "failed",
        "artifact_payload": {
            "chunks": context,
            "chunk_count": len(context) if context else 0,
            "answer": "Không có thông tin",
        },
        "artifact_evidence": {
            "source": "rag_index",
            "query": query,
        },
        "artifact_terminal": terminal,
        "artifact_recommended_action": "finalize" if terminal else "clarify",
    }
