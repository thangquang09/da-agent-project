from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.config import load_settings
from app.logger import logger


@dataclass(frozen=True)
class ContextRecord:
    context_type: str
    needs_semantic_context: bool
    detected_intent: list[str]
    query: str
    user_provided_context: str | None
    source_files: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_type": self.context_type,
            "needs_semantic_context": self.needs_semantic_context,
            "detected_intent": self.detected_intent,
            "query": self.query,
            "user_provided_context": self.user_provided_context,
            "source_files": self.source_files,
        }


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS agent.context_memory (
    id SERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    context_type TEXT NOT NULL,
    needs_semantic_context BOOLEAN NOT NULL,
    detected_intent JSONB NOT NULL,
    query TEXT NOT NULL,
    user_provided_context TEXT,
    source_files JSONB DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_context_thread ON agent.context_memory(thread_id);
CREATE INDEX IF NOT EXISTS idx_context_created ON agent.context_memory(created_at);
"""


class ContextMemoryStore:
    """PostgreSQL-backed context memory store.

    Stores per-run context detection results in the ``agent`` schema.
    """

    def __init__(self, db_url: str | None = None):
        self._db_url = db_url
        self._ensure_tables()

    def _get_connection(self):
        url = self._db_url or load_settings().database_url
        return psycopg.connect(url)

    def _ensure_tables(self) -> None:
        from data.migrations.create_schemas import run as ensure_schemas
        ensure_schemas()

        with self._get_connection() as conn:
            conn.execute(_CREATE_TABLE_SQL)
            conn.commit()
        logger.info("Context memory store initialized (PostgreSQL)")

    def save_context(
        self,
        thread_id: str,
        run_id: str,
        context_type: str,
        needs_semantic_context: bool,
        detected_intent: list[str],
        query: str,
        user_provided_context: str | None = None,
        source_files: list[str] | None = None,
    ) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO agent.context_memory (
                    thread_id, run_id, created_at, context_type,
                    needs_semantic_context, detected_intent, query,
                    user_provided_context, source_files
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    thread_id,
                    run_id,
                    datetime.now(timezone.utc).isoformat(),
                    context_type,
                    needs_semantic_context,
                    Jsonb(detected_intent),
                    query,
                    user_provided_context,
                    Jsonb(source_files or []),
                ),
            )
            record_id = cursor.fetchone()[0]
            conn.commit()
        logger.info(
            "Saved context memory: id={id}, thread={thread}, type={type}",
            id=record_id,
            thread=thread_id,
            type=context_type,
        )
        return record_id

    def get_recent_contexts(
        self, thread_id: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM agent.context_memory
                WHERE thread_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (thread_id, limit),
            )
            rows = cursor.fetchall()

        return [
            {
                "id": row[0],
                "thread_id": row[1],
                "run_id": row[2],
                "created_at": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]),
                "context_type": row[4],
                "needs_semantic_context": row[5],
                "detected_intent": row[6] if row[6] else [],
                "query": row[7],
                "user_provided_context": row[8],
                "source_files": row[9] if row[9] else [],
            }
            for row in rows
        ]

    def get_context_by_type(
        self, thread_id: str, context_type: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM agent.context_memory
                WHERE thread_id = %s AND context_type = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (thread_id, context_type, limit),
            )
            rows = cursor.fetchall()

        return [
            {
                "id": row[0],
                "thread_id": row[1],
                "run_id": row[2],
                "created_at": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]),
                "context_type": row[4],
                "needs_semantic_context": row[5],
                "detected_intent": row[6] if row[6] else [],
                "query": row[7],
                "user_provided_context": row[8],
                "source_files": row[9] if row[9] else [],
            }
            for row in rows
        ]

    def get_all_contexts_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM agent.context_memory
                WHERE run_id = %s
                ORDER BY created_at ASC
                """,
                (run_id,),
            )
            rows = cursor.fetchall()

        return [
            {
                "id": row[0],
                "thread_id": row[1],
                "run_id": row[2],
                "created_at": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]),
                "context_type": row[4],
                "needs_semantic_context": row[5],
                "detected_intent": row[6] if row[6] else [],
                "query": row[7],
                "user_provided_context": row[8],
                "source_files": row[9] if row[9] else [],
            }
            for row in rows
        ]


_context_memory_store: ContextMemoryStore | None = None


def get_context_memory_store() -> ContextMemoryStore:
    global _context_memory_store
    if _context_memory_store is None:
        _context_memory_store = ContextMemoryStore()
    return _context_memory_store
