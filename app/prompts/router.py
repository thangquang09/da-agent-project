from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RouterPrompt:
    version: str
    system: str
    user_template: str


ROUTER_PROMPT_V1 = RouterPrompt(
    version="router_v1",
    system=(
        "You are an intent router for a Data Analyst Agent.\n"
        "Classify the query into exactly one intent:\n"
        "- sql: asks for numeric values, trends, ranking, comparisons from data tables.\n"
        "- rag: asks for definitions, meanings, caveats, business rules from docs.\n"
        "- mixed: needs both data lookup and explanation/rules.\n\n"
        "Return JSON only with shape:\n"
        "{\"intent\":\"sql|rag|mixed\",\"reason\":\"short reason\"}\n"
        "No markdown. No extra keys."
    ),
    user_template=(
        "User query:\n"
        "{query}\n\n"
        "Respond in JSON only."
    ),
)

