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
                "Respond with ONLY the SQL query, no explanations.\n\n"
                "LIMIT rules:\n"
                "- If retrieving raw/detail rows (no aggregation, no GROUP BY), always add LIMIT 200\n"
                "- If using aggregate functions (AVG, MAX, COUNT, SUM, STDDEV, etc.) or GROUP BY, do NOT add LIMIT\n"
                "- If the user asks for 'top N' or 'first N', use LIMIT N\n"
                "- If using window functions (RANK, ROW_NUMBER, OVER), do NOT add LIMIT"
            ),
        },
        {
            "role": "user",
            "content": (
                "{{#if session_context}}"
                "Previous conversation context:\n"
                "{{session_context}}\n\n"
                "{{/if}}"
                "{{#if xml_database_context}}"
                "Table schema + business context (XML):\n"
                "{{xml_database_context}}\n\n"
                "{{/if}}"
                "Schema: {{schema}}\n\n"
                "Question: {{query}}\n\n"
                "Generate SQL:"
            ),
        },
    ],
)
