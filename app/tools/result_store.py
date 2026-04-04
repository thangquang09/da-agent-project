"""Result Store — persist SQL query results for reuse and token-efficient synthesis.

Stores results in SQLite with:
- sample_rows: top 10 rows (JSON) for synthesis prompts
- summary_stats: per-column stats (min, max, avg for numeric columns)
- full_data_path: external file path for large results (row_count > 100)
- TTL-based expiration with lazy cleanup
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.logger import logger
from app.utils.json_serializer import safe_json_dumps, safe_json_loads

FULL_DATA_THRESHOLD = 100
DEFAULT_TTL_HOURS = 24
RESULTS_DIR = Path(__file__).parent.parent.parent / "data" / "results"
SQLITE_TIMEOUT_SECONDS = 5.0


class ResultStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            from app.config import load_settings

            db_path = load_settings().sqlite_db_path
        self.db_path = Path(db_path)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

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
        result_id = str(uuid.uuid4())
        rows = sql_result.get("rows", [])
        row_count = sql_result.get("row_count", len(rows))
        columns = sql_result.get("columns", [])

        sample_rows = rows[:10]
        sample_json = safe_json_dumps(sample_rows)

        stats = self._compute_summary_stats(rows, columns)
        stats_json = safe_json_dumps(stats)

        columns_json = safe_json_dumps(columns)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
        full_data_path: str | None = None

        if row_count > FULL_DATA_THRESHOLD:
            full_data_path = self._save_full_data(result_id, rows)

        conn = sqlite3.connect(str(self.db_path), timeout=SQLITE_TIMEOUT_SECONDS)
        try:
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.execute(
                """
                INSERT INTO result_store
                    (result_id, run_id, thread_id, sql, db_path, row_count,
                     columns, sample_rows, summary_stats, full_data_path, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    expires_at.isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

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

    def get_result(self, result_id: str) -> dict[str, Any] | None:
        """Fetch a stored result by ID. Returns None if expired or not found.

        Deletes expired rows on read to prevent stale data accumulation.
        """
        conn = sqlite3.connect(str(self.db_path), timeout=SQLITE_TIMEOUT_SECONDS)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout = 5000")
            row = conn.execute(
                "SELECT * FROM result_store WHERE result_id = ?", (result_id,)
            ).fetchone()

            if not row:
                return None

            if row["expires_at"]:
                expires = datetime.fromisoformat(row["expires_at"])
                if expires < datetime.now(timezone.utc):
                    conn.execute(
                        "DELETE FROM result_store WHERE result_id = ?", (result_id,)
                    )
                    conn.commit()
                    logger.info(
                        "Deleted expired result on read: id={id}", id=result_id[:8]
                    )
                    return None
        finally:
            conn.close()

        result = {
            "result_id": row["result_id"],
            "sql": row["sql"],
            "row_count": row["row_count"],
            "columns": safe_json_loads(row["columns"]) if row["columns"] else [],
            "sample": safe_json_loads(row["sample_rows"]) if row["sample_rows"] else [],
            "stats": safe_json_loads(row["summary_stats"])
            if row["summary_stats"]
            else {},
            "full_data_path": row["full_data_path"],
        }

        if row["full_data_path"]:
            full_path = Path(row["full_data_path"])
            if full_path.exists():
                with open(full_path) as f:
                    result["full_rows"] = safe_json_loads(f.read())

        return result

    def get_last_result(self, thread_id: str) -> dict[str, Any] | None:
        """Get the most recent non-expired result for a thread."""
        conn = sqlite3.connect(str(self.db_path), timeout=SQLITE_TIMEOUT_SECONDS)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout = 5000")
            row = conn.execute(
                """
                SELECT * FROM result_store
                WHERE thread_id = ?
                  AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (thread_id, datetime.now(timezone.utc).isoformat()),
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return None

        return {
            "result_id": row["result_id"],
            "sql": row["sql"],
            "row_count": row["row_count"],
            "columns": safe_json_loads(row["columns"]) if row["columns"] else [],
            "sample": safe_json_loads(row["sample_rows"]) if row["sample_rows"] else [],
            "stats": safe_json_loads(row["summary_stats"])
            if row["summary_stats"]
            else {},
            "full_data_path": row["full_data_path"],
        }

    def cleanup_expired(self) -> int:
        """Remove expired entries and their full data files. Returns count deleted."""
        cutoff = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(str(self.db_path), timeout=SQLITE_TIMEOUT_SECONDS)
        try:
            conn.execute("PRAGMA busy_timeout = 5000")
            rows = conn.execute(
                """
                SELECT result_id, full_data_path FROM result_store
                WHERE expires_at IS NOT NULL AND expires_at < ?
                """,
                (cutoff,),
            ).fetchall()

            for row in rows:
                if row[1]:
                    path = Path(row[1])
                    if path.exists():
                        path.unlink()
                    dir_path = path.parent
                    if dir_path.exists() and not any(dir_path.iterdir()):
                        dir_path.rmdir()

            cursor = conn.execute(
                "DELETE FROM result_store WHERE expires_at IS NOT NULL AND expires_at < ?",
                (cutoff,),
            )
            conn.commit()
            deleted = cursor.rowcount
        finally:
            conn.close()

        if deleted:
            logger.info("Cleaned up {count} expired results", count=deleted)
        return deleted

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
            f.write(safe_json_dumps(rows))

        return str(file_path)


_instance: ResultStore | None = None
_lock = threading.Lock()


def get_result_store(db_path: str | Path | None = None) -> ResultStore:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = ResultStore(db_path=db_path)
    return _instance
