from __future__ import annotations

from typing import Any


def retrieve_rag_answer(query: str, top_k: int = 4) -> dict[str, Any]:
    """
    Placeholder RAG tool for future leader-agent orchestration.

    The current graph still uses dedicated retrieval nodes. This tool exists so a
    future tool-calling supervisor/leader can invoke a single RAG capability
    without depending on router-specific graph branches.
    """
    return {
        "query": query,
        "top_k": top_k,
        "answer": "Không có thông tin",
        "sources": [],
        "status": "stub",
    }
