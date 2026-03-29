from __future__ import annotations

from app.rag import retrieve_metric_definition as _retrieve_metric_definition


def retrieve_metric_definition(query: str, top_k: int = 3) -> dict:
    results = _retrieve_metric_definition(query=query, top_k=top_k)
    return {
        "query": query,
        "top_k": top_k,
        "results": results,
        "result_count": len(results),
    }

