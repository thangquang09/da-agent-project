from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import create_app


class _DummyConn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, _sql: str):
        return None

MULTI_QUERY = (
    '"Có bao nhiêu học sinh nam và bao nhiêu học sinh nữ trong tập dữ liệu này?"\n\n'
    '"Điểm toán (math score) trung bình của toàn bộ học sinh là bao nhiêu?"\n\n'
    '"Có bao nhiêu học sinh đã hoàn thành khóa luyện thi (test prep course = \'completed\')?"'
)


def test_health_reports_v3(fake_v3_llm):
    client = TestClient(create_app())
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["graph_version"] == "v3"


def test_query_endpoint_accepts_v3(fake_v3_llm):
    client = TestClient(create_app())
    response = client.post(
        "/query",
        json={
            "query": MULTI_QUERY,
            "thread_id": "api-v3",
            "version": "v3",
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["intent"] == "sql"
    assert body["used_tools"] == ["ask_sql_analyst_parallel"]


def test_query_endpoint_rejects_legacy_versions(fake_v3_llm):
    client = TestClient(create_app())
    response = client.post(
        "/query",
        json={
            "query": "Điểm toán trung bình là bao nhiêu?",
            "thread_id": "api-v2-rejected",
            "version": "v2",
        },
    )

    assert response.status_code == 422


def test_health_includes_app_mode(fake_v3_llm):
    client = TestClient(create_app())
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["app_mode"] in {"full", "demo"}


def test_ready_reports_checks(fake_v3_llm, monkeypatch):
    from backend.routers import health as health_router

    monkeypatch.setattr(health_router.psycopg, "connect", lambda *_args, **_kwargs: _DummyConn())

    client = TestClient(create_app())
    response = client.get("/ready")

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ready"
    assert "database" in body["checks"]
    assert "artifact_root" in body["checks"]
