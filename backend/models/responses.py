from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class VisualizationResponse(BaseModel):
    """Mirrors the VisualizationSpec TypedDict from app/graph/state.py."""

    success: bool = False
    image_data: str | None = None  # base64-encoded PNG
    image_format: str = "png"
    execution_time_ms: float = 0.0
    error: str | None = None


class QueryResponse(BaseModel):
    """
    HTTP response shape for all query endpoints.

    Mirrors the dict returned by app.main.run_query(). Every field has a
    safe default because AnswerPayload is TypedDict(total=False).
    """

    run_id: str = ""
    thread_id: str = ""
    answer: str = ""
    intent: str = "unknown"
    intent_reason: str = ""
    confidence: str = "low"
    used_tools: list[str] = []
    generated_sql: str = ""
    evidence: list[str] = []
    error_categories: list[str] = []
    tool_history: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    total_token_usage: int | None = None
    total_cost_usd: float | None = None
    context_type: str = "default"
    visualization: VisualizationResponse | None = None
    rows: int | None = None
    context_chunks: int | None = None
    step_count: int = 0


class ThreadInfo(BaseModel):
    """Summary info for a conversation thread."""

    thread_id: str
    turn_count: int
    summary: str | None = None
    last_updated: str | None = None
    key_entities: list[str] = []


class ConversationTurnResponse(BaseModel):
    """Single conversation turn returned from history endpoint."""

    thread_id: str
    turn_number: int
    role: str
    content: str
    intent: str | None = None
    sql_generated: str | None = None
    result_summary: str | None = None
    entities: list[str] = []
    timestamp: str


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    graph_version: str = "v2"


class EvalRunResponse(BaseModel):
    message: str
    status: str = "started"
