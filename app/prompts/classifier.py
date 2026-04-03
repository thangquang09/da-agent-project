from __future__ import annotations

from app.prompts.base import PromptDefinition

RETRIEVAL_TYPE_CLASSIFIER_PROMPT = PromptDefinition(
    name="da-agent-retrieval-type-classifier",
    prompt_type="chat",
    messages=[
        {
            "role": "system",
            "content": (
                "You are a query classifier for a data analyst agent.\n"
                "Given a user query, decide whether it asks for:\n"
                '1. \'metric_definition\' - if the user is asking for the definition, formula, or meaning of a metric/KPI (e.g., "What is DAU?", "Retention D1 là gì?", "How is revenue calculated?")\n'
                '2. \'business_context\' - if the user is asking for business rules, caveats, data quality notes, or general business context (e.g., "What caveats apply?", "Any data quality notes?", "Business rules for this metric?")\n\n'
                'Respond with ONLY a JSON object: {"retrieval_type": "metric_definition" or "business_context", "reason": "brief reason"}'
            ),
        },
        {"role": "user", "content": "{{query}}"},
    ],
)
