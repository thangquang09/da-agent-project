from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.llm import LLMClient
from app.logger import logger
from app.prompts import prompt_manager


@dataclass
class GroundednessResult:
    score: float
    passed: bool
    supported_keywords: list[str]
    missing_keywords: list[str]
    unsupported_claims: list[str]
    fail_reasons: list[str]
    marked_answer: str
    evaluation_method: str = "keyword"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _extract_number_claims(text: str) -> list[str]:
    return re.findall(r"\b\d+(?:[.,]\d+)?%?\b", text)


def _keyword_coverage(
    answer: str, expected_keywords: list[str]
) -> tuple[list[str], list[str]]:
    if not expected_keywords:
        return [], []
    normalized_answer = _normalize(answer)
    supported: list[str] = []
    missing: list[str] = []
    for keyword in expected_keywords:
        normalized_kw = _normalize(keyword)
        if normalized_kw and normalized_kw in normalized_answer:
            supported.append(keyword)
        else:
            missing.append(keyword)
    return supported, missing


def _llm_evaluate_groundedness(
    answer: str, evidence: list[str], expected_keywords: list[str]
) -> GroundednessResult:
    """
    Use LLM to evaluate if the answer is grounded in the evidence.
    This is a semantic evaluation that doesn't rely on exact keyword matching.
    """
    try:
        client = LLMClient.from_env()
        messages = prompt_manager.groundedness_evaluation_messages(
            evidence=evidence,
            answer=answer,
            expected_keywords=expected_keywords,
        )
        response = client.chat_completion(
            messages=messages,
            model="gh/gpt-4o-mini",
            temperature=0.0,
            stream=False,
        )
        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if content:
            parsed: dict[str, Any] = {}
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", content, flags=re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))

            if parsed:
                score = float(parsed.get("score", 0.0))
                passed = bool(parsed.get("passed", False))
                reason = str(parsed.get("reason", ""))

                return GroundednessResult(
                    score=round(score, 4),
                    passed=passed,
                    supported_keywords=expected_keywords,
                    missing_keywords=[],
                    unsupported_claims=[],
                    fail_reasons=[f"llm_evaluation={reason}"] if reason else [],
                    marked_answer=answer,
                    evaluation_method="llm",
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM groundedness evaluation failed: {error}", error=str(exc))

    return GroundednessResult(
        score=0.0,
        passed=False,
        supported_keywords=[],
        missing_keywords=[],
        unsupported_claims=[],
        fail_reasons=["llm_evaluation_error"],
        marked_answer=answer,
        evaluation_method="llm",
    )


def evaluate_groundedness(
    answer: str,
    evidence: list[str],
    expected_keywords: list[str],
    use_llm_fallback: bool = True,
) -> GroundednessResult:
    """
    Evaluate groundedness using both keyword matching and LLM-based semantic evaluation.

    If use_llm_fallback=True and keyword-based score is low (<0.5), fall back to LLM evaluation.
    This combines the speed of keyword matching with the accuracy of LLM semantic evaluation.
    """
    keyword_result = _keyword_groundedness(answer, evidence, expected_keywords)

    if use_llm_fallback and keyword_result.score < 0.5 and expected_keywords:
        llm_result = _llm_evaluate_groundedness(answer, evidence, expected_keywords)
        if llm_result.score > keyword_result.score:
            return llm_result

    return keyword_result


def _keyword_groundedness(
    answer: str, evidence: list[str], expected_keywords: list[str]
) -> GroundednessResult:
    """Original keyword-based groundedness evaluation."""
    supported_keywords, missing_keywords = _keyword_coverage(answer, expected_keywords)
    answer_numbers = set(_extract_number_claims(answer))
    evidence_blob = " ".join(str(item) for item in evidence)
    evidence_numbers = set(_extract_number_claims(evidence_blob))

    unsupported_claims: list[str] = []
    for number in sorted(answer_numbers):
        if number not in evidence_numbers:
            unsupported_claims.append(f"numeric_claim:{number}")

    fail_reasons: list[str] = []
    if missing_keywords:
        fail_reasons.append(
            f"missing_expected_keywords:{','.join(missing_keywords[:5])}"
        )
    if unsupported_claims:
        fail_reasons.append(f"unsupported_claims:{','.join(unsupported_claims[:5])}")

    keyword_score = 1.0
    if expected_keywords:
        keyword_score = len(supported_keywords) / len(expected_keywords)
    claim_penalty = min(0.5, 0.1 * len(unsupported_claims))
    score = round(max(0.0, keyword_score - claim_penalty), 4)
    passed = score >= 0.7 and not unsupported_claims

    marked_answer = answer
    if unsupported_claims:
        marked_answer = (
            answer + "\n\n[UNSUPPORTED_CLAIMS] " + ", ".join(unsupported_claims)
        )

    return GroundednessResult(
        score=score,
        passed=passed,
        supported_keywords=supported_keywords,
        missing_keywords=missing_keywords,
        unsupported_claims=unsupported_claims,
        fail_reasons=fail_reasons,
        marked_answer=marked_answer,
        evaluation_method="keyword",
    )
