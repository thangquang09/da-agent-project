from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

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
    last_action_json: str | None = None  # JSON-serialized last_action for continuity

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


class ConversationMemoryStore:
    """SQLite-backed conversation memory for session continuity.

    Uses a single persistent connection (both for in-memory and file-based
    databases) to avoid connection leaks. ``row_factory`` is set once at
    creation so every cursor returns ``sqlite3.Row`` objects consistently.
    """

    CREATE_TABLES_SQL = """
    CREATE TABLE IF NOT EXISTS conversation_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT NOT NULL,
        turn_number INTEGER NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        intent TEXT,
        sql_generated TEXT,
        result_summary TEXT,
        entities TEXT,
        timestamp TEXT NOT NULL,
        last_action_json TEXT,
        UNIQUE(thread_id, turn_number)
    );

    CREATE INDEX IF NOT EXISTS idx_conv_thread ON conversation_memory(thread_id);
    CREATE INDEX IF NOT EXISTS idx_conv_timestamp ON conversation_memory(timestamp);

    CREATE TABLE IF NOT EXISTS conversation_summary (
        thread_id TEXT PRIMARY KEY,
        summary TEXT NOT NULL,
        turn_count INTEGER NOT NULL,
        last_updated TEXT NOT NULL,
        key_entities TEXT
    );
    """

    MIGRATE_ADD_LAST_ACTION_SQL = """
    ALTER TABLE conversation_memory ADD COLUMN last_action_json TEXT;
    """

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = (
                Path(__file__).resolve().parents[2]
                / "data"
                / "warehouse"
                / "conversation_memory.db"
            )
        self.db_path = Path(db_path)

        # Single persistent connection for both in-memory and file-based DBs.
        if str(self.db_path) == ":memory:":
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)

        # Set row_factory once at creation to avoid side-effects.
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(self.CREATE_TABLES_SQL)

        # Migration: Add last_action_json column if it doesn't exist
        try:
            self._conn.execute(self.MIGRATE_ADD_LAST_ACTION_SQL)
            self._conn.commit()
            logger.debug("Added last_action_json column to conversation_memory")
        except sqlite3.OperationalError:
            # Column already exists, ignore
            pass

        label = ":memory:" if str(self.db_path) == ":memory:" else str(self.db_path)
        logger.info("Conversation memory store initialized at {path}", path=label)

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Yield the persistent connection (context manager for clarity)."""
        yield self._conn

    def close(self) -> None:
        """Explicitly close the underlying database connection."""
        if self._conn:
            self._conn.close()
            logger.debug("Conversation memory store connection closed")

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001 – best-effort cleanup
            pass

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def save_turn(self, turn: ConversationTurn) -> int:
        """Save a conversation turn."""
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO conversation_memory (
                    thread_id, turn_number, role, content, intent,
                    sql_generated, result_summary, entities, timestamp, last_action_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn.thread_id,
                    turn.turn_number,
                    turn.role,
                    turn.content,
                    turn.intent,
                    turn.sql_generated,
                    turn.result_summary,
                    json.dumps(turn.entities),
                    turn.timestamp,
                    turn.last_action_json,
                ),
            )
            conn.commit()
            record_id = cursor.lastrowid or 0
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
        with self._connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM conversation_memory
                WHERE thread_id = ?
                ORDER BY turn_number DESC
                LIMIT ?
                """,
                (thread_id, limit),
            )
            rows = cursor.fetchall()

        turns = [
            ConversationTurn(
                thread_id=row["thread_id"],
                turn_number=row["turn_number"],
                role=row["role"],
                content=row["content"],
                intent=row["intent"],
                sql_generated=row["sql_generated"],
                result_summary=row["result_summary"],
                entities=json.loads(row["entities"]) if row["entities"] else [],
                timestamp=row["timestamp"],
                last_action_json=row["last_action_json"]
                if "last_action_json" in row.keys()
                else None,
            )
            for row in reversed(rows)
        ]
        return turns

    def get_turn_count(self, thread_id: str) -> int:
        """Get total number of turns for a thread."""
        with self._connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) as cnt FROM conversation_memory WHERE thread_id = ?",
                (thread_id,),
            )
            result = cursor.fetchone()
        return result["cnt"] if result else 0

    def update_summary(self, summary: ConversationSummary) -> None:
        """Upsert conversation summary."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO conversation_summary (thread_id, summary, turn_count, last_updated, key_entities)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    summary = excluded.summary,
                    turn_count = excluded.turn_count,
                    last_updated = excluded.last_updated,
                    key_entities = excluded.key_entities
                """,
                (
                    summary.thread_id,
                    summary.summary,
                    summary.turn_count,
                    summary.last_updated,
                    json.dumps(summary.key_entities),
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
        with self._connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM conversation_summary WHERE thread_id = ?",
                (thread_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        return ConversationSummary(
            thread_id=row["thread_id"],
            summary=row["summary"],
            turn_count=row["turn_count"],
            last_updated=row["last_updated"],
            key_entities=json.loads(row["key_entities"]) if row["key_entities"] else [],
        )

    def delete_old_turns(self, thread_id: str, keep_last_n: int) -> int:
        """Delete old turns, keeping the most recent *keep_last_n* turns.

        Returns the number of rows deleted.
        """
        with self._connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM conversation_memory
                WHERE thread_id = ? AND id NOT IN (
                    SELECT id FROM conversation_memory
                    WHERE thread_id = ?
                    ORDER BY turn_number DESC
                    LIMIT ?
                )
                """,
                (thread_id, thread_id, keep_last_n),
            )
            conn.commit()
            deleted = cursor.rowcount
        if deleted:
            logger.info(
                "Pruned {deleted} old turns for thread={thread} (kept last {keep})",
                deleted=deleted,
                thread=thread_id,
                keep=keep_last_n,
            )
        return deleted

    def clear_thread(self, thread_id: str) -> None:
        """Clear all memory for a thread (useful for testing)."""
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM conversation_memory WHERE thread_id = ?",
                (thread_id,),
            )
            conn.execute(
                "DELETE FROM conversation_summary WHERE thread_id = ?",
                (thread_id,),
            )
            conn.commit()
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
            # Double-checked locking
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
