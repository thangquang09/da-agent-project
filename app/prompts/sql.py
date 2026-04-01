from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PromptDefinition:
    name: str
    prompt_type: Literal["chat", "text"]
    messages: list[dict[str, str]]


SQL_PROMPT_DEFINITION = PromptDefinition(
    name="da-agent-sql-generation",
    prompt_type="chat",
    messages=[
        {
            "role": "system",
            "content": (
                "You are a SQLite SQL generator for analytics.\n"
                "Rules:\n"
                "- Read-only queries only (SELECT or WITH ... SELECT).\n"
                "- Only use tables/columns from the provided schema context.\n"
                "- Prefer LIMIT clauses to keep results small (<=200 rows).\n"
                "- Always keep language neutral and precise; return SQL text only."
            ),
        },
        {
            "role": "user",
            "content": (
                "{{#if session_context}}"
                "Previous conversation context (for follow-up questions):\n"
                "{{session_context}}\n\n"
                "{{/if}}"
                "Question:\n"
                "{{query}}\n\n"
                "Schema context:\n"
                "{{schema_context}}\n\n"
                "Dataset stats (row counts, min/max dates, sample rows):\n"
                "{{dataset_context}}\n\n"
                "{{#if semantic_context}}"
                "Relevant semantic context:\n"
                "{{semantic_context}}\n\n"
                "{{/if}}"
                "Return SQL only."
            ),
        },
    ],
)

SQL_SELF_CORRECTION_PROMPT_DEFINITION = PromptDefinition(
    name="da-agent-sql-self-correction",
    prompt_type="chat",
    messages=[
        {
            "role": "system",
            "content": (
                "You are a SQLite SQL debugger and generator for analytics.\n"
                "The previous SQL query failed. Analyze the error and generate a corrected query.\n"
                "Rules:\n"
                "- Read-only queries only (SELECT or WITH ... SELECT).\n"
                "- Only use tables/columns from the provided schema context.\n"
                "- Prefer LIMIT clauses to keep results small (<=200 rows).\n"
                "- Fix the specific error mentioned in the error message.\n"
                "- If the error mentions unknown columns, check the schema carefully.\n"
                "- If the error is a syntax error, verify SQL syntax.\n"
                "- Do not include comments explaining the fix; return SQL only."
            ),
        },
        {
            "role": "user",
            "content": (
                "{{#if session_context}}"
                "Previous conversation context (for follow-up questions):\n"
                "{{session_context}}\n\n"
                "{{/if}}"
                "Question:\n"
                "{{query}}\n\n"
                "Schema context:\n"
                "{{schema_context}}\n\n"
                "Dataset stats (row counts, min/max dates, sample rows):\n"
                "{{dataset_context}}\n\n"
                "{{#if semantic_context}}"
                "Relevant semantic context:\n"
                "{{semantic_context}}\n\n"
                "{{/if}}"
                "Previous SQL attempt (FAILED):\n"
                "```sql\n"
                "{{previous_sql}}\n"
                "```\n\n"
                "Error message:\n"
                "{{error_message}}\n\n"
                "Return corrected SQL only."
            ),
        },
    ],
)
