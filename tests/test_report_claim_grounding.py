from __future__ import annotations

import json

from app.graph.report_subgraph import section_claim_builder_node, section_pipeline_node


def test_section_claim_builder_requires_evidence_refs(monkeypatch):
    class _FakeClaimBuilderClient:
        def chat_completion(self, **kwargs):  # noqa: ANN003
            payload = {
                "claims": [
                    {
                        "claim_id": "sec-1-claim-1",
                        "claim_type": "comparison",
                        "text": "Nhóm nữ có tỷ lệ sống sót cao hơn nhóm nam.",
                        "evidence_refs": ["sec-1.grouped_rows"],
                        "caveats": [],
                        "confidence": "high",
                        "recommendation_ready": True,
                    }
                ],
                "limitations": [],
            }
            return {
                "choices": [
                    {"message": {"content": json.dumps(payload, ensure_ascii=False)}}
                ]
            }

    monkeypatch.setattr(
        "app.graph.report_subgraph.LLMClient.from_env",
        lambda: _FakeClaimBuilderClient(),
    )

    update = section_claim_builder_node(
        {
            "report_original_request": "Viết report Titanic.",
            "_current_section_result": {
                "section_id": "sec-1",
                "title": "Tỷ lệ sống sót theo giới tính",
                "status": "done",
                "plan": {
                    "section_id": "sec-1",
                    "title": "Tỷ lệ sống sót theo giới tính",
                },
                "evidence_packets": [
                    {
                        "packet_id": "packet-1",
                        "section_id": "sec-1",
                        "request_id": "req-1",
                        "quality_warnings": [],
                        "evidence_paths": ["sec-1.grouped_rows"],
                    }
                ],
                "limitations": [],
            },
        }
    )

    claims = update["_current_claims"]
    assert len(claims) == 1
    assert claims[0]["evidence_refs"] == ["sec-1.grouped_rows"]
    assert (
        update["_current_section_result"]["claims"][0]["recommendation_ready"] is True
    )


def test_section_pipeline_emits_evidence_packets_and_claims(
    fake_v3_llm, fake_report_analysis, monkeypatch
):
    class _FakeWorker:
        def invoke(self, task_input):  # noqa: ANN001
            return {
                "status": "success",
                "sql_result": {
                    "rows": [
                        {"gender": "female", "student_count": 518},
                        {"gender": "male", "student_count": 482},
                    ],
                    "row_count": 2,
                },
                "generated_sql": 'SELECT gender, COUNT(*) AS student_count FROM "Performance_of_Stuednts" GROUP BY gender',
                "validated_sql": 'SELECT gender, COUNT(*) AS student_count FROM "Performance_of_Stuednts" GROUP BY gender',
                "result_ref": None,
            }

    monkeypatch.setattr(
        "app.graph.report_subgraph.get_sql_worker_graph",
        lambda: _FakeWorker(),
    )

    update = section_pipeline_node(
        {
            "report_request": "Viết báo cáo về dữ liệu học sinh.",
            "report_original_request": "Viết báo cáo về dữ liệu học sinh.",
            "thread_id": "report-claims",
            "conversation_turn": 3,
            "_current_section": {
                "section_id": "sec-1",
                "title": "Cơ cấu giới tính",
                "business_question": "Có bao nhiêu học sinh nam và bao nhiêu học sinh nữ?",
                "analysis_query": "Có bao nhiêu học sinh nam và bao nhiêu học sinh nữ trong tập dữ liệu này?",
                "analysis_type": "comparative",
                "target_metrics": ["student_count"],
                "target_dimensions": ["gender"],
                "expected_grain": "gender",
                "requires_visualization": True,
                "section_order": 1,
                "inclusion_reason": "Demographic split.",
                "addresses_question_ids": [],
                "tests_hypothesis_ids": [],
                "must_include": False,
            },
        }
    )

    section = update["_report_sections_raw"][0]
    assert section["status"] == "done"
    assert section["evidence_packets"]
    assert section["claims"]
    assert section["claims"][0]["evidence_refs"]
    assert section["insight_markdown"]


def test_section_claim_builder_falls_back_when_model_returns_invalid_refs(monkeypatch):
    class _FakeClaimBuilderClient:
        def chat_completion(self, **kwargs):  # noqa: ANN003
            payload = {
                "claims": [
                    {
                        "claim_id": "sec-1-claim-1",
                        "claim_type": "comparison",
                        "text": "Unsupported claim refs.",
                        "evidence_refs": ["sec-1.not_real"],
                        "caveats": [],
                        "confidence": "high",
                        "recommendation_ready": True,
                    }
                ],
                "limitations": [],
            }
            return {
                "choices": [
                    {"message": {"content": json.dumps(payload, ensure_ascii=False)}}
                ]
            }

    monkeypatch.setattr(
        "app.graph.report_subgraph.LLMClient.from_env",
        lambda: _FakeClaimBuilderClient(),
    )

    update = section_claim_builder_node(
        {
            "report_original_request": "Viết report Titanic.",
            "_current_section_result": {
                "section_id": "sec-1",
                "title": "Tỷ lệ sống sót theo giới tính",
                "status": "done",
                "section_confidence": "medium",
                "plan": {
                    "section_id": "sec-1",
                    "title": "Tỷ lệ sống sót theo giới tính",
                },
                "evidence_packets": [
                    {
                        "packet_id": "packet-1",
                        "section_id": "sec-1",
                        "request_id": "req-1",
                        "quality_warnings": [],
                        "grouped_rows": [{"gender": "female", "count": 10}],
                        "evidence_paths": ["sec-1.grouped_rows", "sec-1.metrics"],
                    }
                ],
                "limitations": [],
            },
        }
    )

    claims = update["_current_claims"]
    assert len(claims) == 1
    assert claims[0]["evidence_refs"]
    assert claims[0]["evidence_refs"] != ["sec-1.not_real"]
