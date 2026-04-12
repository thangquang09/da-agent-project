from __future__ import annotations

from app.graph.report_subgraph import report_finalize_node, report_validator_node
from app.graph.report_validators import (
    run_report_validators,
    validate_section_warning_quality,
)


def test_validate_section_warning_quality_uses_underlying_observation_count():
    issues = validate_section_warning_quality(
        [
            {
                "title": "Grouped output",
                "evidence_packets": [
                    {
                        "quality_warnings": ["small sample"],
                        "underlying_observation_count": 100,
                    }
                ],
            }
        ]
    )

    assert issues == [
        "A section reports a small-sample warning even though the underlying observation count is not small."
    ]


def test_run_report_validators_flags_missing_structure_and_claim_support():
    issues = run_report_validators(
        {"dropped_must_question_ids": ["q1"]},
        [{"item_type": "question", "question_id": "q1", "reason": "No data"}],
        [
            {
                "title": "Section A",
                "status": "done",
                "claims": [
                    {
                        "claim_id": "c1",
                        "text": "A claim without evidence",
                        "evidence_refs": [],
                        "recommendation_ready": False,
                    }
                ],
                "evidence_packets": [],
                "semantic_warnings": ["Needs caution"],
            }
        ],
        "# Report\n\n## Section A\n\nUnsupported summary.",
    )

    assert any("must-answer" in issue for issue in issues)
    assert any("follow-up questions section" in issue for issue in issues)
    assert any("evidence references" in issue for issue in issues)
    assert any("recommendations section" in issue for issue in issues)


def test_run_report_validators_flags_nonexistent_evidence_refs():
    issues = run_report_validators(
        {"dropped_must_question_ids": []},
        [],
        [
            {
                "title": "Section A",
                "status": "done",
                "claims": [
                    {
                        "claim_id": "c1",
                        "text": "Grounded-looking claim",
                        "evidence_refs": ["sec-1.fake_path"],
                        "recommendation_ready": False,
                    }
                ],
                "evidence_packets": [
                    {"evidence_paths": ["sec-1.metrics"], "quality_warnings": []}
                ],
                "semantic_warnings": [],
            }
        ],
        "# Report\n\n## Executive Summary\n\nSummary.\n\n## Section A\n\nBody.\n\n## Conclusion\n\nDone.\n\n## Recommendations\n\n1. Review.",
    )

    assert any("do not exist" in issue for issue in issues)


def test_report_validator_routes_revision_when_structure_is_incomplete(monkeypatch):
    class _ApprovingCriticClient:
        def chat_completion(self, **kwargs):  # noqa: ANN003
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"verdict":"APPROVED","issues":[],"summary":"Looks fine."}'
                        }
                    }
                ]
            }

    monkeypatch.setattr(
        "app.graph.report_subgraph.LLMClient.from_env",
        lambda: _ApprovingCriticClient(),
    )

    update = report_validator_node(
        {
            "report_original_request": "Write a report.",
            "report_sections": [
                {
                    "title": "Section A",
                    "status": "done",
                    "claims": [
                        {
                            "claim_id": "c1",
                            "text": "Revenue was concentrated in one segment.",
                            "evidence_refs": ["sec-1.metrics"],
                            "recommendation_ready": True,
                        }
                    ],
                    "evidence_packets": [
                        {
                            "quality_warnings": [],
                            "underlying_observation_count": 30,
                        }
                    ],
                    "semantic_warnings": [],
                }
            ],
            "report_draft": "# Report\n\n## Section A\n\nRevenue was concentrated in one segment.",
            "report_question_coverage": {"dropped_must_question_ids": []},
            "report_unresolved_items": [],
            "critic_iteration": 0,
            "report_feedback_hash": "",
        }
    )

    assert update["validator_verdict"] == "REVISE"
    assert update["validator_decision"] == "revise"
    assert any(
        "recommendations section" in issue for issue in update["validator_issues"]
    )


def test_report_finalize_keeps_report_markdown_and_charts_on_same_turn(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    update = report_finalize_node(
        {
            "validator_verdict": "APPROVED",
            "report_plan": {"title": "Titanic Report"},
            "report_draft": "# Titanic Report\n\n## Executive Summary\n\nGrounded.\n\n## Conclusion\n\nDone.\n\n## Recommendations\n\n1. Review caveats.",
            "report_sections": [
                {
                    "section_id": "sec-1",
                    "title": "Overview",
                    "status": "done",
                    "analysis_type": "descriptive",
                    "insight_markdown": "Grounded section.",
                    "claims": [],
                    "evidence_packets": [],
                    "chart_image_url": "/artifacts/thread-1/7/section_sec-1_chart.png",
                    "chart_image_format": "png",
                    "visualization": {"image_size_bytes": 10, "execution_time_ms": 1.0},
                    "limitations": [],
                    "semantic_warnings": [],
                    "section_confidence": "high",
                }
            ],
            "conversation_turn": 7,
            "thread_id": "thread-1",
            "step_count": 1,
        }
    )

    metadata = update["final_payload"]["result_metadata"]
    assert metadata["artifact_turn"] == 7
    assert metadata["report_markdown_path"] == "thread-1/7/report.md"


def test_report_finalize_localizes_answer_from_report_constraints(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    update = report_finalize_node(
        {
            "validator_verdict": "APPROVED",
            "report_plan": {"title": "Sales Report"},
            "report_draft": "# Sales Report\n\n## Executive Summary\n\nGrounded.\n\n## Conclusion\n\nDone.\n\n## Recommendations\n\n1. Review caveats.",
            "report_sections": [],
            "report_constraints": {"output_language": "en"},
            "step_count": 1,
        }
    )

    assert update["final_answer"].startswith("Here is your report")
