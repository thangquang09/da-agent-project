from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class VisualizationResponse(BaseModel):
    """Mirrors the visualization dict from AgentState.

    image_url is a path like /artifacts/{thread_id}/{turn}/chart_xxx.png
    that the frontend can use directly in <img src={...}>.
    """

    success: bool = False
    image_url: str | None = None
    image_format: str = "png"
    image_size_bytes: int | None = None
    execution_time_ms: float = 0.0
    error: str | None = None


class ReportSectionResponse(BaseModel):
    section_id: str = ""
    title: str = ""
    insight_markdown: str = ""
    chart_image: VisualizationResponse | None = None
    chart_manifest: dict[str, Any] | None = None
    limitations: list[str] = []
    analysis_type: str = "descriptive"
    semantic_warnings: list[str] = []
    section_confidence: str = "medium"


class QueryResponse(BaseModel):
    """
    HTTP response shape for all query endpoints.

    Mirrors the dict returned by app.main.run_query(). Every field has a
    safe default because AnswerPayload is TypedDict(total=False).
    """

    run_id: str = ""
    thread_id: str = ""
    answer: str = ""
    report_markdown: str | None = None
    report_sections: list[ReportSectionResponse] = []
    intent: str = "unknown"
    intent_reason: str = ""
    response_mode: str = "answer"
    confidence: str = "low"
    confidence_rationale: str | None = None
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
    visualizations: list[VisualizationResponse] = []
    rows: int | None = None
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
    last_action_json: dict[str, Any] | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    graph_version: str = "v3"


class TurnArtifactResponse(BaseModel):
    """Persisted artifact (report, chart) for a conversation turn.

    payload now contains metadata and file references only — never binary data.
    """

    thread_id: str
    turn_number: int
    artifact_type: str
    payload: dict[str, Any] = {}


class EvalRunResponse(BaseModel):
    message: str
    status: str = "started"
