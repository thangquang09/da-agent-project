"""Tests for session memory functionality."""

from __future__ import annotations

import hashlib
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.memory.conversation_store import (
    ConversationMemoryStore,
    ConversationSummary,
    ConversationTurn,
    get_conversation_memory_store,
    reset_conversation_memory_store,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_db_path():
    """Create a temporary database path for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test_memory.db"


@pytest.fixture
def memory_store(temp_db_path):
    """Create a conversation memory store for testing."""
    store = ConversationMemoryStore(db_path=temp_db_path)
    yield store
    store.close()


@pytest.fixture
def in_memory_store():
    """Create an in-memory store (fast, no disk I/O)."""
    store = ConversationMemoryStore(db_path=":memory:")
    yield store
    store.close()


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure singleton is reset before and after every test."""
    reset_conversation_memory_store()
    yield
    reset_conversation_memory_store()


# ---------------------------------------------------------------------------
# ConversationTurn dataclass
# ---------------------------------------------------------------------------


class TestConversationTurn:
    """Tests for ConversationTurn dataclass."""

    def test_conversation_turn_creation(self):
        turn = ConversationTurn(
            thread_id="thread-123",
            turn_number=1,
            role="user",
            content="What is DAU today?",
            intent="sql",
            sql_generated=None,
            result_summary=None,
            entities=["dau", "daily_active_users"],
            timestamp="2026-01-01T00:00:00",
        )
        assert turn.thread_id == "thread-123"
        assert turn.turn_number == 1
        assert turn.role == "user"
        assert turn.intent == "sql"
        assert len(turn.entities) == 2

    def test_conversation_turn_to_dict(self):
        turn = ConversationTurn(
            thread_id="thread-123",
            turn_number=1,
            role="user",
            content="Test query",
            intent="sql",
            sql_generated=None,
            result_summary=None,
            entities=["metric1"],
            timestamp="2026-01-01T00:00:00",
        )
        d = turn.to_dict()
        assert d["thread_id"] == "thread-123"
        assert d["entities"] == ["metric1"]

    def test_frozen_dataclass_immutability(self):
        turn = ConversationTurn(
            thread_id="t",
            turn_number=1,
            role="user",
            content="x",
            intent=None,
            sql_generated=None,
            result_summary=None,
            entities=[],
            timestamp="2026-01-01T00:00:00",
        )
        with pytest.raises(AttributeError):
            turn.content = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ConversationMemoryStore CRUD
# ---------------------------------------------------------------------------


class TestConversationMemoryStore:
    """Tests for ConversationMemoryStore."""

    def test_save_and_retrieve_turn(self, memory_store):
        turn = ConversationTurn(
            thread_id="thread-123",
            turn_number=1,
            role="user",
            content="What is DAU?",
            intent="sql",
            sql_generated=None,
            result_summary=None,
            entities=["dau"],
            timestamp=_now_iso(),
        )
        memory_store.save_turn(turn)

        turns = memory_store.get_recent_turns("thread-123", limit=1)
        assert len(turns) == 1
        assert turns[0].content == "What is DAU?"
        assert turns[0].intent == "sql"

    def test_get_turn_count(self, memory_store):
        for i in range(3):
            turn = ConversationTurn(
                thread_id="thread-count",
                turn_number=i + 1,
                role="user" if i % 2 == 0 else "assistant",
                content=f"Turn {i + 1}",
                intent="sql" if i % 2 == 0 else None,
                sql_generated=None,
                result_summary=None,
                entities=[],
                timestamp=_now_iso(),
            )
            memory_store.save_turn(turn)

        count = memory_store.get_turn_count("thread-count")
        assert count == 3

    def test_get_recent_turns_ordering(self, memory_store):
        for i in range(5):
            turn = ConversationTurn(
                thread_id="thread-order",
                turn_number=i + 1,
                role="user",
                content=f"Message {i + 1}",
                intent="sql",
                sql_generated=None,
                result_summary=None,
                entities=[],
                timestamp=_now_iso(),
            )
            memory_store.save_turn(turn)

        turns = memory_store.get_recent_turns("thread-order", limit=3)
        assert len(turns) == 3
        # Chronological order (oldest first in the window)
        assert turns[0].content == "Message 3"
        assert turns[1].content == "Message 4"
        assert turns[2].content == "Message 5"

    def test_summary_crud(self, memory_store):
        summary = ConversationSummary(
            thread_id="thread-summary",
            summary="User asked about DAU metrics and retention rates.",
            turn_count=10,
            last_updated=_now_iso(),
            key_entities=["dau", "retention", "revenue"],
        )
        memory_store.update_summary(summary)

        retrieved = memory_store.get_summary("thread-summary")
        assert retrieved is not None
        assert "DAU" in retrieved.summary
        assert "retention" in retrieved.key_entities

    def test_summary_update(self, memory_store):
        summary1 = ConversationSummary(
            thread_id="thread-update",
            summary="Initial summary",
            turn_count=5,
            last_updated=_now_iso(),
            key_entities=["metric1"],
        )
        memory_store.update_summary(summary1)

        summary2 = ConversationSummary(
            thread_id="thread-update",
            summary="Updated summary with more details",
            turn_count=10,
            last_updated=_now_iso(),
            key_entities=["metric1", "metric2"],
        )
        memory_store.update_summary(summary2)

        retrieved = memory_store.get_summary("thread-update")
        assert retrieved is not None
        assert "Updated summary" in retrieved.summary
        assert len(retrieved.key_entities) == 2

    def test_clear_thread(self, memory_store):
        turn = ConversationTurn(
            thread_id="thread-clear",
            turn_number=1,
            role="user",
            content="Test",
            intent="sql",
            sql_generated=None,
            result_summary=None,
            entities=[],
            timestamp=_now_iso(),
        )
        memory_store.save_turn(turn)

        summary = ConversationSummary(
            thread_id="thread-clear",
            summary="Test summary",
            turn_count=1,
            last_updated=_now_iso(),
            key_entities=[],
        )
        memory_store.update_summary(summary)

        memory_store.clear_thread("thread-clear")

        turns = memory_store.get_recent_turns("thread-clear")
        assert len(turns) == 0

        retrieved_summary = memory_store.get_summary("thread-clear")
        assert retrieved_summary is None

    def test_multiple_threads(self, memory_store):
        for thread_num in range(3):
            for turn_num in range(5):
                turn = ConversationTurn(
                    thread_id=f"thread-{thread_num}",
                    turn_number=turn_num + 1,
                    role="user",
                    content=f"Thread {thread_num} turn {turn_num}",
                    intent="sql",
                    sql_generated=None,
                    result_summary=None,
                    entities=[],
                    timestamp=_now_iso(),
                )
                memory_store.save_turn(turn)

        for thread_num in range(3):
            turns = memory_store.get_recent_turns(f"thread-{thread_num}", limit=10)
            assert len(turns) == 5
            assert all(t.thread_id == f"thread-{thread_num}" for t in turns)

    def test_get_summary_nonexistent(self, memory_store):
        result = memory_store.get_summary("nonexistent-thread")
        assert result is None

    def test_entities_round_trip_json(self, memory_store):
        """Entities should survive JSON serialization in SQLite."""
        entities = ["daily_active_users", "revenue", "retention_d1"]
        turn = ConversationTurn(
            thread_id="thread-json",
            turn_number=1,
            role="user",
            content="x",
            intent="sql",
            sql_generated=None,
            result_summary=None,
            entities=entities,
            timestamp=_now_iso(),
        )
        memory_store.save_turn(turn)

        retrieved = memory_store.get_recent_turns("thread-json", limit=1)
        assert retrieved[0].entities == entities

    def test_in_memory_store(self, in_memory_store):
        """In-memory store should work identically."""
        turn = ConversationTurn(
            thread_id="mem-thread",
            turn_number=1,
            role="user",
            content="memory test",
            intent="sql",
            sql_generated=None,
            result_summary=None,
            entities=[],
            timestamp=_now_iso(),
        )
        in_memory_store.save_turn(turn)
        assert in_memory_store.get_turn_count("mem-thread") == 1


# ---------------------------------------------------------------------------
# delete_old_turns (new pruning feature)
# ---------------------------------------------------------------------------


class TestDeleteOldTurns:
    """Tests for the new delete_old_turns method."""

    def test_prune_keeps_last_n(self, in_memory_store):
        """Should keep only the last N turns after pruning."""
        store = in_memory_store
        for i in range(20):
            turn = ConversationTurn(
                thread_id="prune-test",
                turn_number=i + 1,
                role="user" if i % 2 == 0 else "assistant",
                content=f"Turn {i + 1}",
                intent=None,
                sql_generated=None,
                result_summary=None,
                entities=[],
                timestamp=_now_iso(),
            )
            store.save_turn(turn)

        assert store.get_turn_count("prune-test") == 20

        deleted = store.delete_old_turns("prune-test", keep_last_n=6)
        assert deleted == 14
        assert store.get_turn_count("prune-test") == 6

        remaining = store.get_recent_turns("prune-test", limit=10)
        # Should have turns 15-20 (the most recent 6)
        assert remaining[0].turn_number == 15
        assert remaining[-1].turn_number == 20

    def test_prune_no_op_when_below_threshold(self, in_memory_store):
        """No deletes when total turns <= keep_last_n."""
        store = in_memory_store
        for i in range(3):
            turn = ConversationTurn(
                thread_id="prune-noop",
                turn_number=i + 1,
                role="user",
                content=f"Turn {i}",
                intent=None,
                sql_generated=None,
                result_summary=None,
                entities=[],
                timestamp=_now_iso(),
            )
            store.save_turn(turn)

        deleted = store.delete_old_turns("prune-noop", keep_last_n=10)
        assert deleted == 0
        assert store.get_turn_count("prune-noop") == 3

    def test_prune_does_not_affect_other_threads(self, in_memory_store):
        """Pruning one thread should not touch another."""
        store = in_memory_store
        for thread in ["A", "B"]:
            for i in range(5):
                turn = ConversationTurn(
                    thread_id=thread,
                    turn_number=i + 1,
                    role="user",
                    content=f"{thread}-{i}",
                    intent=None,
                    sql_generated=None,
                    result_summary=None,
                    entities=[],
                    timestamp=_now_iso(),
                )
                store.save_turn(turn)

        store.delete_old_turns("A", keep_last_n=2)
        assert store.get_turn_count("A") == 2
        assert store.get_turn_count("B") == 5  # untouched


# ---------------------------------------------------------------------------
# Singleton thread-safety
# ---------------------------------------------------------------------------


class TestSingleton:
    """Tests for singleton management."""

    def test_get_conversation_memory_store_singleton(self):
        """get_conversation_memory_store returns the same instance."""
        store1 = get_conversation_memory_store()
        store2 = get_conversation_memory_store()
        assert store1 is store2

    def test_reset_clears_singleton(self):
        store1 = get_conversation_memory_store()
        reset_conversation_memory_store()
        store2 = get_conversation_memory_store()
        assert store1 is not store2

    def test_singleton_thread_safety(self):
        """Multiple threads should all see the same singleton instance."""
        results: list[ConversationMemoryStore] = []
        barrier = threading.Barrier(4)

        def worker():
            barrier.wait()  # synchronize start
            results.append(get_conversation_memory_store())

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 4
        assert all(r is results[0] for r in results)


# ---------------------------------------------------------------------------
# _extract_entities_from_state (integration)
# ---------------------------------------------------------------------------


class TestExtractEntitiesFromState:
    """Tests for _extract_entities_from_state helper."""

    def test_extracts_tables_from_schema_context(self):
        from app.graph.nodes import _extract_entities_from_state

        state = {
            "schema_context": "Table: daily_metrics\n  - date TEXT\n  - dau INTEGER\nTable: videos\n  - title TEXT",
            "generated_sql": "",
            "retrieved_context": [],
        }
        entities = _extract_entities_from_state(state)
        assert "daily_metrics" in entities
        assert "videos" in entities

    def test_extracts_tables_from_sql(self):
        from app.graph.nodes import _extract_entities_from_state

        state = {
            "schema_context": "",
            "generated_sql": "SELECT u.name FROM users u JOIN orders o ON u.id = o.user_id",
            "retrieved_context": [],
        }
        entities = _extract_entities_from_state(state)
        assert "users" in entities
        assert "orders" in entities

    def test_deduplication(self):
        from app.graph.nodes import _extract_entities_from_state

        state = {
            "schema_context": "Table: users\n  - id INTEGER",
            "generated_sql": "SELECT * FROM users",
            "retrieved_context": [],
        }
        entities = _extract_entities_from_state(state)
        # "users" appears in both schema and SQL — should appear only once
        assert entities.count("users") == 1

    def test_limit_to_five(self):
        from app.graph.nodes import _extract_entities_from_state

        state = {
            "schema_context": "Table: a\nTable: b\nTable: c\nTable: d",
            "generated_sql": "SELECT * FROM e JOIN f JOIN g JOIN h",
            "retrieved_context": [],
        }
        entities = _extract_entities_from_state(state)
        assert len(entities) <= 5

    def test_empty_state(self):
        from app.graph.nodes import _extract_entities_from_state

        entities = _extract_entities_from_state({})
        assert entities == []


# ---------------------------------------------------------------------------
# inject_session_context (integration with mocked store)
# ---------------------------------------------------------------------------


class TestInjectSessionContext:
    """Tests for inject_session_context node."""

    def test_no_thread_id_returns_empty(self):
        from app.graph.nodes import inject_session_context

        result = inject_session_context({"user_query": "test"})
        assert result == {}

    def test_new_thread_returns_turn_1(self, in_memory_store):
        from app.graph.nodes import inject_session_context

        with patch(
            "app.memory.conversation_store.get_conversation_memory_store",
            return_value=in_memory_store,
        ):
            result = inject_session_context(
                {"thread_id": "new-thread", "user_query": "hello"}
            )
        assert result.get("conversation_turn") == 1

    def test_existing_thread_injects_context(self, in_memory_store):
        from app.graph.nodes import inject_session_context

        # Seed some turns
        in_memory_store.save_turn(
            ConversationTurn(
                thread_id="existing",
                turn_number=1,
                role="user",
                content="What is DAU?",
                intent="sql",
                sql_generated=None,
                result_summary=None,
                entities=["dau"],
                timestamp=_now_iso(),
            )
        )
        in_memory_store.save_turn(
            ConversationTurn(
                thread_id="existing",
                turn_number=2,
                role="assistant",
                content="",
                intent=None,
                sql_generated="SELECT dau FROM daily_metrics",
                result_summary="DAU was 10,000 yesterday",
                entities=["dau"],
                timestamp=_now_iso(),
            )
        )

        with patch(
            "app.memory.conversation_store.get_conversation_memory_store",
            return_value=in_memory_store,
        ):
            result = inject_session_context(
                {"thread_id": "existing", "user_query": "And today?"}
            )

        assert "session_context" in result
        assert "What is DAU?" in result["session_context"]
        assert "DAU was 10,000 yesterday" in result["session_context"]
        assert result["conversation_turn"] >= 1

    def test_injects_summary_when_present(self, in_memory_store):
        from app.graph.nodes import inject_session_context

        in_memory_store.update_summary(
            ConversationSummary(
                thread_id="summ",
                summary="User discussed retention and DAU trends.",
                turn_count=12,
                last_updated=_now_iso(),
                key_entities=["retention", "dau"],
            )
        )
        # Need at least one turn so the function doesn't bail out
        in_memory_store.save_turn(
            ConversationTurn(
                thread_id="summ",
                turn_number=1,
                role="user",
                content="latest question",
                intent=None,
                sql_generated=None,
                result_summary=None,
                entities=[],
                timestamp=_now_iso(),
            )
        )

        with patch(
            "app.memory.conversation_store.get_conversation_memory_store",
            return_value=in_memory_store,
        ):
            result = inject_session_context(
                {"thread_id": "summ", "user_query": "next q"}
            )

        ctx = result.get("session_context", "")
        assert "Conversation Summary" in ctx
        assert "retention" in ctx


# ---------------------------------------------------------------------------
# Qdrant point ID determinism
# ---------------------------------------------------------------------------


class TestQdrantPointIdDeterminism:
    """Ensure Qdrant point IDs are deterministic across processes."""

    def test_hashlib_produces_stable_ids(self):
        """hashlib.sha256 should always produce the same ID for the same input."""
        thread_id = "thread-42"
        turn_number = 7
        key = f"{thread_id}_{turn_number}"
        id1 = int(hashlib.sha256(key.encode()).hexdigest(), 16) % (2**63)
        id2 = int(hashlib.sha256(key.encode()).hexdigest(), 16) % (2**63)
        assert id1 == id2
        assert id1 > 0

    def test_different_inputs_produce_different_ids(self):
        def _point_id(thread: str, turn: int) -> int:
            return int(
                hashlib.sha256(f"{thread}_{turn}".encode()).hexdigest(), 16
            ) % (2**63)

        assert _point_id("a", 1) != _point_id("a", 2)
        assert _point_id("a", 1) != _point_id("b", 1)
