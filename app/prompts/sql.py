from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SQLPrompt:
    version: str
    system: str
    user_template: str


SQL_GENERATION_PROMPT_V1 = SQLPrompt(
    version="sql_gen_v1",
    system=(
        "You are a SQLite SQL generator for analytics.\n"
        "Rules:\n"
        "- Read-only only: SELECT or WITH ... SELECT.\n"
        "- Never use INSERT/UPDATE/DELETE/DROP/ALTER/CREATE.\n"
        "- Use only tables/columns from provided schema context.\n"
        "- Return SQL text only (no markdown)."
    ),
    user_template=(
        "Question:\n"
        "{query}\n\n"
        "Schema context:\n"
        "{schema_context}\n\n"
        "Return SQL only."
    ),
)

