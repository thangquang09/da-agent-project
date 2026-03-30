from evals.groundedness import evaluate_groundedness


def test_groundedness_passes_when_keywords_and_numbers_supported():
    result = evaluate_groundedness(
        answer="Latest DAU=12805 vs previous=12840",
        evidence=["intent=sql", "rows=7", "latest=12805", "previous=12840"],
        expected_keywords=["DAU", "Latest"],
    )
    assert result.passed is True
    assert result.unsupported_claims == []


def test_groundedness_flags_unsupported_numeric_claim():
    result = evaluate_groundedness(
        answer="Revenue is 99999 and growing fast",
        evidence=["intent=sql", "rows=7"],
        expected_keywords=["Revenue"],
    )
    assert result.passed is False
    assert "numeric_claim:99999" in result.unsupported_claims
