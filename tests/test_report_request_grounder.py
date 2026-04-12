from __future__ import annotations

import json

from app.graph.report_subgraph import report_request_grounder_node


def test_report_request_grounder_extracts_objective_questions_and_followup(
    monkeypatch,
):
    class _FakeGrounderClient:
        def chat_completion(self, **kwargs):  # noqa: ANN003
            payload = {
                "objective": "Tạo report hoàn chỉnh về dữ liệu Titanic",
                "questions": [
                    "Tỷ lệ sống sót theo giới tính là bao nhiêu?",
                    "Nhóm tuổi nào có tỷ lệ sống sót thấp nhất?",
                ],
                "hypotheses": [
                    {
                        "text": "Giới tính có liên hệ rõ với khả năng sống sót",
                        "priority": "should",
                        "test_type": "compare",
                    }
                ],
                "constraints": {
                    "requested_visualizations": True,
                    "answer_style": "analyst",
                },
                "followup_notes": "User is refining a previous Titanic discussion.",
            }
            return {
                "choices": [
                    {"message": {"content": json.dumps(payload, ensure_ascii=False)}}
                ]
            }

    monkeypatch.setattr(
        "app.graph.report_subgraph.LLMClient.from_env",
        lambda: _FakeGrounderClient(),
    )

    update = report_request_grounder_node(
        {
            "report_request": (
                "Tạo report hoàn chỉnh về dữ liệu Titanic, trả lời câu hỏi "
                "tỷ lệ sống sót theo giới tính là bao nhiêu và nhóm tuổi nào có tỷ lệ sống sót thấp nhất"
            ),
            "session_context": "Trước đó chúng ta đã xem qua các cột tuổi, giới tính và trạng thái sống sót.",
            "last_action": {
                "tool": "ask_sql_analyst",
                "query": "Tóm tắt schema Titanic",
            },
            "task_profile": {"followup_mode": "followup"},
            "conversation_turn": 7,
        }
    )

    assert update["report_original_request"].startswith(
        "Tạo report hoàn chỉnh về dữ liệu Titanic"
    )
    assert update["report_user_objective"] == "Tạo report hoàn chỉnh về dữ liệu Titanic"
    assert [q["text"] for q in update["report_user_questions"]] == [
        "Tỷ lệ sống sót theo giới tính là bao nhiêu?",
        "Nhóm tuổi nào có tỷ lệ sống sót thấp nhất?",
    ]
    assert [q["priority"] for q in update["report_user_questions"]] == [
        "must",
        "must",
    ]
    assert update["report_user_questions"][0]["question_id"] == "q1"
    assert update["report_user_hypotheses"][0]["hypothesis_id"] == "h1"
    assert update["report_constraints"]["requested_visualizations"] is True
    assert update["report_followup_context"] == {
        "followup_mode": "followup",
        "session_context_summary": "User is refining a previous Titanic discussion.",
        "last_action_summary": "tool=ask_sql_analyst; query=Tóm tắt schema Titanic",
        "conversation_turn": 7,
    }
    assert (
        update["report_planning_brief"]["original_request"]
        == update["report_original_request"]
    )
    assert update["report_planning_brief"]["user_questions"][1]["question_id"] == "q2"
