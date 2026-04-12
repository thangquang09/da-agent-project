from __future__ import annotations

import json

from app.graph.report_subgraph import (
    report_brief_builder_node,
    report_dataset_profiler_node,
)


def test_report_dataset_profiler_returns_typed_dataset_profile(monkeypatch):
    class _FakeProfilerClient:
        def chat_completion(self, **kwargs):  # noqa: ANN003
            payload = {
                "candidate_tables": ["students"],
                "selected_tables": ["students"],
                "table_profiles": [
                    {
                        "table_name": "students",
                        "row_estimate": 1000,
                        "columns": ["gender", "math score", "test preparation course"],
                        "likely_metrics": ["math score"],
                        "likely_dimensions": ["gender", "test preparation course"],
                        "time_columns": [],
                        "notes": "Single table with student performance records.",
                    }
                ],
                "join_hints": [],
                "profiling_risks": [
                    "No event timestamp is available for trend analysis."
                ],
                "dataset_summary": "Student performance dataset with demographic and score columns.",
                "key_metrics": ["math score"],
                "key_dimensions": ["gender"],
                "analytical_angles": ["performance overview", "gender comparison"],
            }
            return {
                "choices": [
                    {"message": {"content": json.dumps(payload, ensure_ascii=False)}}
                ]
            }

    monkeypatch.setattr(
        "app.graph.report_subgraph.LLMClient.from_env",
        lambda: _FakeProfilerClient(),
    )

    update = report_dataset_profiler_node(
        {
            "report_original_request": "Viết report về dữ liệu học sinh.",
            "xml_database_context": '<database><table name="students"></table></database>',
            "report_sample_data": {
                "students": {
                    "sample_rows": [{"gender": "female", "math score": 72}],
                    "column_stats": [{"column": "math score", "distinct": 80}],
                    "columns": ["gender", "math score", "test preparation course"],
                    "sample_count": 100,
                    "table_row_count": 1000,
                }
            },
            "table_contexts": {"students": "Student exam performance data."},
        }
    )

    assert update["dataset_profile"]["selected_tables"] == ["students"]
    assert update["dataset_profile"]["table_profiles"][0]["table_name"] == "students"
    assert update["dataset_profile"]["profiling_risks"] == [
        "No event timestamp is available for trend analysis."
    ]
    assert "suggested_sections" not in update["dataset_profile"]
    assert update["report_data_profile"] == update["dataset_profile"]


def test_report_brief_builder_marks_answerability_without_planning_sections(
    monkeypatch,
):
    class _FakeBriefBuilderClient:
        def chat_completion(self, **kwargs):  # noqa: ANN003
            payload = {
                "answerable_question_ids": ["q1"],
                "risky_question_ids": ["q2"],
                "unanswerable_question_ids": [],
                "hypothesis_assessment": [
                    {
                        "hypothesis_id": "h1",
                        "status": "risky",
                        "reason": "The dataset supports comparison, but not causal explanation.",
                    }
                ],
                "domain_context": "Titanic passenger survival dataset with demographics and outcomes.",
                "planning_risks": [
                    "Age coverage is incomplete for some passengers, so age-based findings need caveats."
                ],
                "suggested_analytical_directions": [
                    "survival by demographic segments",
                    "age-group risk profiling",
                ],
            }
            return {
                "choices": [
                    {"message": {"content": json.dumps(payload, ensure_ascii=False)}}
                ]
            }

    monkeypatch.setattr(
        "app.graph.report_subgraph.LLMClient.from_env",
        lambda: _FakeBriefBuilderClient(),
    )

    update = report_brief_builder_node(
        {
            "report_original_request": "Viết report Titanic và trả lời hai câu hỏi cụ thể.",
            "report_user_objective": "Viết report Titanic",
            "report_user_questions": [
                {
                    "question_id": "q1",
                    "text": "Tỷ lệ sống sót theo giới tính là bao nhiêu?",
                    "priority": "must",
                },
                {
                    "question_id": "q2",
                    "text": "Vì sao nhóm tuổi thấp có tỷ lệ sống sót khác biệt?",
                    "priority": "must",
                },
            ],
            "report_user_hypotheses": [
                {
                    "hypothesis_id": "h1",
                    "text": "Giới tính có liên hệ với khả năng sống sót.",
                    "priority": "should",
                }
            ],
            "report_constraints": {"answer_style": "analyst"},
            "report_followup_context": {"followup_mode": "fresh_query"},
            "dataset_profile": {
                "selected_tables": ["titanic"],
                "table_profiles": [
                    {
                        "table_name": "titanic",
                        "columns": ["sex", "age", "survived"],
                    }
                ],
                "profiling_risks": ["Age coverage is incomplete for some passengers."],
                "dataset_summary": "Titanic passenger survival dataset.",
            },
            "table_contexts": {"titanic": "Passenger manifest and survival labels."},
            "report_sample_data": {
                "titanic": {
                    "sample_rows": [{"sex": "female", "age": 29, "survived": 1}],
                    "column_stats": [{"column": "age", "null_count": 0}],
                    "columns": ["sex", "age", "survived"],
                    "sample_count": 50,
                    "table_row_count": 891,
                }
            },
        }
    )

    brief = update["report_planning_brief"]
    assert brief["answerable_question_ids"] == ["q1"]
    assert brief["risky_question_ids"] == ["q2"]
    assert brief["unanswerable_question_ids"] == []
    assert brief["hypothesis_assessment"] == [
        {
            "hypothesis_id": "h1",
            "status": "risky",
            "reason": "The dataset supports comparison, but not causal explanation.",
        }
    ]
    assert brief["domain_context"].startswith("Titanic passenger survival dataset")
    assert brief["suggested_analytical_directions"] == [
        "survival by demographic segments",
        "age-group risk profiling",
    ]
    assert "_report_sections_planned" not in update
