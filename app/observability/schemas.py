from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal


FailureCategory = Literal[
    "ROUTING_ERROR",
    "SQL_GENERATION_ERROR",
    "SQL_VALIDATION_ERROR",
    "SQL_EXECUTION_ERROR",
    "EMPTY_RESULT",
    "RAG_RETRIEVAL_ERROR",
    "RAG_IRRELEVANT_CONTEXT",
    "SYNTHESIS_ERROR",
    "STEP_LIMIT_REACHED",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class NodeTraceRecord:
    record_type: str
    run_id: str
    node_name: str
    attempt: int
    status: Literal["ok", "error"]
    started_at: str
    ended_at: str
    latency_ms: float
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]
    error_category: str | None = None
    error_message: str | None = None
    observation_type: str = "span"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunTraceRecord:
    record_type: str
    run_id: str
    thread_id: str
    started_at: str
    ended_at: str
    latency_ms: float
    query: str
    routed_intent: str
    status: Literal["success", "failed"]
    total_steps: int
    used_tools: list[str]
    generated_sql: str
    retry_count: int
    fallback_used: bool
    error_categories: list[str]
    total_token_usage: int | None = None
    final_confidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

