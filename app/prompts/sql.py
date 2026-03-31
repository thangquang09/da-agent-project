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
