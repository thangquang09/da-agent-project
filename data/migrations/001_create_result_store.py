"""
Migration 001: Create result_store table for persisting SQL query results.

This enables:
- Cross-session result reuse (avoid re-executing same queries)
- Token-efficient synthesis (pass sample + stats instead of full rows)
- Visualization rerun without SQL re-execution
- Downloadable full results for large datasets
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SQL = """
CREATE TABLE IF NOT EXISTS result_store (
    result_id      TEXT PRIMARY KEY,
    run_id         TEXT,
    thread_id      TEXT,
    sql            TEXT NOT NULL,
    db_path        TEXT,
    row_count      INTEGER DEFAULT 0,
    columns        TEXT,
    sample_rows    TEXT,
    summary_stats  TEXT,
    full_data_path TEXT,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at     TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_result_store_thread ON result_store(thread_id);
CREATE INDEX IF NOT EXISTS idx_result_store_expires ON result_store(expires_at);
"""


def migrate(db_path: Path | str | None = None) -> None:
    """Run the migration."""
    if db_path is None:
        from app.config import load_settings

        db_path = Path(load_settings().sqlite_db_path)
    else:
        db_path = Path(db_path)

    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SQL)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
    print("Migration 001 applied: result_store table created")
