from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import load_settings
from app.tools.visualization import ReportAnalysisResult
from data.seeds.create_seed_db import main as seed_main


MULTI_QUERY = (
    '"Có bao nhiêu học sinh nam và bao nhiêu học sinh nữ trong tập dữ liệu này?"\n\n'
    '"Điểm toán (math score) trung bình của toàn bộ học sinh là bao nhiêu?"\n\n'
    "\"Có bao nhiêu học sinh đã hoàn thành khóa luyện thi (test prep course = 'completed')?\""
)

REPORT_QUERY = "Hãy viết báo cáo phân tích chi tiết về tập dữ liệu này"
REPORT_WITH_VIZ_QUERY = (
    "Tạo một bảng báo cáo chi tiết về data Performance_of_Stuednts.csv nhé, "
    "có các biểu đồ trực quan hóa trả về cho tôi báo cáo chi tiết"
)


class FakeV3LLMClient:
    def chat_completion(self, **kwargs):  # noqa: ANN003
        messages = kwargs.get("messages", [])
        system = (
            self._flatten_content(messages[0].get("content", "")) if messages else ""
        )
        user = (
            self._flatten_content(messages[-1].get("content", "")) if messages else ""
        )

        if "You are the supervisor of a hierarchical data analyst system." in system:
            return self._leader_response(user)
        if "Bạn là Task Grounder" in system or "You are Task Grounder" in system:
            return self._task_grounder_response(user)
        if "You are a data domain analyst." in system:
            return self._report_data_profiler_response(user)
        if "You are a data analysis report planner." in system:
            return self._report_planner_response(user)
        if (
            "You are the Report Insight Generator for a grounded analytics system."
            in system
        ):
            return self._report_insight_response(user)
        if (
            "You are a professional data analyst report writer." in system
            or "You are a professional data analyst report assembler." in system
        ):
            return self._report_writer_response(user)
        if "You are a report critic for a data analysis system." in system:
            return self._report_critic_response(user)
        if (
            "You are a SQL expert. Generate a read-only SQL query" in system
            or "You are a PostgreSQL expert. Generate a read-only SQL query" in system
            or "You are a PostgreSQL expert. Fix the failed SQL query below." in system
        ):
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
            elif REPORT_QUERY in user:
                payload = {
                    "action": "tool",
                    "tool": "generate_report",
                    "args": {"query": REPORT_QUERY},
                    "reason": "Explicit report request",
                }
            else:
                payload = {
                    "action": "tool",
                    "tool": "ask_sql_analyst",
                    "args": {"query": self._extract_user_query(user)},
                    "reason": "Needs SQL analysis",
                }
        else:
            if MULTI_QUERY in user:
                query = MULTI_QUERY
            else:
                query = self._extract_user_query(user)
            payload = {
                "action": "final",
                "answer": self._final_answer_for_query(query),
                "confidence": "high",
                "intent": "rag" if "Retention D1 là gì?" in query else "sql",
                "reason": "Leader finalized from tool results",
            }
        return {
            "choices": [
                {"message": {"content": json.dumps(payload, ensure_ascii=False)}}
            ]
        }

    def _report_insight_response(self, user: str) -> dict:
        if "Cơ cấu giới tính" in user:
            payload = {
                "insight_markdown": (
                    "Biểu đồ cho thấy phân bổ giới tính khá cân bằng, với 518 học sinh nữ và 482 học sinh nam."
                ),
                "citations": [
                    {"json_path": "rankings.top_items[0].value", "value": "518"},
                    {"json_path": "rankings.top_items[1].value", "value": "482"},
                ],
                "limitations": [],
            }
        else:
            payload = {
                "insight_markdown": (
                    "Giá trị trung bình của điểm toán trong tập dữ liệu là 66.08."
                ),
                "citations": [
                    {"json_path": "metrics.average_math_score.value", "value": "66.08"},
                ],
                "limitations": [],
            }
        return {
            "choices": [
                {"message": {"content": json.dumps(payload, ensure_ascii=False)}}
            ]
        }

    def _report_planner_response(self, user: str) -> dict:
        payload = {
            "title": "Báo cáo phân tích dữ liệu học sinh",
            "executive_summary_instruction": "Tóm tắt các phát hiện quan trọng nhất.",
            "sections": [
                {
                    "section_id": "1",
                    "title": "Cơ cấu giới tính",
                    "analysis_query": "Có bao nhiêu học sinh nam và bao nhiêu học sinh nữ trong tập dữ liệu này?",
                    "analysis_type": "comparative",
                    "target_metrics": ["student_count"],
                    "target_dimensions": ["gender"],
                    "expected_grain": "gender",
                    "confidence_notes": "Counts are straightforward if grouping is preserved.",
                },
                {
                    "section_id": "2",
                    "title": "Điểm toán trung bình",
                    "analysis_query": "Điểm toán (math score) trung bình của toàn bộ học sinh là bao nhiêu?",
                    "analysis_type": "descriptive",
                    "target_metrics": ["average_math_score"],
                    "target_dimensions": [],
                    "expected_grain": "dataset",
                    "confidence_notes": "Average score should remain descriptive.",
                },
            ],
            "conclusion_instruction": "Kết luận ngắn gọn dựa trên dữ liệu.",
        }
        return {
            "choices": [
                {"message": {"content": json.dumps(payload, ensure_ascii=False)}}
            ]
        }

    def _report_data_profiler_response(self, user: str) -> dict:
        payload = {
            "domain_summary": "Dataset ghi nhận kết quả học tập của học sinh theo giới tính và điểm số.",
            "key_metrics": ["math score"],
            "key_dimensions": ["gender"],
            "analytical_angles": ["student performance", "gender comparison"],
            "suggested_sections": [
                {
                    "title": "Cơ cấu giới tính",
                    "rationale": "Cho biết phân bổ học sinh theo giới tính.",
                    "analysis_query": "Có bao nhiêu học sinh nam và bao nhiêu học sinh nữ trong tập dữ liệu này?",
                    "analysis_type": "comparative",
                    "target_metrics": ["student_count"],
                    "target_dimensions": ["gender"],
                    "expected_grain": "gender",
                    "confidence_notes": "Counts are straightforward if grouping is preserved.",
                    "requires_visualization": True,
                },
                {
                    "title": "Điểm toán trung bình",
                    "rationale": "Tóm tắt hiệu suất học tập tổng thể.",
                    "analysis_query": "Điểm toán (math score) trung bình của toàn bộ học sinh là bao nhiêu?",
                    "analysis_type": "descriptive",
                    "target_metrics": ["average_math_score"],
                    "target_dimensions": [],
                    "expected_grain": "dataset",
                    "confidence_notes": "Average score should remain descriptive.",
                    "requires_visualization": False,
                },
            ],
        }
        return {
            "choices": [
                {"message": {"content": json.dumps(payload, ensure_ascii=False)}}
            ]
        }

    def _task_grounder_response(self, user: str) -> dict:
        query = self._flatten_content(user)
        if REPORT_QUERY in query or REPORT_WITH_VIZ_QUERY in query:
            payload = {
                "task_mode": "simple",
                "data_source": "uploaded_table"
                if REPORT_WITH_VIZ_QUERY in query
                else "database",
                "required_capabilities": (
                    ["sql", "visualization", "report"]
                    if REPORT_WITH_VIZ_QUERY in query
                    else ["report"]
                ),
                "followup_mode": "fresh_query",
                "confidence": "high",
                "reasoning": "Explicit report request.",
            }
        elif "Retention D1 là gì?" in query:
            payload = {
                "task_mode": "simple",
                "data_source": "knowledge",
                "required_capabilities": ["rag"],
                "followup_mode": "fresh_query",
                "confidence": "high",
                "reasoning": "Definition request.",
            }
        else:
            payload = {
                "task_mode": "simple",
                "data_source": "database",
                "required_capabilities": ["sql"],
                "followup_mode": "fresh_query",
                "confidence": "high",
                "reasoning": "Structured data query.",
            }
        return {
            "choices": [
                {"message": {"content": json.dumps(payload, ensure_ascii=False)}}
            ]
        }

    def _report_writer_response(self, user: str) -> dict:
        content = (
            "# Báo cáo phân tích dữ liệu học sinh\n\n"
            "## Tóm tắt điều hành\n\n"
            "Dữ liệu cho thấy có 518 học sinh nữ và 482 học sinh nam. "
            "Điểm toán trung bình của toàn bộ học sinh là 66.08.\n\n"
            "## Cơ cấu giới tính\n\n"
            "Có 518 học sinh nữ và 482 học sinh nam trong tập dữ liệu này.\n\n"
            "## Điểm toán trung bình\n\n"
            "Điểm toán trung bình của toàn bộ học sinh là 66.08.\n"
        )
        return {"choices": [{"message": {"content": content}}]}

    def _report_critic_response(self, user: str) -> dict:
        payload = {
            "verdict": "APPROVED",
            "issues": [],
            "summary": "Draft is grounded in the provided SQL evidence.",
        }
        return {
            "choices": [
                {"message": {"content": json.dumps(payload, ensure_ascii=False)}}
            ]
        }

    def _sql_response(self, user: str) -> dict:
        query = self._extract_sql_question(user)
        sql = "SELECT 1 AS value"
        if (
            "học sinh nam và học sinh nữ" in query
            or "Có bao nhiêu học sinh nam" in query
            or "giới tính nam" in query
        ):
            sql = (
                "SELECT COUNT(*) AS male_students "
                "FROM \"Performance_of_Stuednts\" WHERE gender = 'male'"
                if "giới tính nam" in query
                else 'SELECT gender, COUNT(*) AS student_count FROM "Performance_of_Stuednts" GROUP BY gender'
            )
        elif "Điểm toán" in query and "trung bình" in query:
            sql = 'SELECT AVG("math score") AS average_math_score FROM "Performance_of_Stuednts"'
        elif "khóa luyện thi" in query or "test prep course" in query:
            sql = (
                'SELECT COUNT(*) AS completed_test_prep_count FROM "Performance_of_Stuednts" '
                "WHERE \"test prep course\" = 'completed'"
            )
        elif "Tính tổng điểm 3 môn trung bình theo từng nhóm" in query:
            sql = (
                'SELECT "race/ethnicity" AS race_group, '
                'AVG("math score" + "reading score" + "writing score") AS avg_total_score '
                'FROM "Performance_of_Stuednts" GROUP BY "race/ethnicity" ORDER BY avg_total_score DESC'
            )
        elif "chỉ tính cho các học sinh nam" in query:
            sql = "SELECT COUNT(*) AS male_students FROM \"Performance_of_Stuednts\" WHERE gender = 'male'"
        return {"choices": [{"message": {"content": sql}}]}

    def _synthesis_response(self, user: str) -> dict:
        if (
            "Số lượng học sinh nam và học sinh nữ" in user
            or "Có bao nhiêu học sinh nam" in user
        ):
            answer = "Có 518 học sinh nữ và 482 học sinh nam trong tập dữ liệu này."
        elif "giới tính nam" in user:
            answer = "Có 482 người giới tính nam trong dữ liệu này."
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
        if REPORT_QUERY in query:
            return (
                "# Báo cáo phân tích dữ liệu học sinh\n\n"
                "Dữ liệu cho thấy có 518 học sinh nữ và 482 học sinh nam. "
                "Điểm toán trung bình của toàn bộ học sinh là 66.08."
            )
        if "giới tính nam" in query:
            return "Có 482 người giới tính nam trong dữ liệu này."
        if "Điểm toán trung bình" in query or "math score" in query:
            return "Điểm toán trung bình của toàn bộ học sinh là 66.08."
        if "Tính tổng điểm 3 môn trung bình theo từng nhóm" in query:
            return "Đã tính tổng điểm 3 môn trung bình theo từng nhóm race/group."
        if "chỉ tính cho các học sinh nam" in query:
            return "Chỉ tính cho học sinh nam thì có 482 học sinh."
        return "Không có thông tin."

    def _flatten_content(self, content: object) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
            return "\n".join(parts)
        return str(content)


_TEST_THREAD_IDS = [
    "v3-single-query",
    "v3-multi-query",
    "v3-rag-stub",
    "v3-simple-male-query",
    "v3-report-query",
    "v3-retry-test-1",
    "v3-retry-test-2",
    "v3-retry-test-3",
    # backend API tests
    "api-v3",
    "api-v2-rejected",
    # observability tests
    "trace-v3-parallel",
    "trace-v3-single",
]


@pytest.fixture(scope="session", autouse=True)
def seeded_sqlite_db():
    load_settings.cache_clear()
    try:
        seed_main()
    except Exception:  # noqa: BLE001
        # No PostgreSQL available — skip seeding; tests that depend on the DB
        # will be skipped or fail with a clear error at the test level.
        pass
    yield
    load_settings.cache_clear()


@pytest.fixture(autouse=True)
def reset_settings_cache():
    load_settings.cache_clear()
    yield
    load_settings.cache_clear()


@pytest.fixture(autouse=True)
def clean_test_conversation_memory():
    """Clear all test thread IDs before every test.

    Ensures agent schemas exist and clears test thread data
    from PostgreSQL-backed conversation memory.
    """
    try:
        from data.migrations.create_schemas import run as ensure_schemas

        ensure_schemas()
    except Exception:  # noqa: BLE001
        pass

    from app.memory.conversation_store import get_conversation_memory_store

    try:
        store = get_conversation_memory_store()
        for tid in _TEST_THREAD_IDS:
            store.clear_thread(tid)
    except Exception:  # noqa: BLE001
        # If Postgres is unavailable, skip silently
        pass
    yield


@pytest.fixture
def fake_v3_llm(monkeypatch):
    client = FakeV3LLMClient()
    monkeypatch.setattr("app.graph.nodes.LLMClient.from_env", lambda: client)
    monkeypatch.setattr("app.graph.sql_worker_graph.LLMClient.from_env", lambda: client)
    monkeypatch.setattr("app.graph.report_subgraph.LLMClient.from_env", lambda: client)
    yield client


@pytest.fixture
def fake_report_analysis(monkeypatch):
    def _fake_generate_grounded_report_analysis(
        *, data_rows, user_query, section_title
    ):  # noqa: ANN001
        if "giới tính" in user_query.lower():
            computed_stats = {
                "row_count": 2,
                "metrics": {},
                "series": [
                    {"x": "female", "y": 518, "display_y": "518"},
                    {"x": "male", "y": 482, "display_y": "482"},
                ],
                "rankings": {
                    "top_items": [
                        {"label": "female", "value": 518, "display_value": "518"},
                        {"label": "male", "value": 482, "display_value": "482"},
                    ]
                },
                "comparisons": {},
                "data_quality": {"warnings": []},
            }
            chart_manifest = {
                "chart_type": "bar",
                "x_field": "gender",
                "y_field": "student_count",
            }
        else:
            computed_stats = {
                "row_count": 1,
                "metrics": {
                    "average_math_score": {"value": 66.08, "display_value": "66.08"}
                },
                "series": [
                    {"x": "average_math_score", "y": 66.08, "display_y": "66.08"}
                ],
                "rankings": {},
                "comparisons": {},
                "data_quality": {"warnings": []},
            }
            chart_manifest = {
                "chart_type": "bar",
                "x_field": "metric",
                "y_field": "value",
            }

        return ReportAnalysisResult(
            success=True,
            computed_stats=computed_stats,
            chart_manifest=chart_manifest,
            chart_html=f'<div data-report-analysis="true"><h3>{section_title}</h3></div>',
            image_data=b"fake-png-bytes",
            image_format="png",
            code_executed="print('ok')",
            execution_time_ms=12.0,
        )

    service = type(
        "FakeVisualizationService",
        (),
        {
            "generate_grounded_report_analysis": staticmethod(
                _fake_generate_grounded_report_analysis
            )
        },
    )()
    monkeypatch.setattr(
        "app.graph.report_subgraph.get_visualization_service", lambda: service
    )
    return service


@pytest.fixture
def analytics_db_path() -> None:
    """Legacy fixture — no longer uses SQLite file.

    Returns None so tests that pass this to graph nodes get the default
    PostgreSQL connection via DATABASE_URL.
    """
    return None
