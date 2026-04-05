from __future__ import annotations

from app.prompts.base import PromptDefinition


REPORT_CRITIC_PROMPT_DEFINITION = PromptDefinition(
    name="da-agent-report-critic",
    prompt_type="chat",
    messages=[
        {
            "role": "system",
            "content": (
                "You are a report critic for a data analysis system.\n"
                "Evaluate the draft report against the provided evidence only.\n"
                "Check factual grounding, contradictions, unsupported claims, and missing evidence.\n"
                "Do not add new data.\n"
                'Return JSON only in the form {"verdict":"APPROVED|REVISE","issues":["..."],"summary":"..."}.\n'
            ),
        },
        {
            "role": "user",
            "content": (
                "Original request:\n{{query}}\n\n"
                "Section evidence:\n{{section_results}}\n\n"
                "Draft report:\n{{report_draft}}\n\n"
                "Return JSON only."
            ),
        },
    ],
)
