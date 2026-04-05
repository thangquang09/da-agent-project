from __future__ import annotations

from app.prompts.base import PromptDefinition

GROUNDEDNESS_EVALUATION_PROMPT = PromptDefinition(
    name="da-agent-groundedness-evaluator",
    prompt_type="chat",
    messages=[
        {
            "role": "system",
            "content": (
                "You are an evaluation assistant for a data analyst agent.\n\n"
                "Your task is to evaluate whether the final ANSWER is grounded in and supported by the EVIDENCE provided.\n\n"
                "Evaluation criteria:\n"
                "1. Are the factual claims in the ANSWER supported by the EVIDENCE?\n"
                "2. Are the numbers/values in the ANSWER consistent with the EVIDENCE?\n"
                "3. Does the ANSWER correctly interpret the EVIDENCE?\n\n"
                "Respond with ONLY a JSON object:\n"
                "{\n"
                '  "score": <float 0.0 to 1.0, where 1.0 = fully grounded>,\n'
                '  "passed": <boolean, true if score >= 0.7>,\n'
                '  "reason": "<brief explanation of your evaluation>"\n'
                "}"
            ),
        },
        {
            "role": "user",
            "content": (
                "EVIDENCE:\n"
                "{evidence_text}\n\n"
                "ANSWER:\n"
                "{answer}\n\n"
                "EXPECTED KEYWORDS (for reference, not required to match exactly):\n"
                "{keywords_text}\n\n"
                "Evaluate groundedness:"
            ),
        },
    ],
)
