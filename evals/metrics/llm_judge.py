from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.llm.client import LLMClient
from app.logger import logger


@dataclass(frozen=True)
class LLMJudgeResult:
    completeness: float
    groundedness: float
    clarity: float
    overall_score: float
    reasoning: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "completeness": self.completeness,
            "groundedness": self.groundedness,
            "clarity": self.clarity,
            "overall_score": self.overall_score,
            "reasoning": self.reasoning,
        }


def _call_llm_judge(prompt: str) -> dict[str, Any] | None:
    try:
        client = LLMClient.from_env()
        response = client.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert evaluator assessing AI-generated answers. Respond ONLY with valid JSON in the exact format specified.",
                },
                {"role": "user", "content": prompt},
            ],
            model="gh/gpt-4o",
            temperature=0.0,
            max_tokens=500,
            stream=False,
        )
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        if content:
            return json.loads(content)
        return None
    except Exception as e:
        logger.warning("LLM judge call failed: {error}", error=str(e))
        return None


class LLMAnswerJudge:
    def evaluate(
        self,
        question: str,
        answer: str,
        evidence: list[str] | None = None,
    ) -> LLMJudgeResult:
        if not answer or not answer.strip():
            return LLMJudgeResult(
                completeness=0.0,
                groundedness=0.0,
                clarity=0.0,
                overall_score=0.0,
                reasoning="No answer provided",
            )
        if evidence is None:
            evidence = []
        evidence_for_prompt = evidence[:5] if len(evidence) > 5 else evidence
        evidence_text = (
            "\n".join(f"- {e}" for e in evidence_for_prompt)
            if evidence_for_prompt
            else "No evidence available"
        )
        prompt = f"""Question: {question}

Evidence from database:
{evidence_text}

Generated Answer: {answer}

Evaluate this answer on:
1. Completeness: Does it fully answer the question? (0-1)
2. Groundedness: Is it supported by evidence? (0-1)
3. Clarity: Is it clear and well-explained? (0-1)

Respond in JSON:
{{
    "completeness": float,
    "groundedness": float,
    "clarity": float,
    "overall_score": float,
    "reasoning": str
}}"""

        result = _call_llm_judge(prompt)
        if not result:
            return LLMJudgeResult(
                completeness=0.5,
                groundedness=0.5,
                clarity=0.5,
                overall_score=0.5,
                reasoning="LLM judge unavailable, using fallback",
            )
        try:
            return LLMJudgeResult(
                completeness=float(result.get("completeness", 0.5)),
                groundedness=float(result.get("groundedness", 0.5)),
                clarity=float(result.get("clarity", 0.5)),
                overall_score=float(result.get("overall_score", 0.5)),
                reasoning=str(result.get("reasoning", "")),
            )
        except (ValueError, TypeError):
            return LLMJudgeResult(
                completeness=0.5,
                groundedness=0.5,
                clarity=0.5,
                overall_score=0.5,
                reasoning="Failed to parse LLM judge response",
            )
