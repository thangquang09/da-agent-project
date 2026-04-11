"""Tests for Phase 3 artifact system: accumulation, task_profile injection, and evaluator wiring.

These tests do NOT require a live PostgreSQL instance.
Tests that would call run_query with a real DB are refactored to use
unit-level mocks (mocking get_schema_overview and LLM calls directly).

Fixtures:
- seeded_sqlite_db: provided by conftest.py (requires PostgreSQL)
- analytics_db_path: provided by conftest.py (requires seeded_sqlite_db)

Since this environment may not have PostgreSQL running, integration-style tests
that would need a real DB are skipped via pytest.mark.skip unless
DATABASE_URL is set and reachable.
"""

from __future__ import annotations

import json

import pytest

from app.graph.graph import build_sql_v3_graph, _route_after_leader
from app.graph.nodes import (
    _format_leader_plan,
    _normalize_leader_plan,
    _evaluate_artifacts,
    artifact_evaluator,
)
from app.graph.task_grounder import _normalize_capabilities
from app.graph.state import AgentState
from app.prompts.manager import PromptManager


# =============================================================================
# Fix 1 — Artifact accumulation in leader_agent  (unit-level mock)
# =============================================================================


def _make_minimal_state(
    db_path: str | None = None,
    artifacts: list | None = None,
    task_profile: dict | None = None,
) -> AgentState:
    """Minimal AgentState for unit-testing leader_agent without a live DB."""
    state: AgentState = {
        "user_query": "Điểm toán trung bình là bao nhiêu?",
        "target_db_path": db_path or ":memory:",
        "schema_context": (
            '{"tables": [{"table_name": "Performance_of_Stuednts", '
            '"columns": [{"name": "math score", "type": "INTEGER"}]}]}'
        ),
        "xml_database_context": (
            "<database_context>\n  <table name='Performance_of_Stuednts'>\n"
            "    <column name='math score' type='INTEGER' />\n"
            "  </table>\n</database_context>"
        ),
        "artifacts": artifacts or [],
        "task_profile": task_profile
        or {
            "task_mode": "simple",
            "data_source": "database",
            "required_capabilities": ["sql"],
            "followup_mode": "fresh_query",
            "confidence": "high",
            "reasoning": "unit test",
        },
        "session_context": "",
        "uploaded_file_data": [],
        "errors": [],
        "tool_history": [],
        "step_count": 0,
    }
    return state


class FakeLeaderLLM:
    """Returns a tool call on first invocation, then final on second."""

    def __init__(self) -> None:
        self.call_count = 0

    def chat_completion(self, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "action": "tool",
                                    "tool": "ask_sql_analyst",
                                    "args": {
                                        "query": "Điểm toán trung bình là bao nhiêu?"
                                    },
                                    "reason": "Needs SQL",
                                }
                            )
                        }
                    }
                ]
            }
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "action": "final",
                                "answer": "Điểm toán trung bình là 66.08.",
                                "confidence": "high",
                                "intent": "sql",
                                "reason": "Done",
                            }
                        )
                    }
                }
            ]
        }


class FakeSQLWorkerLLM:
    """Returns a valid SELECT statement for the test schema."""

    def chat_completion(self, **kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "content": 'SELECT AVG("math score") FROM Performance_of_Stuednts'
                    }
                }
            ]
        }


class FakeLeaderPlanLLM:
    """Returns a tool call with a structured micro-plan, then final."""

    def __init__(self) -> None:
        self.call_count = 0

    def chat_completion(self, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "action": "tool",
                                    "tool": "ask_sql_analyst_parallel",
                                    "args": {
                                        "tasks": [
                                            {
                                                "query": "Doanh thu theo danh mục tháng này"
                                            },
                                            {
                                                "query": "Doanh thu theo khu vực tháng này"
                                            },
                                        ]
                                    },
                                    "reason": "Need segmented diagnostic evidence",
                                    "plan": {
                                        "goal": "Tìm các chiều đóng góp vào sụt giảm doanh thu",
                                        "dimensions_to_check": [
                                            "category",
                                            "region",
                                            "time",
                                        ],
                                        "why_this_tool": "Cần nhiều truy vấn độc lập để so sánh các chiều",
                                        "success_criteria": "Xác định được các nhóm giảm mạnh nhất với số liệu cụ thể",
                                    },
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "action": "final",
                                "answer": "Danh mục A và khu vực North giảm mạnh nhất.",
                                "confidence": "high",
                                "intent": "sql",
                                "reason": "Done",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }


def test_leader_agent_returns_artifacts_key(monkeypatch):
    """leader_agent must return state containing the 'artifacts' key."""
    from app.graph.nodes import leader_agent

    fake_llm = FakeLeaderLLM()
    fake_sql = FakeSQLWorkerLLM()

    def fake_get_schema_overview(**kwargs):
        return {
            "tables": [
                {
                    "table_name": "Performance_of_Stuednts",
                    "columns": [{"name": "math score", "type": "INTEGER"}],
                }
            ]
        }

    monkeypatch.setattr("app.graph.nodes.LLMClient.from_env", lambda: fake_llm)
    monkeypatch.setattr(
        "app.graph.sql_worker_graph.LLMClient.from_env", lambda: fake_sql
    )
    monkeypatch.setattr("app.graph.nodes.get_schema_overview", fake_get_schema_overview)
    monkeypatch.setattr(
        "app.graph.sql_worker_graph.get_schema_overview", fake_get_schema_overview
    )

    state = _make_minimal_state()
    result = leader_agent(state)

    assert isinstance(result, dict)
    assert "artifacts" in result, "leader_agent must return 'artifacts' key"
    assert isinstance(result["artifacts"], list)


def test_leader_agent_populates_sql_result_artifact(monkeypatch):
    """After ask_sql_analyst tool call, artifacts must contain a sql_result entry."""
    from app.graph.nodes import leader_agent

    fake_llm = FakeLeaderLLM()
    fake_sql = FakeSQLWorkerLLM()

    def fake_get_schema_overview(**kwargs):
        return {
            "tables": [
                {
                    "table_name": "Performance_of_Stuednts",
                    "columns": [{"name": "math score", "type": "INTEGER"}],
                }
            ]
        }

    monkeypatch.setattr("app.graph.nodes.LLMClient.from_env", lambda: fake_llm)
    monkeypatch.setattr(
        "app.graph.sql_worker_graph.LLMClient.from_env", lambda: fake_sql
    )
    monkeypatch.setattr("app.graph.nodes.get_schema_overview", fake_get_schema_overview)
    monkeypatch.setattr(
        "app.graph.sql_worker_graph.get_schema_overview", fake_get_schema_overview
    )

    state = _make_minimal_state()
    result = leader_agent(state)
    artifacts = result.get("artifacts", [])

    assert len(artifacts) >= 1, "At least one artifact expected after ask_sql_analyst"
    artifact_types = {a.get("artifact_type") for a in artifacts}
    assert "sql_result" in artifact_types, (
        f"Expected sql_result artifact, got types: {artifact_types}"
    )


def test_leader_agent_artifacts_preserve_on_loop_back(monkeypatch):
    """On loop-back, leader_agent must initialise artifacts from incoming state (merge)."""
    from app.graph.nodes import leader_agent

    # State already carrying one artifact (simulating loop-back from artifact_evaluator)
    existing_artifact = {
        "artifact_type": "rag_context",
        "status": "success",
        "payload": {},
        "evidence": {},
        "terminal": False,
        "recommended_next_action": "finalize",
    }
    state = _make_minimal_state(artifacts=[existing_artifact])

    fake_llm = FakeLeaderLLM()
    monkeypatch.setattr("app.graph.nodes.LLMClient.from_env", lambda: fake_llm)

    result = leader_agent(state)
    artifacts = result.get("artifacts", [])

    # The existing artifact must be preserved
    artifact_types = {a.get("artifact_type") for a in artifacts}
    assert "rag_context" in artifact_types, "Loop-back must preserve existing artifacts"


def test_task_grounder_report_capability_overrides_mixed_caps():
    assert _normalize_capabilities(["sql", "visualization", "report"]) == ["report"]


# =============================================================================
# Fix 2 — task_profile injection into leader prompt
# =============================================================================


def test_prompt_manager_accepts_task_profile_kwarg():
    """PromptManager.leader_agent_messages must accept task_profile kwarg without error."""
    pm = PromptManager()
    messages = pm.leader_agent_messages(
        query="Test query",
        session_context="",
        xml_database_context="",
        scratchpad="",
        task_profile={
            "task_mode": "simple",
            "data_source": "database",
            "required_capabilities": ["sql"],
            "followup_mode": "fresh_query",
            "confidence": "high",
            "reasoning": "test profile injection",
        },
    )
    assert isinstance(messages, list)
    assert len(messages) == 2  # system + user


def test_prompt_manager_injects_task_profile_into_user_message():
    """When task_profile is provided, the user message must contain it as structured JSON."""
    pm = PromptManager()
    profile = {
        "task_mode": "mixed",
        "data_source": "mixed",
        "required_capabilities": ["sql", "visualization"],
        "followup_mode": "followup",
        "confidence": "medium",
        "reasoning": "because it is a mixed query",
    }
    messages = pm.leader_agent_messages(
        query="Test",
        session_context="",
        xml_database_context="",
        scratchpad="",
        task_profile=profile,
    )
    user_content = messages[-1]["content"]
    assert "Task profile" in user_content
    assert "task_mode" in user_content
    assert "mixed" in user_content
    assert "required_capabilities" in user_content


def test_prompt_manager_handles_none_task_profile():
    """leader_agent_messages must not crash when task_profile is None (the default)."""
    pm = PromptManager()
    messages = pm.leader_agent_messages(
        query="Test query",
        session_context="",
        xml_database_context="",
        scratchpad="",
        task_profile=None,
    )
    user_content = messages[-1]["content"]
    # Should NOT contain "Task profile" since it is None
    assert "Task profile" not in user_content


def test_prompt_manager_leader_prompt_documents_micro_plan_schema():
    pm = PromptManager()
    messages = pm.leader_agent_messages(
        query="Vì sao doanh thu giảm?",
        session_context="",
        xml_database_context="",
        scratchpad="",
        task_profile=None,
    )

    system_content = messages[0]["content"]
    assert '"plan":{' in system_content
    assert '"dimensions_to_check"' in system_content
    assert '"success_criteria"' in system_content


def test_normalize_leader_plan_keeps_only_supported_fields():
    plan = _normalize_leader_plan(
        {
            "goal": "Find the drivers of decline",
            "dimensions_to_check": ["category", "region", "", "time"],
            "why_this_tool": "Parallel evidence is needed",
            "success_criteria": "Return top drivers with numbers",
            "extra": "ignore me",
        }
    )

    assert plan == {
        "goal": "Find the drivers of decline",
        "dimensions_to_check": ["category", "region", "time"],
        "why_this_tool": "Parallel evidence is needed",
        "success_criteria": "Return top drivers with numbers",
    }
    assert '"goal": "Find the drivers of decline"' in _format_leader_plan(plan)


def test_leader_agent_records_micro_plan_in_tool_history(monkeypatch):
    from app.graph.nodes import leader_agent

    fake_llm = FakeLeaderPlanLLM()

    def fake_parallel_tool(state, tasks, parent_query):  # noqa: ANN001
        return {
            "status": "ok",
            "task_count": len(tasks),
            "execution_mode": "parallel",
            "answer_summary": "Danh mục A và khu vực North giảm mạnh nhất.",
            "sql_result": {
                "row_count": 2,
                "columns": ["segment", "delta"],
                "rows": [
                    {"segment": "A", "delta": -25},
                    {"segment": "North", "delta": -18},
                ],
            },
            "generated_sql": "SELECT * FROM t",
            "validated_sql": "SELECT * FROM t",
            "tool_history": [],
            "errors": [],
            "result_ref": None,
            "visualization": None,
            "task_results": [
                {
                    "task_id": "1",
                    "query": "Doanh thu theo danh mục tháng này",
                    "status": "success",
                    "sql_result": {
                        "row_count": 1,
                        "rows": [{"segment": "A", "delta": -25}],
                    },
                    "answer_summary": "Danh mục A giảm mạnh.",
                },
                {
                    "task_id": "2",
                    "query": "Doanh thu theo khu vực tháng này",
                    "status": "success",
                    "sql_result": {
                        "row_count": 1,
                        "rows": [{"segment": "North", "delta": -18}],
                    },
                    "answer_summary": "North giảm mạnh.",
                },
            ],
            "artifact_terminal": True,
            "artifact_recommended_action": "finalize",
        }

    monkeypatch.setattr("app.graph.nodes.LLMClient.from_env", lambda: fake_llm)
    monkeypatch.setattr(
        "app.graph.nodes.ask_sql_analyst_parallel_tool", fake_parallel_tool
    )

    result = leader_agent(_make_minimal_state())

    first_entry = result["tool_history"][0]
    assert first_entry["tool"] == "ask_sql_analyst_parallel"
    assert (
        first_entry["plan"]["goal"] == "Tìm các chiều đóng góp vào sụt giảm doanh thu"
    )
    assert first_entry["plan"]["dimensions_to_check"] == [
        "category",
        "region",
        "time",
    ]
    assert result["final_answer"] == "Danh mục A và khu vực North giảm mạnh nhất."


# =============================================================================
# Fix 3 — artifact_evaluator node wired into graph
# =============================================================================


def test_artifact_evaluator_node_registered_in_graph():
    """artifact_evaluator must be a registered node in build_sql_v3_graph()."""
    graph = build_sql_v3_graph()
    assert "artifact_evaluator" in graph.nodes, (
        "artifact_evaluator must be a registered graph node"
    )


def test_evaluate_artifacts_returns_artifact_evaluation_key():
    """_evaluate_artifacts must return state with 'artifact_evaluation' dict."""
    state: AgentState = {
        "artifacts": [
            {
                "artifact_type": "sql_result",
                "status": "success",
                "payload": {},
                "evidence": {},
                "terminal": True,
                "recommended_next_action": "finalize",
            }
        ],
        "task_profile": {
            "task_mode": "simple",
            "data_source": "database",
            "required_capabilities": ["sql"],
            "followup_mode": "fresh_query",
            "confidence": "high",
            "reasoning": "test",
        },
        "step_count": 0,
    }
    result = _evaluate_artifacts(state)
    assert "artifact_evaluation" in result
    eval_data = result["artifact_evaluation"]
    assert "decision" in eval_data
    assert "reason" in eval_data
    assert "collected_types" in eval_data
    assert "missing_types" in eval_data


def test_evaluate_artifacts_decision_finalize_on_terminal():
    """When any artifact has terminal=True, evaluator must return decision='finalize'."""
    state: AgentState = {
        "artifacts": [
            {
                "artifact_type": "chart",
                "status": "success",
                "payload": {},
                "evidence": {},
                "terminal": True,  # terminal artifact
                "recommended_next_action": "finalize",
            }
        ],
        "task_profile": {
            "task_mode": "simple",
            "data_source": "inline_data",
            "required_capabilities": ["visualization"],
            "followup_mode": "fresh_query",
            "confidence": "high",
            "reasoning": "viz only",
        },
        "step_count": 1,
    }
    result = _evaluate_artifacts(state)
    assert result["artifact_evaluation"]["decision"] == "finalize"
    assert result["artifact_evaluation"]["has_terminal"] is True


def test_evaluate_artifacts_decision_continue_when_capabilities_missing():
    """When required_capabilities not yet covered, evaluator returns decision='continue'."""
    state: AgentState = {
        "artifacts": [
            {
                "artifact_type": "sql_result",
                "status": "success",
                "payload": {},
                "evidence": {},
                "terminal": False,
                "recommended_next_action": "finalize",
            }
        ],
        "task_profile": {
            "task_mode": "mixed",
            "data_source": "mixed",
            "required_capabilities": ["sql", "rag"],  # rag not covered
            "followup_mode": "fresh_query",
            "confidence": "medium",
            "reasoning": "mixed query",
        },
        "step_count": 1,
    }
    result = _evaluate_artifacts(state)
    assert result["artifact_evaluation"]["decision"] == "continue"
    assert "rag_context" in result["artifact_evaluation"]["missing_types"]


def test_evaluate_artifacts_decision_finalize_when_all_caps_covered():
    """When all required capabilities are covered, evaluator returns decision='finalize'."""
    state: AgentState = {
        "artifacts": [
            {
                "artifact_type": "sql_result",
                "status": "success",
                "payload": {},
                "evidence": {},
                "terminal": False,
                "recommended_next_action": "finalize",
            },
            {
                "artifact_type": "rag_context",
                "status": "success",
                "payload": {},
                "evidence": {},
                "terminal": False,
                "recommended_next_action": "finalize",
            },
        ],
        "task_profile": {
            "task_mode": "mixed",
            "data_source": "mixed",
            "required_capabilities": ["sql", "rag"],
            "followup_mode": "fresh_query",
            "confidence": "high",
            "reasoning": "both covered",
        },
        "step_count": 2,
    }
    result = _evaluate_artifacts(state)
    assert result["artifact_evaluation"]["decision"] == "finalize"
    assert result["artifact_evaluation"]["missing_types"] == []


def test_evaluate_artifacts_decision_finalize_when_no_caps_required():
    """When task_profile has empty required_capabilities, evaluator returns finalize."""
    state: AgentState = {
        "artifacts": [],
        "task_profile": {
            "task_mode": "simple",
            "data_source": "database",
            "required_capabilities": [],
            "followup_mode": "fresh_query",
            "confidence": "high",
            "reasoning": "no caps needed",
        },
        "step_count": 0,
    }
    result = _evaluate_artifacts(state)
    assert result["artifact_evaluation"]["decision"] == "finalize"


def test_evaluate_artifacts_decision_retry_on_failed_with_retry_signal():
    """Failed artifact with recommended_next_action=retry_sql → decision='retry'."""
    state: AgentState = {
        "artifacts": [
            {
                "artifact_type": "sql_result",
                "status": "failed",
                "payload": {},
                "evidence": {},
                "terminal": False,
                "recommended_next_action": "retry_sql",
            }
        ],
        "task_profile": {
            "task_mode": "simple",
            "data_source": "database",
            "required_capabilities": ["sql"],
            "followup_mode": "fresh_query",
            "confidence": "high",
            "reasoning": "sql failed, needs retry",
        },
        "step_count": 1,
    }
    result = _evaluate_artifacts(state)
    assert result["artifact_evaluation"]["decision"] == "retry"


# =============================================================================
# Routing — _route_after_evaluator
# =============================================================================


def test_route_loops_on_continue():
    """continue decision → leader_agent (loop back)."""
    state: AgentState = {
        "artifact_evaluation": {"decision": "continue"},
        "response_mode": "answer",
    }
    assert _route_after_leader(state) == "leader_agent"


def test_route_loops_on_retry():
    """retry decision → leader_agent (loop back)."""
    state: AgentState = {
        "artifact_evaluation": {"decision": "retry"},
        "response_mode": "answer",
    }
    assert _route_after_leader(state) == "leader_agent"


def test_route_captures_on_finalize():
    """finalize + answer mode → capture_action_node."""
    state: AgentState = {
        "artifact_evaluation": {"decision": "finalize"},
        "response_mode": "answer",
    }
    assert _route_after_leader(state) == "capture_action_node"


def test_route_report_subgraph_on_report_mode():
    """report response_mode → report_subgraph (even after finalize)."""
    state: AgentState = {
        "artifact_evaluation": {"decision": "finalize"},
        "response_mode": "report",
    }
    assert _route_after_leader(state) == "report_subgraph"


def test_route_captures_on_clarify():
    """clarify decision → capture_action_node."""
    state: AgentState = {
        "artifact_evaluation": {"decision": "clarify"},
        "response_mode": "answer",
    }
    assert _route_after_leader(state) == "capture_action_node"


def test_route_defaults_to_finalize_on_missing_evaluation():
    """When artifact_evaluation is absent, routing defaults to finalize."""
    state: AgentState = {
        "response_mode": "answer",
    }
    assert _route_after_leader(state) == "capture_action_node"
