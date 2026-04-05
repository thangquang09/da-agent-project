from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.config import load_settings
from app.logger import logger


def _query_postgres(sql: str) -> dict[str, Any]:
    """Execute SQL query on PostgreSQL database."""
    settings = load_settings()
    start = time.perf_counter()
    logger.info("Executing SQL query on PostgreSQL")

    with psycopg.connect(settings.database_url) as conn:
        conn.row_factory = dict_row
        cur = conn.execute(sql)
        rows = cur.fetchall()
        # Get column names from cursor description
        columns = [desc.name for desc in cur.description] if cur.description else []

    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "SQL query completed (rows={row_count}, latency_ms={latency})",
        row_count=len(rows),
        latency=latency_ms,
    )
    return {
        "rows": rows,
        "row_count": len(rows),
        "columns": columns,
        "latency_ms": latency_ms,
    }


def _query_sqlite(sql: str, db_path: Path) -> dict[str, Any]:
    """Execute SQL query on SQLite database."""
    start = time.perf_counter()
    logger.info("Executing SQL query on {path}", path=db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql)
        rows = [dict(row) for row in cur.fetchall()]
        columns = [desc[0] for desc in cur.description] if cur.description else []

    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "SQL query completed (rows={row_count}, latency_ms={latency})",
        row_count=len(rows),
        latency=latency_ms,
    )
    return {
        "rows": rows,
        "row_count": len(rows),
        "columns": columns,
        "latency_ms": latency_ms,
    }


def query_sql(sql: str, db_path: Path | None = None) -> dict[str, Any]:
    """Execute SQL query on the appropriate database.

    Args:
        sql: SQL query string to execute
        db_path: Optional database path.
            - If Path to .sqlite/.db file: uses SQLite
            - If None: uses PostgreSQL (default)

    Returns:
        Dictionary with rows, row_count, columns, and latency_ms.
    """
    if db_path:
        # Spider evaluation or explicit SQLite path
        return _query_sqlite(sql, db_path)
    else:
        # Default: use PostgreSQL
        return _query_postgres(sql)
