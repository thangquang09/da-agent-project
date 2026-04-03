from __future__ import annotations

from app.prompts.base import PromptDefinition

CONTINUITY_DETECTION_PROMPT_DEFINITION = PromptDefinition(
    name="da-agent-continuity-detector",
    prompt_type="chat",
    messages=[
        {
            "role": "user",
            "content": (
                "You are analyzing if a user's follow-up query continues a previous action.\n\n"
                "## Previous Action\n"
                "Type: {action_type}\n"
                "Intent: {intent}\n"
                "SQL Generated: {sql}\n"
                "Result Summary: {result_summary}\n"
                "Parameters: {parameters}\n\n"
                "## Current Query\n"
                "{current_query}\n\n"
                "## Task\n"
                "Determine if the current query is:\n"
                "1. A continuation of the previous action (implicit follow-up)\n"
                "2. A completely new query\n\n"
                "## Classification Rules\n"
                '- "continuation" if: User is modifying parameters, asking for visualizations of previous results, refining previous query\n'
                '- "new_query" if: User is asking about a different topic, metric, or table\n\n'
                "## Response Format (JSON)\n"
                "{{\n"
                '  "is_continuation": true/false,\n'
                '  "continuation_type": "parameter_change" | "visualization_request" | "refinement" | "new_query",\n'
                '  "inherited_action": {{\n'
                '    "action_type": "sql_query" | "rag_query" | "mixed_query",\n'
                '    "base_sql": "the SQL to re-run or modify",\n'
                '    "base_parameters": {{}},\n'
                '    "needs_rerun": true/false\n'
                "  }},\n"
                '  "parameter_changes": {{\n'
                '    "addiction_level": "Medium",\n'
                '    "visualization_type": "bar_chart"\n'
                "  }},\n"
                '  "reasoning": "Brief explanation"\n'
                "}}\n\n"
                "## Examples\n\n"
                "Example 1:\n"
                'Previous: "Vẽ biểu đồ cho High addiction level"\n'
                'Current: "Đổi sang Medium"\n'
                'Response: {{"is_continuation": true, "continuation_type": "parameter_change", "inherited_action": {{"action_type": "sql_query", "base_sql": "SELECT...", "needs_rerun": true}}, "parameter_changes": {{"addiction_level": "Medium"}}}}\n\n'
                "Example 2:\n"
                'Previous: "Calculate average study_hours by addiction_level"\n'
                'Current: "Vẽ biểu đồ cho kết quả vừa rồi"\n'
                'Response: {{"is_continuation": true, "continuation_type": "visualization_request", "inherited_action": {{"action_type": "sql_query", "base_sql": "SELECT...", "needs_rerun": true, "add_visualization": true}}}}\n\n'
                "Example 3:\n"
                'Previous: "Calculate DAU for last 7 days"\n'
                'Current: "What is retention D1?"\n'
                'Response: {{"is_continuation": false, "continuation_type": "new_query"}}\n\n'
                "Now analyze the given query and respond with JSON only."
            ),
        },
    ],
)
