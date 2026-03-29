from __future__ import annotations

from app.rag import retrieve_business_context as _retrieve_business_context


def retrieve_business_context(query: str, top_k: int = 4) -> dict:
    results = _retrieve_business_context(query=query, top_k=top_k)
    return {
        "query": query,
        "top_k": top_k,
        "results": results,
        "result_count": len(results),
    }

