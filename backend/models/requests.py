from __future__ import annotations

from pydantic import BaseModel, Field


class FileUpload(BaseModel):
    """A single file sent as base64-encoded content (for JSON body uploads)."""

    name: str
    data: str  # base64-encoded bytes
    context: str | None = None  # optional user-provided business context for this table


class QueryRequest(BaseModel):
    """Request body for POST /query."""

    query: str = Field(..., min_length=1, max_length=4096)
    thread_id: str | None = None
    user_semantic_context: str | None = None
    uploaded_file_data: list[FileUpload] | None = None
    recursion_limit: int = Field(default=25, ge=1, le=50)
    version: str = Field(default="v2", pattern="^(v1|v2|v3)$")
