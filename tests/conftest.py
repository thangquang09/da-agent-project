from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import load_settings
from data.seeds.create_seed_db import main as seed_main


MULTI_QUERY = (
    '"Có bao nhiêu học sinh nam và bao nhiêu học sinh nữ trong tập dữ liệu này?"\n\n'
    '"Điểm toán (math score) trung bình của toàn bộ học sinh là bao nhiêu?"\n\n'
    '"Có bao nhiêu học sinh đã hoàn thành khóa luyện thi (test prep course = \'completed\')?"'
)


class FakeV3LLMClient:
    def chat_completion(self, **kwargs):  # noqa: ANN003
        messages = kwargs.get("messages", [])
        system = messages[0].get("content", "") if messages else ""
        user = messages[-1].get("content", "") if messages else ""

        if "You are the supervisor of a hierarchical data analyst system." in system:
            return self._leader_response(user)
        if "You are a SQL expert. Generate a read-only SQL query" in system:
            return self._sql_response(user)
        if "You are a helpful data analyst assistant." in system:
            return self._synthesis_response(user)
        if "helpful assistant that summarizes conversation history" in system.lower():
            return self._summary_response()
        return {"choices": [{"message": {"content": "OK"}}]}

    def _leader_response(self, user: str) -> dict:
        has_tool_history = "Tool history:" in user
        if not has_tool_history:
            if MULTI_QUERY in user:
                payload = {
                    "action": "tool",
                    "tool": "ask_sql_analyst_parallel",
                    "args": {
                        "tasks": [
                            {
                                "task_id": "1",
                                "query": "Số lượng học sinh nam và học sinh nữ trong tập dữ liệu là bao nhiêu?",
                            },
                            {
                                "task_id": "2",
                                "query": "Điểm toán (math score) trung bình của toàn bộ học sinh là bao nhiêu?",
                            },
                            {
                                "task_id": "3",
                                "query": "Số lượng học sinh đã hoàn thành khóa luyện thi (test prep course = 'completed') là bao nhiêu?",
                            },
                        ]
                    },
                    "reason": "Independent quantitative sub-questions",
                }
            elif "Retention D1 là gì?" in user:
                payload = {
                    "action": "tool",
                    "tool": "retrieve_rag_answer",
                    "args": {"query": "Retention D1 là gì?"},
                    "reason": "Definition request",
                }
            else:
                payload = {
                    "action": "tool",
                    "tool": "ask_sql_analyst",
                    "args": {"query": self._extract_user_query(user)},
                    "reason": "Needs SQL analysis",
                }
        else:
            query = self._extract_user_query(user)
            payload = {
                "action": "final",
                "answer": self._final_answer_for_query(query),
                "confidence": "high",
                "intent": "rag" if "Retention D1 là gì?" in query else "sql",
                "reason": "Leader finalized from tool results",
            }
        return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}

    def _sql_response(self, user: str) -> dict:
        query = self._extract_sql_question(user)
        sql = "SELECT 1 AS value"
        if "học sinh nam và học sinh nữ" in query or "Có bao nhiêu học sinh nam" in query:
            sql = (
                "SELECT gender, COUNT(*) AS student_count "
                "FROM Performance_of_Stuednts GROUP BY gender"
            )
        elif "Điểm toán" in query and "trung bình" in query:
            sql = 'SELECT AVG("math score") AS average_math_score FROM Performance_of_Stuednts'
        elif "khóa luyện thi" in query or "test prep course" in query:
            sql = (
                'SELECT COUNT(*) AS completed_test_prep_count FROM Performance_of_Stuednts '
                'WHERE "test prep course" = \'completed\''
            )
        elif "Tính tổng điểm 3 môn trung bình theo từng nhóm" in query:
            sql = (
                'SELECT "race/ethnicity" AS race_group, '
                'AVG("math score" + "reading score" + "writing score") AS avg_total_score '
                'FROM Performance_of_Stuednts GROUP BY "race/ethnicity" ORDER BY avg_total_score DESC'
            )
        elif "chỉ tính cho các học sinh nam" in query:
            sql = "SELECT COUNT(*) AS male_students FROM Performance_of_Stuednts WHERE gender = 'male'"
        return {"choices": [{"message": {"content": sql}}]}

    def _synthesis_response(self, user: str) -> dict:
        if "Số lượng học sinh nam và học sinh nữ" in user or "Có bao nhiêu học sinh nam" in user:
            answer = "Có 518 học sinh nữ và 482 học sinh nam trong tập dữ liệu này."
        elif "Điểm toán" in user and "trung bình" in user:
            answer = "Điểm toán trung bình của toàn bộ học sinh là 66.08."
        elif "khóa luyện thi" in user or "test prep course" in user:
            answer = "Có 358 học sinh đã hoàn thành khóa luyện thi."
        elif "Tính tổng điểm 3 môn trung bình theo từng nhóm" in user:
            answer = "Đã tính tổng điểm 3 môn trung bình theo từng nhóm race/group."
        elif "chỉ tính cho các học sinh nam" in user:
            answer = "Chỉ tính cho học sinh nam thì có 482 học sinh."
        else:
            answer = "Không có thông tin."
        return {"choices": [{"message": {"content": answer}}]}

    def _summary_response(self) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": "Cuộc hội thoại tập trung vào phân tích dữ liệu học sinh bằng SQL."
                    }
                }
            ]
        }

    def _extract_user_query(self, user: str) -> str:
        if "User query:\n" in user:
            tail = user.split("User query:\n", 1)[1]
            for marker in (
                "\n\nSession context:\n",
                "\n\nDatabase context (XML):\n",
                "\n\nTool history:\n",
            ):
                if marker in tail:
                    tail = tail.split(marker, 1)[0]
            return tail.strip()
        return user.strip()

    def _extract_sql_question(self, user: str) -> str:
        marker = "Question: "
        if marker in user:
            return user.split(marker, 1)[1].split("\n\n", 1)[0].strip()
        return user.strip()

    def _final_answer_for_query(self, query: str) -> str:
        if query == MULTI_QUERY:
            return (
                "Có 518 học sinh nữ và 482 học sinh nam trong tập dữ liệu này. "
                "Điểm toán trung bình của toàn bộ học sinh là 66.08. "
                "Có 358 học sinh đã hoàn thành khóa luyện thi."
            )
        if "Retention D1 là gì?" in query:
            return "Không có thông tin"
        if "Điểm toán trung bình" in query or "math score" in query:
            return "Điểm toán trung bình của toàn bộ học sinh là 66.08."
        if "Tính tổng điểm 3 môn trung bình theo từng nhóm" in query:
            return "Đã tính tổng điểm 3 môn trung bình theo từng nhóm race/group."
        if "chỉ tính cho các học sinh nam" in query:
            return "Chỉ tính cho học sinh nam thì có 482 học sinh."
        return "Không có thông tin."


@pytest.fixture(scope="session", autouse=True)
def seeded_sqlite_db():
    load_settings.cache_clear()
    seed_main()
    yield
    load_settings.cache_clear()


@pytest.fixture(autouse=True)
def reset_settings_cache():
    load_settings.cache_clear()
    yield
    load_settings.cache_clear()


@pytest.fixture
def fake_v3_llm(monkeypatch):
    client = FakeV3LLMClient()
    monkeypatch.setattr("app.graph.nodes.LLMClient.from_env", lambda: client)
    monkeypatch.setattr("app.graph.sql_worker_graph.LLMClient.from_env", lambda: client)
    yield client


@pytest.fixture
def analytics_db_path() -> str:
    return str(Path("data/warehouse/analytics.db"))
