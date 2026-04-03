from __future__ import annotations

from app.prompts.base import PromptDefinition

SQL_WORKER_GENERATION_PROMPT = PromptDefinition(
    name="da-agent-sql-worker-generator",
    prompt_type="chat",
    messages=[
        {
            "role": "system",
            "content": (
                "You are a SQL expert. Generate a read-only SQL query to answer the user's question.\n"
                "Use the provided schema. Only use SELECT and WITH statements.\n"
                "Respond with ONLY the SQL query, no explanations."
            ),
        },
        {
            "role": "user",
            "content": (
                "{{#if session_context}}"
                "Previous conversation context:\n"
                "{{session_context}}\n\n"
                "{{/if}}"
                "Schema: {{schema}}\n\n"
                "Question: {{query}}\n\n"
                "Generate SQL:"
            ),
        },
    ],
)
