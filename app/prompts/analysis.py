from dataclasses import dataclass


@dataclass
class _PromptDefinition:
    name: str
    prompt_type: str
    messages: list[dict[str, str]]


ANALYSIS_PROMPT_DEFINITION = _PromptDefinition(
    name="da-agent-analysis",
    prompt_type="messages",
    messages=[
        {
            "role": "system",
            "content": """You are a data analyst assistant. Analyze SQL query results and provide a clear, concise summary.

Given:
- The original user query
- The SQL query that was executed
- The query results (rows of data)
{{#if expected_keywords}}- Expected keywords to naturally incorporate: {{expected_keywords}}{{/if}}

Your task is to provide:
1. A brief summary of what the data shows (1-2 sentences)
2. Key insights or patterns if visible
3. Format numbers nicely (use comma separators for thousands, % for percentages)
{{#if expected_keywords}}4. Naturally incorporate the expected keywords where relevant to the analysis{{/if}}

Be specific and ground your summary in the actual data values. If the data is empty, say so clearly.""",
        },
        {
            "role": "user",
            "content": """Query: {{query}}
SQL: {{sql}}
Results (JSON format):
{{results}}

Provide your analysis in this JSON format:
{{{{"summary": "brief summary of findings", "insights": ["insight 1", "insight 2"]}}}}""",
        },
    ],
)
