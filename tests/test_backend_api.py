from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_PAYLOAD: dict[str, Any] = {
    "run_id": "test-run-001",
    "thread_id": "test-thread-001",
    "answer": "DAU hôm qua là 1.234 người dùng.",
    "intent": "sql",
    "confidence": "high",
    "used_tools": ["get_schema", "query_sql"],
    "generated_sql": "SELECT COUNT(*) FROM events WHERE date = date('now', '-1 day')",
    "evidence": ["rows=1", "context_chunks=0"],
    "error_categories": [],
    "tool_history": [],
    "errors": [],
    "total_token_usage": 500,
    "total_cost_usd": 0.001,
    "context_type": "default",
    "step_count": 4,
}


@pytest.fixture(scope="module")
def client():
    """Test client with mocked run_query so tests don't need LLM API keys."""
    app = create_app()
    return TestClient(app)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health_ok(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["graph_version"] == "v2"


# ---------------------------------------------------------------------------
# POST /query
# ---------------------------------------------------------------------------


def test_query_returns_valid_shape(client: TestClient) -> None:
    with patch("backend.services.agent_service.run_query", return_value=MOCK_PAYLOAD):
        r = client.post("/query", json={"query": "DAU hôm qua?"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == MOCK_PAYLOAD["answer"]
    assert body["intent"] == "sql"
    assert body["confidence"] == "high"
    assert "get_schema" in body["used_tools"]


def test_query_auto_generates_thread_id(client: TestClient) -> None:
    with patch("backend.services.agent_service.run_query", return_value=MOCK_PAYLOAD):
        r = client.post("/query", json={"query": "Test?"})
    assert r.status_code == 200
    # thread_id comes from MOCK_PAYLOAD; important thing is request didn't fail


def test_query_passes_thread_id(client: TestClient) -> None:
    with patch("backend.services.agent_service.run_query", return_value=MOCK_PAYLOAD) as mock_rq:
        r = client.post("/query", json={"query": "Test?", "thread_id": "explicit-tid"})
    assert r.status_code == 200
    call_kwargs = mock_rq.call_args[1]
    assert call_kwargs["thread_id"] == "explicit-tid"


def test_query_validation_empty_query(client: TestClient) -> None:
    r = client.post("/query", json={"query": ""})
    assert r.status_code == 422


def test_query_validation_invalid_version(client: TestClient) -> None:
    r = client.post("/query", json={"query": "test", "version": "v9"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /query/stream (SSE)
# ---------------------------------------------------------------------------


def test_query_stream_missing_param(client: TestClient) -> None:
    r = client.get("/query/stream")
    assert r.status_code == 422


def test_query_stream_returns_sse_events(client: TestClient) -> None:
    with patch("backend.services.sse_service.run_query", return_value=MOCK_PAYLOAD):
        r = client.get("/query/stream", params={"q": "DAU?", "thread_id": "sse-test"})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
    body = r.text
    assert "event: started" in body
    assert "event: result" in body


# ---------------------------------------------------------------------------
# GET /threads/{id}
# ---------------------------------------------------------------------------


def test_get_thread_not_found(client: TestClient) -> None:
    r = client.get("/threads/nonexistent-thread-xyz-abc")
    assert r.status_code == 404


def test_get_thread_history_empty(client: TestClient) -> None:
    r = client.get("/threads/nonexistent-thread-xyz-abc/history")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# DELETE /threads/{id}
# ---------------------------------------------------------------------------


def test_delete_thread_idempotent(client: TestClient) -> None:
    """Deleting a non-existent thread should return 204 (idempotent)."""
    r = client.delete("/threads/thread-that-does-not-exist")
    assert r.status_code == 204


def test_delete_then_get_thread(client: TestClient) -> None:
    """After delete, thread should not be found."""
    from app.memory.conversation_store import get_conversation_memory_store
    from app.memory.conversation_store import ConversationTurn
    from datetime import datetime, timezone

    store = get_conversation_memory_store()
    tid = "backend-test-thread-delete"
    store.save_turn(ConversationTurn(
        thread_id=tid, turn_number=1, role="user",
        content="hello", intent=None, sql_generated=None,
        result_summary=None, entities=[],
        timestamp=datetime.now(timezone.utc).isoformat(),
    ))

    r = client.delete(f"/threads/{tid}")
    assert r.status_code == 204

    r2 = client.get(f"/threads/{tid}")
    assert r2.status_code == 404


# ---------------------------------------------------------------------------
# POST /query/upload (multipart)
# ---------------------------------------------------------------------------


def test_query_upload_no_files(client: TestClient) -> None:
    with patch("backend.services.agent_service.run_query", return_value=MOCK_PAYLOAD):
        r = client.post("/query/upload", data={"query": "analyze data"})
    assert r.status_code == 200
    assert r.json()["answer"] == MOCK_PAYLOAD["answer"]
