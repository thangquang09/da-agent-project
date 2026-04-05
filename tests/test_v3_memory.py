from __future__ import annotations

import json

from app.graph.nodes import compact_and_save_memory, inject_session_context
from app.memory.conversation_store import (
    ConversationMemoryStore,
    ConversationSummary,
    ConversationTurn,
)


def test_inject_session_context_returns_recent_turns_summary_and_last_action(monkeypatch, tmp_path):
    memory_db = tmp_path / "conversation_memory.db"
    store = ConversationMemoryStore(db_path=memory_db)
    monkeypatch.setattr(
        "app.memory.conversation_store.get_conversation_memory_store",
        lambda: store,
    )

    store.update_summary(
        ConversationSummary(
            thread_id="memory-thread",
            summary="Nguoi dung dang hoi ve du lieu hoc sinh.",
            turn_count=2,
            last_updated="2026-04-04T00:00:00+00:00",
            key_entities=["Performance_of_Stuednts", "math score"],
        )
    )
    store.save_turn(
        ConversationTurn(
            thread_id="memory-thread",
            turn_number=1,
            role="user",
            content="Có bao nhiêu học sinh nam và nữ?",
            intent="sql",
            sql_generated=None,
            result_summary=None,
            entities=[],
            timestamp="2026-04-04T00:00:00+00:00",
        )
    )
    store.save_turn(
        ConversationTurn(
            thread_id="memory-thread",
            turn_number=2,
            role="assistant",
            content="",
            intent=None,
            sql_generated=None,
            result_summary="Có 518 nữ và 482 nam.",
            entities=[],
            last_action_json=json.dumps(
                {
                    "action_type": "sql",
                    "generated_sql": "SELECT gender, COUNT(*) FROM Performance_of_Stuednts GROUP BY gender",
                }
            ),
            timestamp="2026-04-04T00:00:01+00:00",
        )
    )

    update = inject_session_context(
        {
            "thread_id": "memory-thread",
            "user_query": "Giờ chỉ tính cho các học sinh nam thôi nhé.",
        }
    )

    assert "Conversation Summary" in update["session_context"]
    assert "Recent Turns" in update["session_context"]
    assert update["conversation_turn"] == 2
    assert update["last_action"]["action_type"] == "sql"


def test_compact_and_save_memory_persists_last_action(monkeypatch, tmp_path):
    memory_db = tmp_path / "conversation_memory.db"
    store = ConversationMemoryStore(db_path=memory_db)
    monkeypatch.setattr(
        "app.memory.conversation_store.get_conversation_memory_store",
        lambda: store,
    )

    compact_and_save_memory(
        {
            "thread_id": "persist-thread",
            "user_query": "Điểm toán trung bình là bao nhiêu?",
            "intent": "sql",
            "generated_sql": 'SELECT AVG("math score") AS average_math_score FROM Performance_of_Stuednts',
            "final_payload": {"answer": "Điểm toán trung bình của toàn bộ học sinh là 66.08."},
            "last_action": {
                "action_type": "sql",
                "generated_sql": 'SELECT AVG("math score") AS average_math_score FROM Performance_of_Stuednts',
            },
        }
    )

    turns = store.get_recent_turns("persist-thread", limit=5)
    assistant_turns = [turn for turn in turns if turn.role == "assistant"]
    assert assistant_turns
    assert assistant_turns[-1].last_action_json is not None
    assert "AVG" in assistant_turns[-1].last_action_json
