"""Tests for Phase 1.2: ConversationMemoryStore PostgreSQL migration.

Validates that ConversationMemoryStore works identically when backed
by PostgreSQL instead of SQLite.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import psycopg
import pytest

from app.config import load_settings
from app.memory.conversation_store import (
    ConversationMemoryStore,
    ConversationSummary,
    ConversationTurn,
    reset_conversation_memory_store,
)


def _ensure_schemas():
    """Ensure agent + user_data schemas exist."""
    from data.migrations.create_schemas import run as ensure_schemas
    ensure_schemas()


@pytest.fixture()
def pg_store():
    """Create a ConversationMemoryStore backed by PostgreSQL."""
    _ensure_schemas()
    settings = load_settings()
    store = ConversationMemoryStore(db_url=settings.database_url)
    yield store
    # Cleanup: drop test tables
    with psycopg.connect(settings.database_url) as conn:
        conn.execute("DROP TABLE IF EXISTS agent.conversation_memory")
        conn.execute("DROP TABLE IF EXISTS agent.conversation_summary")
        conn.commit()
    reset_conversation_memory_store()


# ── save_turn + get_recent_turns ──────────────────────────────────


def test_save_and_retrieve_turn(pg_store: ConversationMemoryStore):
    store = pg_store
    turn = ConversationTurn(
        thread_id="test-thread-1",
        turn_number=1,
        role="user",
        content="DAU hôm qua?",
        intent="sql",
        sql_generated=None,
        result_summary=None,
        entities=["dau", "metric"],
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    record_id = store.save_turn(turn)
    assert record_id > 0

    turns = store.get_recent_turns("test-thread-1", limit=5)
    assert len(turns) == 1
    assert turns[0].thread_id == "test-thread-1"
    assert turns[0].role == "user"
    assert turns[0].content == "DAU hôm qua?"
    assert turns[0].intent == "sql"
    assert turns[0].entities == ["dau", "metric"]


def test_turns_returned_in_chronological_order(pg_store: ConversationMemoryStore):
    store = pg_store
    now = datetime.now(timezone.utc).isoformat()
    for i in range(1, 4):
        store.save_turn(
            ConversationTurn(
                thread_id="test-thread-2",
                turn_number=i,
                role="user" if i % 2 == 1 else "assistant",
                content=f"Turn {i}",
                intent=None,
                sql_generated=None,
                result_summary=None,
                entities=[],
                timestamp=now,
            )
        )

    turns = store.get_recent_turns("test-thread-2", limit=10)
    assert len(turns) == 3
    # Chronological order: turn_number ascending
    assert turns[0].turn_number == 1
    assert turns[1].turn_number == 2
    assert turns[2].turn_number == 3


def test_get_recent_turns_respects_limit(pg_store: ConversationMemoryStore):
    store = pg_store
    now = datetime.now(timezone.utc).isoformat()
    for i in range(1, 6):
        store.save_turn(
            ConversationTurn(
                thread_id="test-thread-3",
                turn_number=i,
                role="user",
                content=f"Turn {i}",
                intent=None,
                sql_generated=None,
                result_summary=None,
                entities=[],
                timestamp=now,
            )
        )

    turns = store.get_recent_turns("test-thread-3", limit=3)
    # Returns last 3 in chronological order
    assert len(turns) == 3
    assert turns[0].turn_number == 3
    assert turns[2].turn_number == 5


def test_get_turn_count(pg_store: ConversationMemoryStore):
    store = pg_store
    now = datetime.now(timezone.utc).isoformat()
    for i in range(1, 4):
        store.save_turn(
            ConversationTurn(
                thread_id="test-thread-4",
                turn_number=i,
                role="user",
                content=f"Turn {i}",
                intent=None,
                sql_generated=None,
                result_summary=None,
                entities=[],
                timestamp=now,
            )
        )
    assert store.get_turn_count("test-thread-4") == 3
    assert store.get_turn_count("nonexistent-thread") == 0


def test_isolates_different_threads(pg_store: ConversationMemoryStore):
    store = pg_store
    now = datetime.now(timezone.utc).isoformat()
    store.save_turn(
        ConversationTurn(
            thread_id="thread-a",
            turn_number=1,
            role="user",
            content="Query A",
            intent=None,
            sql_generated=None,
            result_summary=None,
            entities=[],
            timestamp=now,
        )
    )
    store.save_turn(
        ConversationTurn(
            thread_id="thread-b",
            turn_number=1,
            role="user",
            content="Query B",
            intent=None,
            sql_generated=None,
            result_summary=None,
            entities=[],
            timestamp=now,
        )
    )

    turns_a = store.get_recent_turns("thread-a", limit=5)
    turns_b = store.get_recent_turns("thread-b", limit=5)
    assert len(turns_a) == 1
    assert len(turns_b) == 1
    assert turns_a[0].content == "Query A"
    assert turns_b[0].content == "Query B"


# ── Summary CRUD ──────────────────────────────────────────────────


def test_update_and_get_summary(pg_store: ConversationMemoryStore):
    store = pg_store
    summary = ConversationSummary(
        thread_id="test-thread-5",
        summary="User asked about DAU metrics.",
        turn_count=4,
        last_updated=datetime.now(timezone.utc).isoformat(),
        key_entities=["dau", "retention"],
    )
    store.update_summary(summary)

    result = store.get_summary("test-thread-5")
    assert result is not None
    assert result.thread_id == "test-thread-5"
    assert result.summary == "User asked about DAU metrics."
    assert result.turn_count == 4
    assert result.key_entities == ["dau", "retention"]


def test_update_summary_upserts(pg_store: ConversationMemoryStore):
    store = pg_store
    ts = datetime.now(timezone.utc).isoformat()

    store.update_summary(
        ConversationSummary(
            thread_id="test-thread-6",
            summary="First version",
            turn_count=2,
            last_updated=ts,
            key_entities=[],
        )
    )
    store.update_summary(
        ConversationSummary(
            thread_id="test-thread-6",
            summary="Updated version",
            turn_count=5,
            last_updated=ts,
            key_entities=["new_entity"],
        )
    )

    result = store.get_summary("test-thread-6")
    assert result.summary == "Updated version"
    assert result.turn_count == 5
    assert result.key_entities == ["new_entity"]


def test_get_summary_returns_none_for_unknown_thread(pg_store: ConversationMemoryStore):
    store = pg_store
    assert store.get_summary("nonexistent") is None


# ── delete_old_turns ──────────────────────────────────────────────


def test_delete_old_turns_keeps_recent(pg_store: ConversationMemoryStore):
    store = pg_store
    now = datetime.now(timezone.utc).isoformat()
    for i in range(1, 11):
        store.save_turn(
            ConversationTurn(
                thread_id="test-thread-7",
                turn_number=i,
                role="user",
                content=f"Turn {i}",
                intent=None,
                sql_generated=None,
                result_summary=None,
                entities=[],
                timestamp=now,
            )
        )

    deleted = store.delete_old_turns("test-thread-7", keep_last_n=3)
    assert deleted == 7

    remaining = store.get_recent_turns("test-thread-7", limit=20)
    assert len(remaining) == 3
    assert remaining[0].turn_number == 8


# ── clear_thread ──────────────────────────────────────────────────


def test_clear_thread_removes_all_data(pg_store: ConversationMemoryStore):
    store = pg_store
    now = datetime.now(timezone.utc).isoformat()
    store.save_turn(
        ConversationTurn(
            thread_id="test-thread-8",
            turn_number=1,
            role="user",
            content="Hello",
            intent=None,
            sql_generated=None,
            result_summary=None,
            entities=[],
            timestamp=now,
        )
    )
    store.update_summary(
        ConversationSummary(
            thread_id="test-thread-8",
            summary="Test summary",
            turn_count=1,
            last_updated=now,
            key_entities=[],
        )
    )

    store.clear_thread("test-thread-8")

    assert store.get_turn_count("test-thread-8") == 0
    assert store.get_summary("test-thread-8") is None


# ── last_action_json field ────────────────────────────────────────


def test_save_turn_with_last_action_json(pg_store: ConversationMemoryStore):
    store = pg_store
    action = {"action_type": "sql", "generated_sql": "SELECT 1"}
    store.save_turn(
        ConversationTurn(
            thread_id="test-thread-9",
            turn_number=1,
            role="assistant",
            content="",
            intent=None,
            sql_generated="SELECT 1",
            result_summary="Found 1 row",
            entities=[],
            timestamp=datetime.now(timezone.utc).isoformat(),
            last_action_json=json.dumps(action),
        )
    )

    turns = store.get_recent_turns("test-thread-9", limit=5)
    assert len(turns) == 1
    parsed = json.loads(turns[0].last_action_json)
    assert parsed["action_type"] == "sql"
    assert "SELECT 1" in parsed["generated_sql"]


# ── Integration: inject_session_context with PG store ─────────────


def test_inject_session_context_with_pg_store(monkeypatch, pg_store):
    """inject_session_context works with PostgreSQL-backed store."""
    from app.graph.nodes import inject_session_context

    monkeypatch.setattr(
        "app.memory.conversation_store.get_conversation_memory_store",
        lambda: pg_store,
    )

    pg_store.update_summary(
        ConversationSummary(
            thread_id="pg-inject-thread",
            summary="User asks about student data.",
            turn_count=2,
            last_updated=datetime.now(timezone.utc).isoformat(),
            key_entities=["students"],
        )
    )
    pg_store.save_turn(
        ConversationTurn(
            thread_id="pg-inject-thread",
            turn_number=1,
            role="user",
            content="Có bao nhiêu học sinh?",
            intent="sql",
            sql_generated=None,
            result_summary=None,
            entities=[],
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    )
    pg_store.save_turn(
        ConversationTurn(
            thread_id="pg-inject-thread",
            turn_number=2,
            role="assistant",
            content="",
            intent=None,
            sql_generated=None,
            result_summary="Có 1000 học sinh.",
            entities=[],
            timestamp=datetime.now(timezone.utc).isoformat(),
            last_action_json=json.dumps({"action_type": "sql"}),
        )
    )

    result = inject_session_context(
        {
            "thread_id": "pg-inject-thread",
            "user_query": "Học sinh nam?",
        }
    )

    assert "Conversation Summary" in result["session_context"]
    assert "Recent Turns" in result["session_context"]
    assert result["conversation_turn"] >= 1
    assert result["last_action"]["action_type"] == "sql"
