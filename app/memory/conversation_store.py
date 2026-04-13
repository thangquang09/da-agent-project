from __future__ import annotations

import json
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.config import load_settings
from app.logger import logger


@dataclass(frozen=True)
class ConversationTurn:
    """Single turn in a conversation."""

    thread_id: str
    turn_number: int
    role: str
    content: str
    intent: str | None
    sql_generated: str | None
    result_summary: str | None
    entities: list[str]
    timestamp: str
    last_action_json: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Parse last_action_json from string to dict for API serialization
        if d.get("last_action_json") and isinstance(d["last_action_json"], str):
            try:
                d["last_action_json"] = json.loads(d["last_action_json"])
            except (json.JSONDecodeError, TypeError):
                d["last_action_json"] = None
        return d


@dataclass(frozen=True)
class ConversationSummary:
    """Running summary of a conversation thread."""

    thread_id: str
    summary: str
    turn_count: int
    last_updated: str
    key_entities: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS agent.conversation_memory (
    id SERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    intent TEXT,
    sql_generated TEXT,
    result_summary TEXT,
    entities JSONB DEFAULT '[]',
    timestamp TIMESTAMPTZ NOT NULL,
    last_action_json JSONB,
    UNIQUE(thread_id, turn_number)
);

CREATE INDEX IF NOT EXISTS idx_conv_thread ON agent.conversation_memory(thread_id);
CREATE INDEX IF NOT EXISTS idx_conv_timestamp ON agent.conversation_memory(timestamp);

CREATE TABLE IF NOT EXISTS agent.conversation_summary (
    thread_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    turn_count INTEGER NOT NULL,
    last_updated TIMESTAMPTZ NOT NULL,
    key_entities JSONB DEFAULT '[]'
);
"""


class ConversationMemoryStore:
    """PostgreSQL-backed conversation memory for session continuity.

    Stores conversation turns and summaries in the ``agent`` schema.
    Each operation opens a short-lived connection from psycopg (thread-safe).
    """

    def __init__(self, db_url: str | None = None):
        self._db_url = db_url
        self._ensure_tables()

    def _get_connection(self):
        url = self._db_url or load_settings().database_url
        return psycopg.connect(url)

    def _ensure_tables(self) -> None:
        """Create agent schema + tables if they don't exist."""
        # First ensure schemas exist
        from data.migrations.create_schemas import run as ensure_schemas

        ensure_schemas()

        with self._get_connection() as conn:
            conn.execute(_CREATE_TABLES_SQL)
            conn.commit()
        logger.info("Conversation memory store initialized (PostgreSQL)")

    def close(self) -> None:
        """No-op — connections are short-lived."""
        pass

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def save_turn(self, turn: ConversationTurn) -> int:
        """Save a conversation turn. Returns the record id."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO agent.conversation_memory (
                    thread_id, turn_number, role, content, intent,
                    sql_generated, result_summary, entities, timestamp, last_action_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    turn.thread_id,
                    turn.turn_number,
                    turn.role,
                    turn.content,
                    turn.intent,
                    turn.sql_generated,
                    turn.result_summary,
                    Jsonb(turn.entities),
                    turn.timestamp,
                    Jsonb(json.loads(turn.last_action_json)) if turn.last_action_json else None,
                ),
            )
            record_id = cursor.fetchone()[0]
            conn.commit()
        logger.debug(
            "Saved conversation turn: thread={thread}, turn={turn}",
            thread=turn.thread_id,
            turn=turn.turn_number,
        )
        return record_id

    def get_recent_turns(
        self, thread_id: str, limit: int = 10
    ) -> list[ConversationTurn]:
        """Get recent turns for a conversation thread in chronological order."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM agent.conversation_memory
                WHERE thread_id = %s
                ORDER BY turn_number DESC
                LIMIT %s
                """,
                (thread_id, limit),
            )
            rows = cursor.fetchall()

        turns = [
            ConversationTurn(
                thread_id=row[1],
                turn_number=row[2],
                role=row[3],
                content=row[4],
                intent=row[5],
                sql_generated=row[6],
                result_summary=row[7],
                entities=row[8] if row[8] else [],
                timestamp=row[9].isoformat() if hasattr(row[9], "isoformat") else str(row[9]),
                last_action_json=json.dumps(row[10]) if row[10] else None,
            )
            for row in reversed(rows)
        ]
        return turns

    def get_turn_count(self, thread_id: str) -> int:
        """Get total number of turns for a thread."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) as cnt FROM agent.conversation_memory WHERE thread_id = %s",
                (thread_id,),
            )
            result = cursor.fetchone()
        return result[0] if result else 0

    def get_next_turn_number(self, thread_id: str) -> int:
        """Return the next monotonic turn number for a thread.

        This uses ``MAX(turn_number)`` instead of ``COUNT(*)`` so numbering
        remains unique even after old turns are pruned during compaction.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT COALESCE(MAX(turn_number), 0)
                FROM agent.conversation_memory
                WHERE thread_id = %s
                """,
                (thread_id,),
            )
            result = cursor.fetchone()
        return (result[0] if result else 0) + 1

    def update_summary(self, summary: ConversationSummary) -> None:
        """Upsert conversation summary."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO agent.conversation_summary (thread_id, summary, turn_count, last_updated, key_entities)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT(thread_id) DO UPDATE SET
                    summary = EXCLUDED.summary,
                    turn_count = EXCLUDED.turn_count,
                    last_updated = EXCLUDED.last_updated,
                    key_entities = EXCLUDED.key_entities
                """,
                (
                    summary.thread_id,
                    summary.summary,
                    summary.turn_count,
                    summary.last_updated,
                    Jsonb(summary.key_entities),
                ),
            )
            conn.commit()
        logger.debug(
            "Updated conversation summary: thread={thread}, turns={count}",
            thread=summary.thread_id,
            count=summary.turn_count,
        )

    def get_summary(self, thread_id: str) -> ConversationSummary | None:
        """Get conversation summary for a thread."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM agent.conversation_summary WHERE thread_id = %s",
                (thread_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        return ConversationSummary(
            thread_id=row[0],
            summary=row[1],
            turn_count=row[2],
            last_updated=row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]),
            key_entities=row[4] if row[4] else [],
        )

    def delete_old_turns(self, thread_id: str, keep_last_n: int) -> int:
        """Delete old turns, keeping the most recent *keep_last_n* turns.

        Returns the number of rows deleted.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM agent.conversation_memory
                WHERE thread_id = %s AND id NOT IN (
                    SELECT id FROM agent.conversation_memory
                    WHERE thread_id = %s
                    ORDER BY turn_number DESC
                    LIMIT %s
                )
                """,
                (thread_id, thread_id, keep_last_n),
            )
            deleted = cursor.rowcount
            conn.commit()
        if deleted:
            logger.info(
                "Pruned {deleted} old turns for thread={thread} (kept last {keep})",
                deleted=deleted,
                thread=thread_id,
                keep=keep_last_n,
            )
        return deleted

    def list_threads(self, limit: int = 50) -> list[dict[str, Any]]:
        """List all conversation threads, ordered by most recently updated.

        Queries conversation_memory directly for turn counts and timestamps,
        then left-joins conversation_summary for summary data. Falls back to
        the first user message as a preview when no summary exists.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT
                    m.thread_id,
                    s.summary,
                    m.turn_count,
                    m.last_updated,
                    COALESCE(s.key_entities, '[]') AS key_entities,
                    preview.first_content
                FROM (
                    SELECT
                        thread_id,
                        COUNT(*) AS turn_count,
                        MAX(timestamp) AS last_updated
                    FROM agent.conversation_memory
                    GROUP BY thread_id
                ) m
                LEFT JOIN agent.conversation_summary s
                    ON m.thread_id = s.thread_id
                LEFT JOIN (
                    SELECT DISTINCT ON (thread_id)
                        thread_id,
                        content AS first_content
                    FROM agent.conversation_memory
                    WHERE role = 'user'
                    ORDER BY thread_id, turn_number ASC
                ) preview ON m.thread_id = preview.thread_id
                ORDER BY m.last_updated DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()

        return [
            {
                "thread_id": row[0],
                "summary": row[1] or (row[5][:120] + ("..." if row[5] and len(row[5]) > 120 else "") if row[5] else None),
                "turn_count": row[2],
                "last_updated": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]),
                "key_entities": row[4] if row[4] else [],
            }
            for row in rows
        ]

    def clear_thread(self, thread_id: str) -> None:
        """Clear all memory for a thread (useful for testing)."""
        with self._get_connection() as conn:
            conn.execute(
                "DELETE FROM agent.conversation_memory WHERE thread_id = %s",
                (thread_id,),
            )
            conn.execute(
                "DELETE FROM agent.conversation_summary WHERE thread_id = %s",
                (thread_id,),
            )
            conn.commit()
        # Also clear artifacts in a separate connection (table may not exist on first run)
        try:
            with self._get_connection() as conn2:
                conn2.execute(
                    "DELETE FROM agent.turn_artifacts WHERE thread_id = %s",
                    (thread_id,),
                )
                conn2.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to clear artifacts for thread {thread}: {error}", thread=thread_id, error=str(exc))
        logger.info("Cleared conversation memory: thread={thread}", thread=thread_id)


# ---------------------------------------------------------------------------
# Thread-safe singleton
# ---------------------------------------------------------------------------

_conversation_memory_store: ConversationMemoryStore | None = None
_singleton_lock = threading.Lock()


def get_conversation_memory_store() -> ConversationMemoryStore:
    """Get or create conversation memory store singleton (thread-safe)."""
    global _conversation_memory_store
    if _conversation_memory_store is None:
        with _singleton_lock:
            if _conversation_memory_store is None:
                _conversation_memory_store = ConversationMemoryStore()
    return _conversation_memory_store


def reset_conversation_memory_store() -> None:
    """Reset the singleton (useful for testing)."""
    global _conversation_memory_store
    with _singleton_lock:
        if _conversation_memory_store is not None:
            _conversation_memory_store.close()
        _conversation_memory_store = None
