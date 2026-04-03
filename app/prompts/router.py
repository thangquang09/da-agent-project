from __future__ import annotations

from app.prompts.base import PromptDefinition

ROUTER_PROMPT_DEFINITION = PromptDefinition(
    name="da-agent-router",
    prompt_type="chat",
    messages=[
        {
            "role": "system",
            "content": (
                "You are an intent router for a Data Analyst Agent.\n"
                "Classify the query into exactly one intent:\n"
                "- sql: needs numeric values, trends, rankings, comparisons from structured data, OR requests for data visualization (charts, graphs, plots) with or without explicit data values.\n"
                "- rag: needs definitions, caveats, business rules, or qualitative context.\n"
                "- mixed: needs both data and business context.\n"
                "- unknown: capability questions, help requests, or casual conversation that doesn't require data or definitions.\n\n"
                "IMPORTANT: If the user asks to draw/create/plot a chart, graph, or visualization (even with raw data values provided), classify as 'sql'.\n\n"
                "Return JSON only with shape:\n"
                '{{"intent":"sql|rag|mixed|unknown","execution_mode":"direct|planned","reason":"short reason"}}\n'
                "No markdown. No extra keys.\n\n"
                "execution_mode rules:\n"
                '- "direct": single table, simple aggregation/filter, no cross-table joins, no complex multi-step comparisons\n'
                '- "planned": multi-table joins, multi-step queries, complex comparisons across dimensions, needs decomposition'
            ),
        },
        {
            "role": "user",
            "content": (
                "{{#if session_context}}Previous conversation:\n{{session_context}}\n\n{{/if}}User query:\n{{query}}\n\nRespond in JSON only."
            ),
        },
    ],
)
