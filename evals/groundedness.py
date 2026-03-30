from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class GroundednessResult:
    score: float
    passed: bool
    supported_keywords: list[str]
    missing_keywords: list[str]
    unsupported_claims: list[str]
    fail_reasons: list[str]
    marked_answer: str


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _extract_number_claims(text: str) -> list[str]:
    return re.findall(r"\b\d+(?:[.,]\d+)?%?\b", text)


def _keyword_coverage(answer: str, expected_keywords: list[str]) -> tuple[list[str], list[str]]:
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


def evaluate_groundedness(answer: str, evidence: list[str], expected_keywords: list[str]) -> GroundednessResult:
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
        fail_reasons.append(f"missing_expected_keywords:{','.join(missing_keywords[:5])}")
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
        marked_answer = answer + "\n\n[UNSUPPORTED_CLAIMS] " + ", ".join(unsupported_claims)

    return GroundednessResult(
        score=score,
        passed=passed,
        supported_keywords=supported_keywords,
        missing_keywords=missing_keywords,
        unsupported_claims=unsupported_claims,
        fail_reasons=fail_reasons,
        marked_answer=marked_answer,
    )
