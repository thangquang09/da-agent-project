from __future__ import annotations

from typing import Any, TypedDict


class SchemaColumn(TypedDict):
    name: str
    type: str
    nullable: bool
    is_primary_key: bool


class SchemaTable(TypedDict):
    table_name: str
    columns: list[SchemaColumn]


class DatasetContextTable(TypedDict):
    table_name: str
    row_count: int
    columns: list[SchemaColumn]
    min_max_dates: dict[str, tuple[str | None, str | None]]
    top_values: dict[str, list[dict[str, Any]]]
    sample_rows: list[dict[str, Any]]


class DatasetContextResponse(TypedDict):
    tables: list[DatasetContextTable]


class QuerySQLRequest(TypedDict, total=False):
    sql: str
    row_limit: int


class QuerySQLResponse(TypedDict):
    rows: list[dict[str, Any]]
    row_count: int
    columns: list[str]
    latency_ms: float
    sanitized_sql: str
    validation_reasons: list[str]

