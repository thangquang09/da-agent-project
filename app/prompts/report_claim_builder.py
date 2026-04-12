from __future__ import annotations

from app.prompts.base import PromptDefinition


REPORT_CLAIM_BUILDER_PROMPT_DEFINITION = PromptDefinition(
    name="da-agent-report-claim-builder",
    prompt_type="chat",
    messages=[
        {
            "role": "system",
            "content": (
                "You are a claim builder for a grounded analytics report system.\n"
                "Convert structured evidence into claim packets.\n"
                "Rules:\n"
                "- Use only the provided evidence packets and section plan.\n"
                "- Every claim must include exact evidence_refs that point to evidence packet paths.\n"
                "- Label comparisons and trends accurately.\n"
                "- If the section is only descriptive, do not use causal wording.\n"
                "- Hypothesis-style language must stay explicitly labeled as a hypothesis and include caveats.\n"
                "- Do not produce recommendations in this stage.\n"
                'Return JSON only in the form {"claims":[...],"limitations":[...]}.'
            ),
        },
        {
            "role": "user",
            "content": (
                "Original request:\n{{query}}\n\n"
                "Section plan:\n{{section_plan}}\n\n"
                "Evidence packets:\n{{evidence_packets}}\n\n"
                "Return JSON only."
            ),
        },
    ],
)
