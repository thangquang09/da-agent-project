from __future__ import annotations

from app.prompts.base import PromptDefinition


AUTO_CONTEXT_PROMPT_DEFINITION = PromptDefinition(
    name="da-agent-auto-context",
    prompt_type="chat",
    messages=[
        {
            "role": "system",
            "content": (
                "You are a data domain classifier. Given a database table schema and a few sample rows, "
                "produce a concise 1-2 sentence business context description that answers:\n"
                "1. What domain/industry this data belongs to.\n"
                "2. What the data is likely used for (analysis goal).\n\n"
                "Rules:\n"
                "- Return plain text only, no JSON.\n"
                "- Be specific: mention actual column names and value ranges when they help identify the domain.\n"
                "- Keep it under 80 words.\n"
                "- If uncertain, give your best guess with a hedge (e.g., 'likely', 'appears to be').\n"
                "- Respond in the same language as the table/column names (Vietnamese if Vietnamese, English otherwise).\n"
            ),
        },
        {
            "role": "user",
            "content": (
                "Table: {{table_name}}\n\n"
                "Columns:\n{{columns_info}}\n\n"
                "Sample rows (first 10):\n{{sample_rows}}\n\n"
                "Describe the business context of this dataset in 1-2 sentences."
            ),
        },
    ],
)
