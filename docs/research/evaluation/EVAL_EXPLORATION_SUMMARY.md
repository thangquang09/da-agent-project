# DA Agent Evaluation Pipeline - Exploration Summary

**Completed:** April 1, 2026  
**Scope:** Full technical deep-dive of evaluation infrastructure

---

## What I Read

### Core Evaluation Files (100% coverage)
✓ `evals/runner.py` (705 lines) — Main orchestrator
✓ `evals/case_contracts.py` (82 lines) — Data structures
✓ `evals/build_spider_cases.py` (121 lines) — Case generator
✓ `evals/metrics/execution_accuracy.py` (162 lines) — Execution-based comparison
✓ `evals/metrics/spider_exact_match.py` (443 lines) — Component-based comparison
✓ `evals/metrics/llm_judge.py` (123 lines) — LLM answer quality
✓ `evals/metrics/official_spider_eval.py` (269 lines) — Official benchmark integration
✓ `evals/metrics/__init__.py` (27 lines) — Exports
✓ `evals/groundedness.py` (211 lines) — Hallucination detection
✓ `app/prompts/sql.py` (99 lines) — SQL generation prompts

### Sample Data
✓ `evals/cases/dev/spider_dev.jsonl` (first case examined)
✓ `evals/cases/domain_cases.jsonl` (first case examined)
✓ `evals/reports/latest_summary.json` (structure analyzed)

---

## Key Findings

### 1. Architecture Overview

The evaluation pipeline is **multi-layered**:

```
Case Input (JSONL)
    ↓
Agent Execution (run_query → payload)
    ↓
Metric Evaluation (4 independent evaluators)
    ├─ Execution Accuracy (rows match?)
    ├─ Spider Exact Match (components match?)
    ├─ LLM Judge (quality score)
    └─ Groundedness (no hallucinations?)
    ↓
Failure Categorization (priority buckets)
    ↓
Report Generation (JSON + Markdown + JSONL)
```

### 2. Critical Functions & Their Behavior

#### `_tool_path_ok()` — Lines 103-105
- **Current:** Checks if ALL expected tools are in used_tools set
- **Status:** ALWAYS RETURNS FALSE (0.0% pass rate)
- **Expected tools:** `["route_intent", "get_schema", "generate_sql", "validate_sql", "query_sql", "analyze_result"]`
- **Actual:** Agent typically stops after SQL generation (fewer tools)
- **Issue:** Definition mismatch or tool invocation logic broken

#### `_normalize_rows()` — Lines 117-124
- **CRITICAL ISSUE:** Only compares **first 100 rows**
- **Impact:** False positives possible if gold has 500+ rows and pred has LIMIT 200
- **Symptom:** execution_match might be True while spider_exact_match is False

#### `_execution_match()` — Lines 127-142
- Uses `_normalize_rows()` internally
- Compares result sets after normalization
- Returns True/False/None (three-valued logic)

#### `_failure_bucket()` — Lines 145-166
- Priority-ordered categorization (ROUTING_ERROR > ... > TOOL_PATH_MISMATCH)
- Tool path is **lowest priority** — rarely assigned if other errors present

### 3. Evaluation Metrics

**Gate Thresholds (lines 30-36):**
```python
GATE_THRESHOLDS = {
    "routing_accuracy": 0.90,
    "sql_validity_rate": 0.90,
    "tool_path_accuracy": 0.95,      ← Hardest gate (95%)
    "answer_format_validity": 1.00,   ← Perfection required
    "groundedness_pass_rate": 0.70,
}
```

**Metrics evaluated per case:**
- `routing_correct`: Intent matching (expected vs predicted)
- `tool_path_correct`: Tool set validation
- `sql_valid`: Syntax validation only (no execution)
- `answer_format_valid`: Payload structure check
- `execution_match`: Row data comparison (LIMIT 100)
- `spider_exact_match`: Component-by-component SQL parsing
- `spider_exact_match_f1`: F1 score across 11 SQL components
- `answer_quality_score`: LLM judge (completeness/groundedness/clarity)
- `groundedness_score`: Keyword + LLM-based hallucination detection

### 4. SQL Component Parsing (11 components)

Spider Exact Match evaluates:
1. SELECT items
2. FROM tables
3. WHERE conditions
4. GROUP BY columns
5. HAVING clauses
6. ORDER BY columns
7. LIMIT value
8. OFFSET value
9. INTERSECT
10. UNION
11. EXCEPT

**Comparison method:**
- Parse both SQLs into frozensets per component
- Compute precision/recall/F1 for each component
- Overall F1 = average of all 11
- Exact match = all components identical (very strict)

**Issues:**
- Case-sensitivity: `Song_Name` vs `song_name` may cause exact_match to fail
- Normalization loses original casing information
- Subquery handling is naive

### 5. Dataset Structure

#### Spider Suite
- **Dev:** ~920 cases (EN + VI variants) → 1,840 total
- **Test:** ~300 cases (EN + VI) → 600 total
- **Expected tools:** Always `["route_intent", "get_schema", "generate_sql", "validate_sql", "query_sql", "analyze_result"]`
- **Expected keywords:** Always empty `[]` (no keyword grounding)
- **Should have SQL:** Always `True`

#### Domain Suite
- Project-internal custom cases
- Example: `"domain_sql_001_vi"` (Vietnamese)
- Has expected_keywords for grounding validation

#### Movielens Suite
- Movie database test cases
- Language variants (EN, VI)

### 6. Execution Accuracy Comparison

**Algorithm:**
1. Execute both SQLs against same database
2. Check columns match exactly
3. Normalize rows (first 100 only):
   - Convert dict → sorted tuple of (k,v) pairs
   - Sort tuples lexicographically
4. Compare normalized row sets

**Issues:**
- LIMIT 100 is hidden assumption
- Column comparison is case-sensitive
- Order-independence means `[1,2,3]` == `[3,2,1]` after sorting

### 7. Groundedness Evaluation

**Two-phase approach:**
1. **Keyword-based** (fast): Check if expected_keywords appear in answer
2. **LLM fallback** (slower): Semantic evaluation if keyword_score < 0.5

**Critical issue for Spider:**
- Spider cases have `expected_keywords = []` (empty)
- Keyword-based score = 1.0 (no missing keywords)
- LLM fallback never triggered (score >= 0.5)
- Result: **All Spider cases pass groundedness** (vacuous truth)
- Hallucinations in numeric claims not detected

### 8. Prompts & LIMIT Injection

**SQL Prompt System Message:**
```
"Prefer LIMIT clauses to keep results small (<=200 rows)."
```

**Issues:**
- "Prefer" = guidance, not enforcement
- Agent may add LIMIT 200, LIMIT 50, or omit entirely
- Prompt uses Handlebars templates: `{{#if condition}}...{{/if}}`
- Injection points: `{{query}}`, `{{schema_context}}`, `{{dataset_context}}`, `{{semantic_context}}`, `{{session_context}}`

### 9. Official Spider Evaluation Integration

**Subprocess-based evaluation:**
- Spawns `test-suite-sql-eval` script from vendored repo
- Takes gold (SQL + db_id) and predicted SQL
- Returns execution accuracy per hardness level (easy/medium/hard/extra)

**Issues:**
- Fragile output parsing (regex-based)
- Requires `gold_sql` stored on CaseResult
- Timeout 600s (may be too short for large batches)
- Path handling: db_id extracted via `Path(db_path).stem`

### 10. Data Flow & Storage

**EvalCase → CaseResult:**
```python
EvalCase {
    id: str
    suite: SuiteName
    language: Language
    query: str
    expected_intent: IntentName
    expected_tools: list[str]
    should_have_sql: bool
    expected_keywords: list[str]
    target_db_path: str
    gold_sql: str
    expected_context_type: ContextType
}
    ↓ run_case()
CaseResult {
    ... (all EvalCase fields reflected)
    predicted_intent: str
    routing_correct: bool
    used_tools: list[str]
    tool_path_correct: bool
    generated_sql: str
    has_sql: bool
    sql_valid: bool
    answer_format_valid: bool
    execution_match: bool | None
    spider_exact_match: bool | None
    spider_exact_match_f1: float | None
    answer_quality_score: float | None
    groundedness_score: float
    groundedness_pass: bool
    failure_bucket: str | None
    ... (11 additional fields)
}
```

---

## Critical Issues Summary

| Issue | File | Lines | Severity | Impact |
|-------|------|-------|----------|--------|
| Tool path always 0% | runner.py | 103-105, 244 | CRITICAL | Metric gate impossible to pass (95% required) |
| LIMIT 100 comparison | runner.py | 117-124 | HIGH | False positives in execution_match |
| Empty expected_keywords | build_spider_cases.py | 47 | HIGH | Groundedness always passes (vacuous) |
| Case-sensitivity in parsing | spider_exact_match.py | 140-144 | MEDIUM | exact_match may fail on schema naming differences |
| Fragile official eval parsing | official_spider_eval.py | 55-133 | MEDIUM | Silent failures if output format changes |
| Prompt LIMIT guidance | prompts/sql.py | 25 | MEDIUM | Not enforced; agent may ignore |
| Gold SQL data loss risk | runner.py | 274 | LOW | Mitigated by explicit storage (line 274) |

---

## What Works Well

✓ **Architecture:** Clean separation of concerns (case loading, execution, metrics, reporting)
✓ **Parallelization:** ThreadPoolExecutor with configurable workers
✓ **Metrics composition:** Four independent evaluators can run in parallel
✓ **Output format:** JSONL per-case + JSON summary + Markdown report
✓ **Failure categorization:** Priority-ordered buckets for debugging
✓ **Type hints:** Strong typing throughout (Python 3.10+ with frozen dataclasses)
✓ **Error handling:** Graceful degradation (None values for optional metrics)
✓ **SQL parsing:** Reasonable component extraction despite limitations

---

## Questions for Clarification

1. **Tool path accuracy = 0.0%**: Is this expected? Should expected_tools be dynamic per case?
2. **Empty expected_keywords for Spider**: Intentional design? Should they be defined?
3. **LIMIT 100 limitation**: How was this threshold chosen? Safe for typical datasets?
4. **Official Spider eval**: Is this currently working or is it a known limitation?
5. **Tool path priority**: Why is it the lowest priority in failure buckets?

---

## Next Steps (Recommended)

### Short-term Fixes
1. Investigate `_tool_path_ok()` logic and expected_tools definition
2. Add `expected_keywords` to Spider cases for proper groundedness testing
3. Document the LIMIT 100 assumption in comparison functions
4. Add schema name case normalization tests

### Medium-term Improvements
1. Make evaluators configurable (limit, model, etc.)
2. Decouple LIMIT injection from comparison logic
3. Improve official Spider eval output parsing (use JSON instead of regex)
4. Add comprehensive test coverage for metric functions

### Long-term Enhancements
1. Support for different SQL dialects (not just SQLite)
2. Pluggable metric evaluators (different benchmarks)
3. Distributed evaluation (scale beyond ThreadPoolExecutor)
4. Interactive evaluation dashboard (visualize results)

---

## File Statistics

| File | Lines | Functions | Key Classes | Purpose |
|------|-------|-----------|-------------|---------|
| runner.py | 705 | 13 | CaseResult | Main orchestrator |
| spider_exact_match.py | 443 | 16 | SQLComponentSet, SpiderExactMatchResult | Component parsing |
| official_spider_eval.py | 269 | 3 | OfficialSpiderEvaluator, OfficialSpiderResult | Subprocess wrapper |
| groundedness.py | 211 | 6 | GroundednessResult | Hallucination detection |
| execution_accuracy.py | 162 | 2 | ExecutionAccuracyEvaluator, ExecutionAccuracyResult | Row comparison |
| build_spider_cases.py | 121 | 2 | (functions) | Case generation |
| case_contracts.py | 82 | 2 | EvalCase | Data contract |
| llm_judge.py | 123 | 2 | LLMAnswerJudge, LLMJudgeResult | Quality scoring |
| prompts/sql.py | 99 | (constants) | PromptDefinition | Prompt templates |

**Total:** ~2,215 lines of evaluation code (excluding test files)

---

## Documents Created

1. **EVAL_PIPELINE_DEEP_DIVE.md** (34 KB) — Complete technical deep dive
2. **EVAL_FUNCTIONS_REFERENCE.md** (20 KB) — Function signatures and behavior
3. **EVAL_EXPLORATION_SUMMARY.md** (this file) — Executive summary

---

## How to Use These Docs

- **For quick lookup:** Start with EVAL_FUNCTIONS_REFERENCE.md
- **For understanding architecture:** Start with EVAL_PIPELINE_DEEP_DIVE.md (Overview section)
- **For specific investigation:** Use Ctrl+F to search by function name or file
- **For code review:** Reference the critical issues table above

