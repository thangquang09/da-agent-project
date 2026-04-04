"""Result Store — persist SQL query results for reuse and token-efficient synthesis.

Stores results in PostgreSQL with:
- sample_rows: top 10 rows (JSONB) for synthesis prompts
- summary_stats: per-column stats (min, max, avg for numeric columns)
- full_data_path: external file path for large results (row_count > 100)
- TTL-based expiration with lazy cleanup
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.config import load_settings
from app.logger import logger

FULL_DATA_THRESHOLD = 100
DEFAULT_TTL_HOURS = 24
RESULTS_DIR = Path(__file__).parent.parent.parent / "data" / "results"


class ResultStore:
    def __init__(self) -> None:
        """Initialize ResultStore with PostgreSQL connection from settings."""
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    def _get_connection(self):
        """Get a new PostgreSQL connection."""
        settings = load_settings()
        return psycopg.connect(settings.database_url)

    def _ensure_table_exists(self) -> None:
        """Ensure the result_store table exists in PostgreSQL."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS result_store (
                    result_id TEXT PRIMARY KEY,
                    run_id TEXT,
                    thread_id TEXT,
                    sql TEXT,
                    db_path TEXT,
                    row_count INTEGER,
                    columns JSONB,
                    sample_rows JSONB,
                    summary_stats JSONB,
                    full_data_path TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    expires_at TIMESTAMPTZ
                );

                CREATE INDEX IF NOT EXISTS idx_result_store_expires_at ON result_store(expires_at);
                CREATE INDEX IF NOT EXISTS idx_result_store_run_id ON result_store(run_id);
            """)
            # Create index on auto-expired results cleanup
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_result_store_created_at
                ON result_store(created_at);
            """)

    def save_result(
        self,
        sql: str,
        sql_result: dict[str, Any],
        run_id: str | None = None,
        thread_id: str | None = None,
        db_path: str | None = None,
        ttl_hours: int = DEFAULT_TTL_HOURS,
    ) -> dict[str, Any]:
        """Persist SQL result and return a lightweight reference."""
        # Ensure table exists on first use
        self._ensure_table_exists()

        result_id = str(uuid.uuid4())
        rows = sql_result.get("rows", [])
        row_count = sql_result.get("row_count", len(rows))
        columns = sql_result.get("columns", [])

        sample_rows = rows[:10]

        stats = self._compute_summary_stats(rows, columns)

        columns_json = Jsonb(columns)
        sample_json = Jsonb(sample_rows)
        stats_json = Jsonb(stats)

        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
        full_data_path: str | None = None

        if row_count > FULL_DATA_THRESHOLD:
            full_data_path = self._save_full_data(result_id, rows)

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO result_store
                    (result_id, run_id, thread_id, sql, db_path, row_count,
                     columns, sample_rows, summary_stats, full_data_path, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    result_id,
                    run_id,
                    thread_id,
                    sql,
                    db_path,
                    row_count,
                    columns_json,
                    sample_json,
                    stats_json,
                    full_data_path,
                    expires_at,
                ),
            )

        logger.info(
            "Saved result: id={id}, rows={rows}, has_full={full}",
            id=result_id[:8],
            rows=row_count,
            full=bool(full_data_path),
        )

        return {
            "result_id": result_id,
            "row_count": row_count,
            "columns": columns,
            "sample": sample_rows,
            "stats": stats,
            "has_full_data": bool(full_data_path),
            "full_data_path": full_data_path,
        }

    def _compute_summary_stats(
        self, rows: list[dict[str, Any]], columns: list[str]
    ) -> dict[str, Any]:
        """Compute per-column summary stats (min, max, avg for numeric columns)."""
        if not rows:
            return {}

        stats: dict[str, Any] = {}
        for col in columns:
            values = [r.get(col) for r in rows if r.get(col) is not None]
            if not values:
                continue

            numeric_values = []
            for v in values:
                try:
                    numeric_values.append(float(v))
                except (ValueError, TypeError):
                    pass

            if numeric_values:
                stats[col] = {
                    "min": min(numeric_values),
                    "max": max(numeric_values),
                    "avg": sum(numeric_values) / len(numeric_values),
                    "count": len(numeric_values),
                    "type": "numeric",
                }
            else:
                stats[col] = {
                    "count": len(values),
                    "type": "non_numeric",
                }

        return stats

    def _save_full_data(self, result_id: str, rows: list[dict[str, Any]]) -> str:
        """Save full result rows to external JSON file."""
        thread_dir = RESULTS_DIR / result_id[:8]
        thread_dir.mkdir(parents=True, exist_ok=True)
        file_path = thread_dir / f"{result_id}.json"

        with open(file_path, "w") as f:
            json.dump(rows, f, default=str)

        return str(file_path)


_instance: ResultStore | None = None
_lock = threading.Lock()


def get_result_store() -> ResultStore:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = ResultStore()
    return _instance
