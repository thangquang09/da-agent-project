from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PromptDefinition:
    name: str
    prompt_type: Literal["chat", "text"]
    messages: list[dict[str, str]]


ROUTER_PROMPT_DEFINITION = PromptDefinition(
    name="da-agent-router",
    prompt_type="chat",
    messages=[
        {
            "role": "system",
            "content": (
                "You are an intent router for a Data Analyst Agent.\n"
                "Classify the query into exactly one intent:\n"
                "- sql: needs numeric values, trends, rankings, comparisons from structured data.\n"
                "- rag: needs definitions, caveats, business rules, or qualitative context.\n"
                "- mixed: needs both data and business context.\n"
                "- unknown: capability, help, or casual questions that don't require SQL/RAG.\n\n"
                "Return JSON only with shape:\n"
                "{{\"intent\":\"sql|rag|mixed|unknown\",\"reason\":\"short reason\"}}\n"
                "No markdown. No extra keys."
            ),
        },
        {
            "role": "user",
            "content": (
                "User query:\n"
                "{{query}}\n\n"
                "Respond in JSON only."
            ),
        },
    ],
)
