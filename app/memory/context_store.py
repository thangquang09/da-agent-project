from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

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


class ContextMemoryStore:
    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS context_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        context_type TEXT NOT NULL,
        needs_semantic_context INTEGER NOT NULL,
        detected_intent TEXT NOT NULL,
        query TEXT NOT NULL,
        user_provided_context TEXT,
        source_files TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_thread_id ON context_memory(thread_id);
    CREATE INDEX IF NOT EXISTS idx_created_at ON context_memory(created_at);
    """

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = (
                Path(__file__).resolve().parents[2]
                / "data"
                / "warehouse"
                / "context_memory.db"
            )
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(self.CREATE_TABLE_SQL)
            conn.commit()
        logger.info("Context memory store initialized at {path}", path=self.db_path)

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
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO context_memory (
                    thread_id, run_id, created_at, context_type,
                    needs_semantic_context, detected_intent, query,
                    user_provided_context, source_files
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thread_id,
                    run_id,
                    datetime.utcnow().isoformat(),
                    context_type,
                    1 if needs_semantic_context else 0,
                    json.dumps(detected_intent),
                    query,
                    user_provided_context,
                    json.dumps(source_files or []),
                ),
            )
            conn.commit()
            record_id = cursor.lastrowid
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
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM context_memory
                WHERE thread_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (thread_id, limit),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_context_by_type(
        self, thread_id: str, context_type: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM context_memory
                WHERE thread_id = ? AND context_type = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (thread_id, context_type, limit),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_all_contexts_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM context_memory
                WHERE run_id = ?
                ORDER BY created_at ASC
                """,
                (run_id,),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]


_context_memory_store: ContextMemoryStore | None = None


def get_context_memory_store() -> ContextMemoryStore:
    global _context_memory_store
    if _context_memory_store is None:
        _context_memory_store = ContextMemoryStore()
    return _context_memory_store
