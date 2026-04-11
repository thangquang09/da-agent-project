"""Dedicated store for heavyweight conversation artifacts (reports, charts).

Keeps the main conversation_memory table lean by storing large blobs
(base64 chart images, full report markdown + sections) in a separate table.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.config import load_settings
from app.logger import logger


@dataclass(frozen=True)
class TurnArtifact:
    """Persisted artifact from a conversation turn."""

    thread_id: str
    turn_number: int
    artifact_type: str  # "report" | "chart"
    payload: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS agent.turn_artifacts (
    id SERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    artifact_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_artifacts_thread
    ON agent.turn_artifacts(thread_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_artifacts_unique
    ON agent.turn_artifacts(thread_id, turn_number, artifact_type);
"""


class ArtifactStore:
    """PostgreSQL-backed store for conversation turn artifacts.

    Stores heavyweight artifacts (reports, charts) separately from
    conversation turns to keep the main conversation table lean.
    """

    def __init__(self, db_url: str | None = None):
        self._db_url = db_url
        self._ensure_table()

    def _get_connection(self):
        url = self._db_url or load_settings().database_url
        return psycopg.connect(url)

    def _ensure_table(self) -> None:
        with self._get_connection() as conn:
            conn.execute(_CREATE_TABLE_SQL)
            conn.commit()
        logger.info("Artifact store initialized (PostgreSQL)")

    def save_artifact(self, artifact: TurnArtifact) -> int:
        """Save or upsert an artifact. Returns the record id."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO agent.turn_artifacts
                    (thread_id, turn_number, artifact_type, payload, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (thread_id, turn_number, artifact_type)
                DO UPDATE SET payload = EXCLUDED.payload, created_at = EXCLUDED.created_at
                RETURNING id
                """,
                (
                    artifact.thread_id,
                    artifact.turn_number,
                    artifact.artifact_type,
                    Jsonb(artifact.payload),
                    artifact.created_at,
                ),
            )
            record_id = cursor.fetchone()[0]
            conn.commit()
        logger.debug(
            "Saved artifact: thread={thread}, turn={turn}, type={atype}",
            thread=artifact.thread_id[:8],
            turn=artifact.turn_number,
            atype=artifact.artifact_type,
        )
        return record_id

    def get_thread_artifacts(self, thread_id: str) -> list[TurnArtifact]:
        """Get all artifacts for a thread, ordered by turn number."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT thread_id, turn_number, artifact_type, payload, created_at
                FROM agent.turn_artifacts
                WHERE thread_id = %s
                ORDER BY turn_number ASC, artifact_type ASC
                """,
                (thread_id,),
            )
            rows = cursor.fetchall()

        return [
            TurnArtifact(
                thread_id=row[0],
                turn_number=row[1],
                artifact_type=row[2],
                payload=row[3] if row[3] else {},
                created_at=row[4].isoformat() if hasattr(row[4], "isoformat") else str(row[4]),
            )
            for row in rows
        ]

    def delete_thread_artifacts(self, thread_id: str, *, cleanup_files: bool = True) -> int:
        """Delete all artifacts for a thread. Returns count of deleted rows.

        If cleanup_files is True, also removes the artifact files from disk.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM agent.turn_artifacts WHERE thread_id = %s",
                (thread_id,),
            )
            deleted = cursor.rowcount
            conn.commit()
        if deleted:
            logger.info(
                "Deleted {n} artifacts for thread={thread}",
                n=deleted,
                thread=thread_id[:8],
            )
        # Clean up filesystem artifacts
        if cleanup_files:
            try:
                from app.artifacts.file_store import get_artifact_file_store
                file_store = get_artifact_file_store()
                file_count = file_store.delete_thread(thread_id)
                if file_count:
                    logger.info(
                        "Deleted {n} artifact files for thread={thread}",
                        n=file_count,
                        thread=thread_id[:8],
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to cleanup artifact files for thread={thread}: {err}",
                    thread=thread_id[:8],
                    err=str(exc),
                )
        return deleted


# ---------------------------------------------------------------------------
# Thread-safe singleton
# ---------------------------------------------------------------------------

_artifact_store: ArtifactStore | None = None
_lock = threading.Lock()


def get_artifact_store() -> ArtifactStore:
    """Get or create artifact store singleton (thread-safe)."""
    global _artifact_store
    if _artifact_store is None:
        with _lock:
            if _artifact_store is None:
                _artifact_store = ArtifactStore()
    return _artifact_store
