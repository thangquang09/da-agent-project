# EVAL Fix Task - Groundedness Score Improvement

**Date**: 2026-03-31
**Priority**: HIGH
**Related PR/Change**: Generalization Sprint (removed hardcoded logic, fully LLM-driven)

---

## Problem Statement

The eval currently fails the `groundedness_pass_rate` gate (threshold: 0.70, actual: ~0.17).

### Current Behavior

The `groundedness` evaluator (`evals/groundedness.py`) checks if the final answer contains `expected_keywords` from the eval case:

```python
# Simplified logic
for keyword in expected_keywords:
    if keyword.lower() in answer.lower():
        found += 1
score = found / len(expected_keywords)
passed = score >= 0.5
```

### Issue

LLM-generated answers (via `synthesize_answer` node) don't explicitly include the `expected_keywords` from eval cases. The eval case `expected_keywords` are for evaluation purposes only, not injected into the prompt.

Example:
- Eval case: `expected_keywords: ["dau", "trend"]`
- LLM generates: "The query results show DAU fluctuated between X and Y over the past week..."
- The word "trend" is NOT in the answer, but the answer IS correct
- Groundedness fails incorrectly

---

## Root Cause Analysis

1. **Eval design issue**: `expected_keywords` were never passed to the agent during generation
2. **Groundedness evaluator naive**: Uses simple keyword matching instead of semantic similarity
3. **No feedback loop**: Agent doesn't know what keywords eval expects

---

## Solution Options

### Option A: Pass `expected_keywords` to Synthesis Prompt (Recommended)
- Add `expected_keywords` to synthesis prompt
- LLM will naturally incorporate them into the answer
- Pro: Simple change, improves answer quality
- Con: Agent becomes "eval-aware" which may cause overfitting

### Option B: Fix Groundedness Evaluator
- Use LLM-based groundedness check instead of keyword matching
- Pro: More accurate evaluation, not keyword-dependent
- Con: More complex, slower evaluation

### Option C: Accept Lower Groundedness Threshold
- Lower threshold to match actual LLM performance
- Pro: Quick fix
- Con: Loses evaluation signal

---

## Recommended Approach

**Combine Option A + B**:

1. **Short-term**: Pass `expected_keywords` to synthesis prompt so answers naturally include them
2. **Long-term**: Replace keyword-based groundedness with LLM-based semantic check

---

## Files to Modify

| File | Change |
|------|--------|
| `evals/groundedness.py` | Add LLM-based groundedness check as alternative |
| `app/prompts/analysis.py` | Add `expected_keywords` to synthesis prompt template |
| `app/prompts/manager.py` | Pass `expected_keywords` in `analysis_messages()` |
| `evals/runner.py` | Pass `expected_keywords` through `run_case()` |
| `app/graph/state.py` | Optional: add `expected_keywords` to state |

---

## Step-by-Step Implementation

### Step 1: Understand current groundedness evaluator

Read `evals/groundedness.py`:
- `evaluate_groundedness()` function signature
- How `expected_keywords` are used
- What `fail_reasons` are tracked

### Step 2: Add LLM-based groundedness check

Create new function `evaluate_groundedness_llm()` that:
- Takes `answer`, `evidence`, `expected_keywords`
- Uses LLM to evaluate if answer is supported by evidence
- Returns structured JSON with `score`, `passed`, `reasons`

### Step 3: Update synthesis prompt

In `app/prompts/analysis.py`:
- Add `{{expected_keywords}}` to template
- Instruct LLM to naturally incorporate these keywords

### Step 4: Wire through the pipeline

1. `evals/runner.run_case()` already has `case.expected_keywords`
2. Pass to `run_query()` or store in state
3. Pass to synthesis node via `analysis_messages()`
4. Use both keyword-based and LLM-based groundedness

### Step 5: Verify with eval run

```bash
uv run python -m evals.runner --suite domain --limit 12
```

Target: `groundedness_pass_rate >= 0.70`

---

## Verification Checklist

- [ ] Unit tests pass: `uv run python -m pytest tests/test_groundedness.py -v`
- [ ] Eval run completes without errors
- [ ] `groundedness_pass_rate` improves from ~0.17 to >= 0.70
- [ ] Other metrics remain at 1.0 (routing, tool_path, sql_validity)

---

## Notes for Agent

1. **This is NOT about the agent being "dumb"** - the agent generates correct answers
2. **This IS about the eval being too strict** - it requires exact keyword matches
3. **The fix should improve eval accuracy**, not change agent behavior
4. **Do NOT break the generalization work** - keep LLM-driven routing and SQL generation
5. **Maintain bilingual support** - answers should work for both VI and EN queries

---

## References

- Current eval results: `evals/reports/latest_summary.md`
- Groundedness code: `evals/groundedness.py`
- Synthesis prompts: `app/prompts/analysis.py`
- Case structure: `evals/case_contracts.py`
