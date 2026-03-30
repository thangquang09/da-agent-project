from __future__ import annotations

from pathlib import Path
from typing import Any

from app.logger import logger
from app.tools import (
    SQLValidationResult,
    dataset_context,
    get_schema_overview,
    query_sql,
    retrieve_metric_definition,
    validate_sql,
)
from mcp_server.config import load_mcp_config
from mcp_server.schemas import DatasetContextResponse, QuerySQLResponse, SchemaTable


def _resolve_db_path(db_path: str | None) -> Path:
    cfg = load_mcp_config()
    return Path(db_path) if db_path else cfg.db_path


def tool_get_schema(db_path: str | None = None) -> dict[str, Any]:
    overview = get_schema_overview(db_path=_resolve_db_path(db_path))
    return overview


def tool_dataset_context(db_path: str | None = None) -> DatasetContextResponse:
    cfg = load_mcp_config()
    return dataset_context(
        db_path=_resolve_db_path(db_path),
        sample_rows=cfg.sample_rows,
        top_values=cfg.top_values,
    )


def tool_retrieve_metric_definition(query: str, top_k: int = 4) -> dict[str, Any]:
    return retrieve_metric_definition(query=query, top_k=top_k)


def tool_query_sql(sql: str, row_limit: int | None = None, db_path: str | None = None) -> QuerySQLResponse:
    cfg = load_mcp_config()
    resolved_db_path = _resolve_db_path(db_path)
    validation: SQLValidationResult = validate_sql(sql, db_path=resolved_db_path, max_limit=row_limit or cfg.max_limit)
    if not validation.is_valid:
        logger.warning("SQL rejected by validator", reasons=validation.reasons)
        return {
            "rows": [],
            "row_count": 0,
            "columns": [],
            "latency_ms": 0.0,
            "sanitized_sql": validation.sanitized_sql,
            "validation_reasons": validation.reasons,
        }

    result = query_sql(validation.sanitized_sql, db_path=resolved_db_path)
    return {
        **result,
        "sanitized_sql": validation.sanitized_sql,
        "validation_reasons": validation.reasons,
    }
