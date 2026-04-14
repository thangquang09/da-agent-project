from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from app.config import load_settings
from app.logger import logger

_CREATE_TABLE_SQL = """
CREATE SCHEMA IF NOT EXISTS user_data;

CREATE TABLE IF NOT EXISTS user_data.table_contexts (
    table_name VARCHAR PRIMARY KEY,
    business_context TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    user_id VARCHAR NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""

_MIGRATE_ADD_USER_ID = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'user_data'
          AND table_name = 'table_contexts'
          AND column_name = 'user_id'
    ) THEN
        ALTER TABLE user_data.table_contexts ADD COLUMN user_id VARCHAR NOT NULL DEFAULT '';
        CREATE INDEX IF NOT EXISTS idx_table_contexts_user_id ON user_data.table_contexts(user_id);
    END IF;
END$$;
"""

_MIGRATE_ADD_CREATED_AT = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'user_data'
          AND table_name = 'table_contexts'
          AND column_name = 'created_at'
    ) THEN
        ALTER TABLE user_data.table_contexts ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW();
    END IF;
END$$;
"""


def _ensure_table() -> None:
    """Create user_data.table_contexts if it doesn't exist, and run migrations."""
    settings = load_settings()
    with psycopg.connect(settings.database_url) as conn:
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(_MIGRATE_ADD_USER_ID)
        conn.execute(_MIGRATE_ADD_CREATED_AT)


def get_table_context(table_name: str) -> str:
    """Get business context for a single table. Returns empty string if not found."""
    _ensure_table()
    settings = load_settings()
    with psycopg.connect(settings.database_url) as conn:
        conn.row_factory = dict_row
        cur = conn.execute(
            "SELECT business_context FROM user_data.table_contexts WHERE table_name = %s",
            (table_name,),
        )
        row = cur.fetchone()
        return row["business_context"] if row else ""


def set_table_context(table_name: str, context: str, user_id: str = "") -> None:
    """Upsert business context for a table, optionally scoped to a user_id.

    On conflict, ``updated_at`` is refreshed but ``created_at`` is preserved
    so the TTL timer keeps counting from the original upload time.
    """
    _ensure_table()
    settings = load_settings()
    with psycopg.connect(settings.database_url) as conn:
        conn.execute(
            """
            INSERT INTO user_data.table_contexts (table_name, business_context, updated_at, user_id, created_at)
            VALUES (%s, %s, NOW(), %s, NOW())
            ON CONFLICT (table_name)
            DO UPDATE SET
                business_context = EXCLUDED.business_context,
                updated_at = NOW(),
                user_id = EXCLUDED.user_id
            """,
            (table_name, context, user_id),
        )
    logger.info(
        "Saved context for table={table} user_id={uid} ({len} chars)",
        table=table_name,
        uid=user_id,
        len=len(context),
    )


def get_all_table_contexts(user_id: str | None = None) -> dict[str, str]:
    """Get all table contexts as a dict. Optionally filter by user_id.

    Returns {table_name: business_context}.
    """
    _ensure_table()
    settings = load_settings()
    with psycopg.connect(settings.database_url) as conn:
        conn.row_factory = dict_row
        if user_id is not None:
            cur = conn.execute(
                "SELECT table_name, business_context FROM user_data.table_contexts WHERE user_id = %s",
                (user_id,),
            )
        else:
            cur = conn.execute(
                "SELECT table_name, business_context FROM user_data.table_contexts"
            )
        return {row["table_name"]: row["business_context"] for row in cur.fetchall()}


def delete_table_context(table_name: str) -> None:
    """Remove context entry for a table (call when table is dropped)."""
    _ensure_table()
    settings = load_settings()
    with psycopg.connect(settings.database_url) as conn:
        conn.execute(
            "DELETE FROM user_data.table_contexts WHERE table_name = %s",
            (table_name,),
        )


def count_user_tables(user_id: str) -> int:
    """Count how many tables are registered under a given user_id."""
    _ensure_table()
    settings = load_settings()
    with psycopg.connect(settings.database_url) as conn:
        conn.row_factory = dict_row
        cur = conn.execute(
            "SELECT COUNT(*) AS cnt FROM user_data.table_contexts WHERE user_id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        return int(row["cnt"]) if row else 0


def get_user_table_names(user_id: str) -> list[str]:
    """Return list of table names owned by user_id."""
    _ensure_table()
    settings = load_settings()
    with psycopg.connect(settings.database_url) as conn:
        conn.row_factory = dict_row
        cur = conn.execute(
            "SELECT table_name FROM user_data.table_contexts WHERE user_id = %s ORDER BY updated_at",
            (user_id,),
        )
        return [row["table_name"] for row in cur.fetchall()]


def delete_all_user_contexts(user_id: str) -> int:
    """Delete all table_context entries for a user. Returns number of deleted rows."""
    _ensure_table()
    settings = load_settings()
    with psycopg.connect(settings.database_url) as conn:
        cur = conn.execute(
            "DELETE FROM user_data.table_contexts WHERE user_id = %s",
            (user_id,),
        )
        deleted = cur.rowcount or 0
    logger.info("Deleted {n} table contexts for user_id={uid}", n=deleted, uid=user_id)
    return deleted


# ---------------------------------------------------------------------------
# TTL cleanup
# ---------------------------------------------------------------------------

TABLE_TTL_HOURS = 2


def cleanup_expired_tables(ttl_hours: int = TABLE_TTL_HOURS) -> int:
    """Drop all user tables whose ``created_at`` exceeds the TTL.

    Scans ``user_data.table_contexts`` for rows older than *ttl_hours*,
    drops the corresponding PostgreSQL tables, and removes the context rows.
    Called lazily from API endpoints — not a cron job.

    Returns the number of expired tables cleaned up.
    """
    _ensure_table()
    settings = load_settings()
    with psycopg.connect(settings.database_url) as conn:
        conn.row_factory = dict_row
        cur = conn.execute(
            """
            SELECT table_name FROM user_data.table_contexts
            WHERE created_at < NOW() - INTERVAL '%s hours'
            """,
            (ttl_hours,),
        )
        expired = [row["table_name"] for row in cur.fetchall()]

    if not expired:
        return 0

    dropped: list[str] = []
    with psycopg.connect(settings.database_url) as conn:
        for table_name in expired:
            try:
                conn.execute(f'DROP TABLE IF EXISTS public."{table_name}" CASCADE')
                dropped.append(table_name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("TTL cleanup failed to drop {t}: {e}", t=table_name, e=str(exc))

        # Remove contexts for all expired tables (even if drop failed)
        for table_name in expired:
            conn.execute("DELETE FROM user_data.table_contexts WHERE table_name = %s", (table_name,))
        conn.commit()

    logger.info(
        "TTL cleanup: expired={total} dropped={dropped} ttl={h}h",
        total=len(expired),
        dropped=len(dropped),
        h=ttl_hours,
    )
    return len(dropped)
