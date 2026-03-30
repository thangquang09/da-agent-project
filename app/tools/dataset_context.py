from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import load_settings
from app.logger import logger
from app.tools.get_schema import describe_table, list_tables


DEFAULT_SAMPLE_ROWS = 3
DEFAULT_TOP_VALUES = 3


@dataclass(frozen=True)
class TableSample:
    table_name: str
    row_count: int
    min_max_dates: dict[str, tuple[str | None, str | None]]
    top_values: dict[str, list[dict[str, Any]]]
    sample_rows: list[dict[str, Any]]
    columns: list[dict[str, Any]]


def _default_db_path() -> Path:
    return Path(load_settings().sqlite_db_path)


def _is_date_like(column_name: str) -> bool:
    lower = column_name.lower()
    return "date" in lower or lower.endswith("_at")


def _is_categorical(col_type: str) -> bool:
    upper = col_type.upper()
    return "CHAR" in upper or "TEXT" in upper


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_identifier(name: str) -> str:
    """Whitelist SQL identifiers (table/column names) to avoid injection via f-strings."""
    cleaned = name.strip().replace('"', "")
    if not _IDENTIFIER_PATTERN.match(cleaned):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return cleaned


def _fetch_sample_rows(conn: sqlite3.Connection, table: str, limit: int) -> list[dict[str, Any]]:
    safe_table = _safe_identifier(table)
    cur = conn.execute(f'SELECT * FROM "{safe_table}" LIMIT {limit}')
    return [dict(row) for row in cur.fetchall()]


def _fetch_row_count(conn: sqlite3.Connection, table: str) -> int:
    safe_table = _safe_identifier(table)
    cur = conn.execute(f'SELECT COUNT(*) as cnt FROM "{safe_table}"')
    return int(cur.fetchone()[0])


def _fetch_min_max_dates(conn: sqlite3.Connection, table: str, date_columns: list[str]) -> dict[str, tuple[str | None, str | None]]:
    safe_table = _safe_identifier(table)
    stats: dict[str, tuple[str | None, str | None]] = {}
    for col in date_columns:
        safe_col = _safe_identifier(col)
        cur = conn.execute(f'SELECT MIN("{safe_col}"), MAX("{safe_col}") FROM "{safe_table}"')
        min_val, max_val = cur.fetchone()
        stats[col] = (min_val, max_val)
    return stats


def _fetch_top_values(conn: sqlite3.Connection, table: str, cat_columns: list[str], top_k: int) -> dict[str, list[dict[str, Any]]]:
    safe_table = _safe_identifier(table)
    results: dict[str, list[dict[str, Any]]] = {}
    for col in cat_columns:
        safe_col = _safe_identifier(col)
        cur = conn.execute(
            f'SELECT "{safe_col}" as value, COUNT(*) as cnt '
            f'FROM "{safe_table}" '
            f'GROUP BY "{safe_col}" '
            f'ORDER BY cnt DESC '
            f'LIMIT {top_k}'
        )
        results[col] = [dict(row) for row in cur.fetchall()]
    return results


def dataset_context(
    db_path: Path | None = None,
    *,
    sample_rows: int = DEFAULT_SAMPLE_ROWS,
    top_values: int = DEFAULT_TOP_VALUES,
    allowed_tables: list[str] | None = None,
) -> dict[str, Any]:
    path = db_path or _default_db_path()
    tables = allowed_tables or list_tables(db_path=path)
    payload: list[dict[str, Any]] = []

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        for table in tables:
            columns = describe_table(table, db_path=path)
            row_count = _fetch_row_count(conn, table)
            date_cols = [col.name for col in columns if _is_date_like(col.name)]
            cat_cols = [col.name for col in columns if _is_categorical(col.col_type)]
            min_max = _fetch_min_max_dates(conn, table, date_cols) if date_cols else {}
            top_vals = _fetch_top_values(conn, table, cat_cols, top_values) if cat_cols else {}
            samples = _fetch_sample_rows(conn, table, sample_rows)

            payload.append(
                {
                    "table_name": table,
                    "row_count": row_count,
                    "columns": [
                        {
                            "name": col.name,
                            "type": col.col_type,
                            "nullable": col.nullable,
                            "is_primary_key": col.is_pk,
                        }
                        for col in columns
                    ],
                    "min_max_dates": min_max,
                    "top_values": top_vals,
                    "sample_rows": samples,
                }
            )

    logger.info(
        "dataset_context collected for {count} tables (samples={sample_rows}, top_values={top_values})",
        count=len(payload),
        sample_rows=sample_rows,
        top_values=top_values,
    )
    return {"tables": payload}

