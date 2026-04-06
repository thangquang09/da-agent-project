from __future__ import annotations

from app.prompts.base import PromptDefinition


REPORT_WRITER_PROMPT_DEFINITION = PromptDefinition(
    name="da-agent-report-writer",
    prompt_type="chat",
    messages=[
        {
            "role": "system",
            "content": (
                "You are a professional data analyst report assembler.\n"
                "Assemble a Markdown report using only the provided grounded section insights.\n"
                "Rules:\n"
                "- Do not hallucinate numbers, tables, columns, comparisons, or conclusions.\n"
                "- Treat each section insight_markdown as canonical source text.\n"
                "- Preserve the meaning and numeric claims of each section insight_markdown.\n"
                "- Do not compute new metrics from citations, charts, or raw data.\n"
                "- Do not introduce extra sections beyond the report plan.\n"
                "- Do not repeat the same section, conclusion, or insight twice.\n"
                "- Do not add a subheading that simply repeats the section title.\n"
                "- If a section failed or lacks data, state that clearly and do not fill gaps.\n"
                "- Keep the report grounded, concise, and business-readable.\n"
                "- Do not wrap the report in ```markdown fences.\n"
                "- Return Markdown only.\n"
            ),
        },
        {
            "role": "user",
            "content": (
                "Original request:\n{{query}}\n\n"
                "Report plan:\n{{report_plan}}\n\n"
                "Section results:\n{{section_results}}\n\n"
                "{{#if critic_feedback}}Critic feedback to address:\n{{critic_feedback}}\n\n{{/if}}"
                "Required structure:\n"
                "1. A single H1 title.\n"
                "2. One short executive summary.\n"
                "3. One H2 section per planned section, in the same order.\n"
                "4. One short conclusion.\n\n"
                "Use the provided section insight_markdown almost verbatim. Only do light editing for flow.\n"
                "Return Markdown only."
            ),
        },
    ],
)
