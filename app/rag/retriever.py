from __future__ import annotations

from app.rag.index_docs import query_index


METRIC_DOCS = {"metric_definitions.md", "retention_rules.md"}


def retrieve_metric_definition(query: str, top_k: int = 3) -> list[dict]:
    return query_index(query=query, top_k=top_k, source_filter=METRIC_DOCS)


def retrieve_business_context(query: str, top_k: int = 4) -> list[dict]:
    return query_index(query=query, top_k=top_k, source_filter=None)

