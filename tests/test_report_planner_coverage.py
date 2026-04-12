from __future__ import annotations

import json

from app.graph.report_subgraph import report_planner_node, report_writer_node


def test_report_planner_does_not_silently_drop_must_questions(monkeypatch):
    class _FakePlannerClient:
        def chat_completion(self, **kwargs):  # noqa: ANN003
            payload = {
                "title": "Titanic report",
                "executive_summary_instruction": "Summarize the main findings.",
                "sections": [
                    {
                        "section_id": "sec-1",
                        "title": "Survival by gender",
                        "analysis_query": "Tỷ lệ sống sót theo giới tính là bao nhiêu?",
                        "analysis_type": "comparative",
                        "target_metrics": ["survival_rate"],
                        "target_dimensions": ["sex"],
                        "expected_grain": "gender",
                        "confidence_notes": "Grounded by passenger counts and survival labels.",
                        "requires_visualization": True,
                        "inclusion_reason": "Directly answers the gender question.",
                        "addresses_question_ids": ["q1"],
                        "tests_hypothesis_ids": [],
                    }
                ],
                "conclusion_instruction": "Conclude cautiously.",
                "coverage_summary": {
                    "covered_question_ids": ["q1"],
                    "unanswered_question_ids": [],
                },
                "unresolved_items": [],
            }
            return {
                "choices": [
                    {"message": {"content": json.dumps(payload, ensure_ascii=False)}}
                ]
            }

    monkeypatch.setattr(
        "app.graph.report_subgraph.LLMClient.from_env",
        lambda: _FakePlannerClient(),
    )

    update = report_planner_node(
        {
            "report_request": "Viết report Titanic và trả lời hai câu hỏi bắt buộc.",
            "report_original_request": "Viết report Titanic và trả lời hai câu hỏi bắt buộc.",
            "report_user_objective": "Viết report Titanic",
            "report_user_questions": [
                {
                    "question_id": "q1",
                    "text": "Tỷ lệ sống sót theo giới tính là bao nhiêu?",
                    "priority": "must",
                    "source": "current_query",
                    "intent_type": "comparison",
                },
                {
                    "question_id": "q2",
                    "text": "Nhóm tuổi nào có tỷ lệ sống sót thấp nhất?",
                    "priority": "must",
                    "source": "current_query",
                    "intent_type": "ranking",
                },
            ],
            "report_user_hypotheses": [],
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
                "dataset_summary": "Titanic passenger survival dataset.",
                "profiling_risks": [],
            },
            "report_planning_brief": {
                "original_request": "Viết report Titanic và trả lời hai câu hỏi bắt buộc.",
                "objective": "Viết report Titanic",
                "user_questions": [
                    {
                        "question_id": "q1",
                        "text": "Tỷ lệ sống sót theo giới tính là bao nhiêu?",
                        "priority": "must",
                    },
                    {
                        "question_id": "q2",
                        "text": "Nhóm tuổi nào có tỷ lệ sống sót thấp nhất?",
                        "priority": "must",
                    },
                ],
                "user_hypotheses": [],
                "constraints": {"answer_style": "analyst"},
                "followup_context": {"followup_mode": "fresh_query"},
                "answerable_question_ids": ["q1", "q2"],
                "risky_question_ids": [],
                "unanswerable_question_ids": [],
                "hypothesis_assessment": [],
                "domain_context": "Titanic passenger survival dataset.",
                "planning_risks": [],
                "suggested_analytical_directions": ["survival breakdown"],
            },
            "session_context": "",
            "xml_database_context": "<database></database>",
        }
    )

    covered_ids = set(update["report_question_coverage"]["covered_question_ids"])
    unresolved_ids = {
        item.get("question_id")
        for item in update["report_unresolved_items"]
        if item.get("question_id")
    }
    addressed_ids = {
        question_id
        for section in update["_report_sections_planned"]
        for question_id in section.get("addresses_question_ids", [])
    }

    assert "q1" in addressed_ids
    assert "q2" in addressed_ids or "q2" in unresolved_ids
    assert update["report_question_coverage"]["dropped_must_question_ids"] == []
    assert covered_ids | unresolved_ids == {"q1", "q2"}


def test_report_writer_fallback_includes_unresolved_questions_block(monkeypatch):
    class _FailingWriterClient:
        def chat_completion(self, **kwargs):  # noqa: ANN003
            raise TimeoutError("timed out")

    monkeypatch.setattr(
        "app.graph.report_subgraph.LLMClient.from_env",
        lambda: _FailingWriterClient(),
    )

    update = report_writer_node(
        {
            "report_original_request": "Write a Titanic report and explain unresolved questions.",
            "report_plan": {"title": "Titanic report"},
            "report_sections": [
                {
                    "section_id": "sec-1",
                    "title": "Survival by gender",
                    "status": "done",
                    "analysis_status": "done",
                    "analysis_query": "Survival by gender",
                    "insight_markdown": "Women had a higher observed survival rate than men.",
                    "insight_citations": [],
                    "limitations": [],
                    "semantic_warnings": [],
                    "section_confidence": "high",
                }
            ],
            "report_user_questions": [
                {
                    "question_id": "q2",
                    "text": "What caused younger passengers to survive at different rates?",
                    "priority": "must",
                }
            ],
            "report_unresolved_items": [
                {
                    "item_type": "question",
                    "question_id": "q2",
                    "reason": "The current data does not identify the causal mechanism.",
                }
            ],
        }
    )

    assert "## Executive Summary" in update["report_draft"]
    assert "## Questions Requiring Follow-up" in update["report_draft"]
    assert (
        "What caused younger passengers to survive at different rates?"
        in update["report_draft"]
    )
    assert "## Recommendations" in update["report_draft"]


def test_safe_report_markdown_localizes_vietnamese_headings():
    from app.graph.report_subgraph import _build_safe_report_markdown

    report = _build_safe_report_markdown(
        {
            "report_original_request": "Viết báo cáo về doanh thu theo khu vực.",
            "report_constraints": {"output_language": "vi"},
            "report_plan": {"title": "Báo cáo doanh thu"},
            "report_sections": [
                {
                    "title": "Tổng quan khu vực",
                    "status": "done",
                    "insight_markdown": "Doanh thu tập trung ở miền Nam.",
                    "limitations": [],
                }
            ],
            "report_unresolved_items": [
                {
                    "item_type": "question",
                    "question_id": "q1",
                    "reason": "Thiếu dữ liệu chi phí.",
                }
            ],
            "report_user_questions": [
                {"question_id": "q1", "text": "Vì sao lợi nhuận giảm?"}
            ],
        }
    )

    assert "## Tóm tắt điều hành" in report
    assert "## Câu hỏi cần làm rõ thêm" in report
    assert "## Kết luận" in report
    assert "## Khuyến nghị" in report
