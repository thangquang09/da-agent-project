from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from app.config import load_settings
from app.logger import logger


def _default_db_path() -> Path:
    return Path(load_settings().sqlite_db_path)


def query_sql(sql: str, db_path: Path | None = None) -> dict[str, Any]:
    path = db_path or _default_db_path()
    start = time.perf_counter()
    logger.info("Executing SQL query on {path}", path=path)

    with sqlite3.connect(path) as conn:
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

