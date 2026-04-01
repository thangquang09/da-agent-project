# DA Agent Evaluation Pipeline: Complete Technical Deep Dive

**Date:** April 1, 2026  
**Focus:** Architecture, data flow, critical algorithms, and integration points

---

## Table of Contents

1. [Overview & Architecture](#overview--architecture)
2. [Detailed File Analysis](#detailed-file-analysis)
3. [Data Structures & Contracts](#data-structures--contracts)
4. [Evaluation Metrics Pipeline](#evaluation-metrics-pipeline)
5. [SQL Parsing & Comparison](#sql-parsing--comparison)
6. [Prompts & SQL Generation](#prompts--sql-generation)
7. [Critical Integration Points](#critical-integration-points)
8. [Known Issues & Gaps](#known-issues--gaps)

---

## Overview & Architecture

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│ evals/runner.py :: main()                                           │
│ - Load cases from JSONL (build_spider_cases.py generates them)      │
│ - Filter by suite, split, language                                 │
│ - Parallel execution (ThreadPoolExecutor, configurable workers)     │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
        ┌───────────────────────────────────────────┐
        │ For each EvalCase, run_case(case):        │
        │ 1. Invoke app.main.run_query()            │
        │ 2. Extract payload (answer, sql, tools)   │
        │ 3. Run metrics evaluators                 │
        │ 4. Categorize failures                    │
        │ 5. Store CaseResult                       │
        └───────────────────────────────────────────┘
                                ↓
        ┌───────────────────────────────────────────┐
        │ Metrics Evaluation Phase:                 │
        │ - ExecutionAccuracyEvaluator              │
        │ - SpiderExactMatchEvaluator               │
        │ - LLMAnswerJudge                          │
        │ - evaluate_groundedness()                 │
        │ - OfficialSpiderEvaluator (optional)      │
        └───────────────────────────────────────────┘
                                ↓
        ┌───────────────────────────────────────────┐
        │ Generate Reports:                         │
        │ - per_case_<timestamp>.jsonl              │
        │ - summary_<timestamp>.json                │
        │ - summary_<timestamp>.md                  │
        │ - latest_summary.json / .md               │
        └───────────────────────────────────────────┘
                                ↓
        ┌───────────────────────────────────────────┐
        │ Gate Checks (optional enforcement):       │
        │ routing_accuracy >= 0.90                  │
        │ sql_validity_rate >= 0.90                 │
        │ tool_path_accuracy >= 0.95                │
        │ answer_format_validity >= 1.00            │
        │ groundedness_pass_rate >= 0.70            │
        └───────────────────────────────────────────┘
```

### Suite & Dataset Structure

**Suites:**
- `spider`: SQL generation benchmark (900+ cases), EN + VI variants, dev + test splits
- `domain`: Project-internal domain cases (SQL intent)
- `movielens`: Internal movie database cases (SQL intent)

**Each suite has cases in:**
- `evals/cases/dev/`: Development/validation split
- `evals/cases/test/`: Test split (optional)

**Example paths:**
- `evals/cases/dev/spider_dev.jsonl` → dev cases
- `evals/cases/test/spider_test.jsonl` → test cases

---

## Detailed File Analysis

### 1. `evals/runner.py`

**Purpose:** Main evaluation orchestrator

#### Key Functions

**`run_case(case: EvalCase, recursion_limit: int) -> CaseResult`** (lines 169-278)

Flow:
1. **Invoke agent:** `payload = run_query(case.query, db_path=case.target_db_path, ...)`
2. **Extract results from payload:**
   - `predicted_intent = _extract_intent(payload)` (lines 93-100)
   - `used_tools = payload.get("used_tools", [])`
   - `generated_sql = str(payload.get("generated_sql", "") or "")`
3. **Validate SQL:** `_sql_validity(generated_sql, db_path)` → calls `app.tools.validate_sql`
4. **Run metrics (if applicable):**
   - `SpiderExactMatchEvaluator.evaluate()` (if gold_sql + generated_sql)
   - `ExecutionAccuracyEvaluator.evaluate()` (if gold_sql + generated_sql)
   - `LLMAnswerJudge.evaluate()` (if answer present)
   - `evaluate_groundedness()` (with answer + evidence)
5. **Categorize failure:** `_failure_bucket(result)` → returns priority bucket
6. **Return CaseResult** with all metrics populated

**Critical Function: `_tool_path_ok(expected_tools, used_tools) -> bool`** (lines 103-105)

```python
def _tool_path_ok(expected_tools: list[str], used_tools: list[str]) -> bool:
    used = set(used_tools)
    return all(tool in used for tool in expected_tools)
```

**Logic:**
- For each expected tool, check if it's in used_tools set
- Returns True only if ALL expected tools were used
- Does NOT check order or uniqueness

**Impact:**
- Expected tools from case (lines 38-45): `["route_intent", "get_schema", "generate_sql", "validate_sql", "query_sql", "analyze_result"]`
- If agent uses only `["route_intent", "get_schema", "generate_sql"]`, check fails
- Current data shows: **tool_path_accuracy = 0.0%** (all cases fail this check)

---

**Function: `_execution_match(gold_sql, pred_sql, db_path) -> bool | None`** (lines 127-142)

Flow:
1. Execute both SQLs against database
2. Normalize rows: `_normalize_rows()` compares:
   - Columns (must match)
   - Row data (normalized: sorted tuples of (k,v) pairs, case-insensitive)
3. Returns True if identical after normalization, False otherwise, None if DB unavailable

**Normalization detail** (lines 117-124):
```python
def _normalize_rows(rows: list[dict], limit: int = 100) -> list[tuple]:
    compact = rows[:limit]  # Take first 100 rows max
    normalized: list[tuple] = []
    for row in compact:
        items = tuple(sorted((str(k), str(v)) for k, v in row.items()))
        normalized.append(items)
    normalized.sort()  # Sort normalized rows
    return normalized
```

**Key insight:** Only compares first 100 rows due to LIMIT injection (see SQL prompts issue)

---

**Function: `summarize(results: list[CaseResult]) -> dict`** (lines 296-395)

Generates summary by:
- Grouping by suite and language
- Calculating metrics per group using `_metric_ratio()`
- Computing averages and counts
- Counting failure buckets

**Output structure:**
```json
{
  "total_cases": 1034,
  "overall": {
    "count": 1034,
    "routing_accuracy": 0.851,
    "tool_path_accuracy": 0.0,
    "sql_validity_rate": 0.749,
    "answer_format_validity": 1.0,
    "groundedness_pass_rate": 0.52,
    "avg_groundedness_score": 0.62,
    "avg_latency_ms": 12300.0,
    "spider_exact_match_rate": 0.34,
    "spider_exact_match_avg_f1": 0.68
  },
  "by_suite": { ... },
  "by_language": { ... },
  "spider_execution_match_rate": 0.42,
  "failure_buckets": {
    "SQL_EXECUTION_ERROR": 499,
    "SQL_COMPONENT_MISMATCH": 269,
    "ROUTING_ERROR": 154,
    ...
  }
}
```

---

### 2. `evals/build_spider_cases.py`

**Purpose:** Dataset generator (one-time script)

#### `load_dev_cases()` (lines 16-58)

Reads from:
- `data/spider_1/spider_data/dev.json` (metadata + questions)
- `data/spider_1/spider_data/dev_gold.sql` (gold SQL answers)

Generates **2 case variants per example** (EN + VI):
1. **English variant:** `id = "spider_dev_0000_en"`, `language = "en"`
2. **Vietnamese variant:** `id = "spider_dev_0000_vi"`, `language = "vi"`, question prepended with Vietnamese context

**Case structure** (lines 32-51):
```python
{
    "id": "spider_dev_0000_en",
    "suite": "spider",
    "language": "en",
    "query": "How many singers do we have?",
    "expected_intent": "sql",
    "expected_tools": [
        "route_intent",
        "get_schema",
        "generate_sql",
        "validate_sql",
        "query_sql",
        "analyze_result"
    ],
    "should_have_sql": True,
    "expected_keywords": [],
    "target_db_path": "data/spider_1/spider_data/database/concert_singer/concert_singer.sqlite",
    "gold_sql": "SELECT count(*) FROM singer",
    "metadata": {"db_id": "concert_singer", "spider_idx": 0}
}
```

**Key observations:**
- ALL cases have `expected_tools` = same hardcoded list (6 tools)
- `should_have_sql` always True for Spider cases
- `expected_keywords` always empty (no keyword grounding tests)
- `target_db_path` points to SQLite database under `data/spider_1/spider_data/database/`

#### `load_test_cases()` (lines 61-96)

Same structure, but reads from:
- `data/spider_1/spider_data/test.json`
- `data/spider_1/spider_data/test_gold.sql`
- Uses `TEST_DATABASE_DIR` = `data/spider_1/spider_data/test_database/`

---

### 3. `evals/case_contracts.py`

**Purpose:** Data contracts for test cases

#### `EvalCase` Dataclass (lines 22-57)

```python
@dataclass(frozen=True)
class EvalCase:
    id: str
    suite: SuiteName  # Literal["domain", "spider", "movielens"]
    language: Language  # Literal["vi", "en"]
    query: str
    expected_intent: IntentName  # Literal["sql", "rag", "mixed"]
    expected_tools: list[str]
    should_have_sql: bool
    expected_keywords: list[str] = field(default_factory=list)
    target_db_path: str | None = None
    gold_sql: str | None = None
    expected_context_type: ContextType = "default"  # Literal["user_provided", "csv_auto", "mixed", "default"]
    metadata: dict[str, Any] = field(default_factory=dict)
```

**Fields:**
- `id`: Unique identifier (e.g., `"spider_dev_0000_en"`)
- `suite`: Which benchmark/dataset
- `language`: Test language (Vietnamese/English)
- `query`: The question/task
- `expected_intent`: Classification the agent should output
- `expected_tools`: Tools the agent should invoke (for path validation)
- `should_have_sql`: Whether answer should include SQL generation
- `expected_keywords`: For grounding validation (optional)
- `target_db_path`: SQLite database path for query execution
- `gold_sql`: Ground truth SQL for comparison
- `expected_context_type`: Expected context retrieval type (for internal context system)

**Loader: `load_cases_jsonl(path)` (lines 60-74)**
- Reads JSONL file (one case per line)
- Parses JSON and constructs EvalCase via `EvalCase.from_dict()`
- Validates case.id is present

---

### 4. `evals/metrics/execution_accuracy.py`

**Purpose:** Execution-based SQL comparison

#### `ExecutionAccuracyEvaluator.evaluate()` (lines 52-161)

**Input:** `pred_sql, gold_sql, db_path`

**Flow:**

1. **Validation checks:**
   - Both SQLs non-empty and stripped
   - Database exists and is accessible
   - Both SQL must be executable (or both empty for match)

2. **Execution:** Execute both against same database
   ```python
   gold_result, gold_error = _execute_sql(gold_sql, db_path)
   pred_result, pred_error = _execute_sql(pred_sql, db_path)
   ```

3. **Comparison:**
   ```python
   if len(gold_rows) != len(pred_rows):
       return ExecutionAccuracyResult(execution_match=False, ...)
   
   gold_cols = set(gold_rows[0].keys()) if gold_rows else set()
   pred_cols = set(pred_rows[0].keys()) if pred_rows else set()
   if gold_cols != pred_cols:
       return ExecutionAccuracyResult(execution_match=False, ...)
   
   normalized_gold = _normalize_result_rows(gold_rows)
   normalized_pred = _normalize_result_rows(pred_rows)
   if normalized_gold == normalized_pred:
       return ExecutionAccuracyResult(execution_match=True, ...)
   ```

#### `_normalize_result_rows()` (lines 27-34)

```python
def _normalize_result_rows(rows: list[dict], limit: int = 100) -> list[tuple]:
    compact = rows[:limit]  # ⚠️ LIMIT 100
    normalized: list[tuple] = []
    for row in compact:
        items = tuple(sorted((str(k), str(v)) for k, v in row.items()))
        normalized.append(items)
    normalized.sort()
    return normalized
```

**Critical behavior:**
- **Only compares first 100 rows** (limit=100)
- Converts each row dict to sorted tuple of (key, value) pairs (case-insensitive)
- Sorts all tuples (order-independent comparison)

**Impact on SQL generation:**
- If agent generates `SELECT ... LIMIT 50` and gold has no limit
  - Pred: 50 rows
  - Gold: 500+ rows
  - After normalization: First 100 rows each
  - Result: **May falsely match** if first 100 rows are identical

---

### 5. `evals/metrics/spider_exact_match.py`

**Purpose:** Component-based SQL comparison (Spider benchmark standard)

#### Algorithm Overview

Parses both SQL queries into components:
- SELECT clause items
- FROM clause tables/joins
- WHERE conditions
- GROUP BY columns
- HAVING clauses
- ORDER BY columns
- LIMIT value
- OFFSET value
- Set operations (INTERSECT, UNION, EXCEPT)

Then compares component-by-component using precision/recall/F1.

#### Detailed Parsing: `parse_sql_into_components(sql)` (lines 339-354)

1. **Tokenize** (lines 67-80): Remove comments, split on SQL keywords
   ```python
   tokens = re.split(
       r"(\bSELECT\b|\bFROM\b|\bWHERE\b|...)",
       sql,
       flags=re.IGNORECASE,
   )
   ```

2. **Split by clause** (lines 83-137): Assign tokens to current clause
   - Start with "select" clause
   - When encountering keyword (SELECT, FROM, WHERE, ...), switch clause
   - Accumulate non-keyword tokens into current clause

3. **Extract clause-specific items:**

   **SELECT** (lines 147-165):
   - Iterates through tokens, accumulates to current item
   - Splits on comma (respecting parentheses depth)
   - Normalizes: removes quotes, strips, lowercases
   - Returns `frozenset[str]` of select items

   **FROM** (lines 168-214):
   - Handles nested subqueries (tracks parentheses depth)
   - Handles JOIN keywords and ON clauses
   - Handles table aliases (AS keyword)
   - Separates on comma
   - Returns normalized table references

   **WHERE** (lines 217-238):
   - Splits on AND/OR at depth=0 (not in parentheses)
   - Each condition normalized separately
   - Returns `frozenset[str]` of conditions

   **Condition normalization** (lines 241-252):
   ```python
   def _normalize_condition(cond: str) -> str:
       cond = re.sub(r"\s+", " ", cond).strip().lower()
       cond = re.sub(r"'([^']*)'", r"\1", cond)  # Remove quotes
       cond = re.sub(r"(\d+)\s*<=\s*(\d+)", r"\2 >= \1", cond)  # Normalize
       cond = re.sub(r"(\w+)\s*<>\s*(\w+)", r"\2 <> \1", cond)
       parts = re.split(r"(>=|<=|=|<>|<|>|\bLIKE\b|...)", cond, flags=re.IGNORECASE)
       return " ".join(parts)
   ```

   **GROUP BY** (lines 255-275):
   - Stops at HAVING/ORDER/LIMIT
   - Normalizes each item
   - Returns `frozenset[str]`

   **ORDER BY** (lines 278-292):
   - Extracts column + direction (ASC/DESC)
   - Stops at LIMIT/OFFSET
   - Returns `frozenset[str]`

   **LIMIT/OFFSET** (lines 319-324):
   - Extracts numeric values only

   **Set operations** (lines 327-336):
   - Checks if INTERSECT/UNION/EXCEPT present in SQL (case-insensitive)
   - Returns `frozenset[str]` with op names if present

#### Comparison: `SpiderExactMatchEvaluator.evaluate()` (lines 398-442)

```python
def evaluate(self, pred_sql: str, gold_sql: str, db_path: str | None = None) -> SpiderExactMatchResult:
    pred_components = parse_sql_into_components(pred_sql)
    gold_components = parse_sql_into_components(gold_sql)
    
    for attr in SQL_COMPONENTS:  # 11 components
        pred_val = getattr(pred_components, attr)
        gold_val = getattr(gold_components, attr)
        metrics = _set_metrics(pred_val, gold_val)  # Precision, recall, F1
        partial_scores[attr] = metrics
        component_breakdown[attr] = bool(pred_val == gold_val)  # Exact match?
    
    overall_f1 = average(all_f1s)
    exact_match = all(component_breakdown.values())  # ALL must match
    
    return SpiderExactMatchResult(
        exact_match=exact_match,
        partial_scores=partial_scores,
        component_breakdown=component_breakdown,
        overall_f1=overall_f1
    )
```

#### `_set_metrics()` (lines 363-379)

For each component, compute precision, recall, F1:

```python
def _set_metrics(pred_set: frozenset[str], gold_set: frozenset[str]) -> dict:
    if not pred_set and not gold_set:
        return {"acc": 1.0, "rec": 1.0, "f1": 1.0}  # Both empty = perfect match
    if not pred_set or not gold_set:
        return {"acc": 0.0, "rec": 0.0, "f1": 0.0}  # Only one empty = no match
    
    tp = len(pred_set & gold_set)  # Intersection (true positives)
    precision = tp / len(pred_set)
    recall = tp / len(gold_set)
    f1 = 2 * precision * recall / (precision + recall)
    return {"acc": precision, "rec": recall, "f1": f1}
```

**Key insight:** "acc" actually means precision (TP / all predicted)

#### Issues with Parsing

1. **Schema name case-sensitivity:**
   - Normalizes to lowercase: `_normalize_value()` strips quotes and lowercases
   - **Problem**: `Song_Name` becomes `song_name`
   - If gold has different capitalization than generated, exact_match fails
   - But partial F1 scores might still be high (if spelling matches)

2. **Complex subquery handling:**
   - Parentheses depth tracking prevents splitting on keywords inside subqueries
   - But normalization is naive: doesn't understand nested structure
   - May merge or split subquery clauses incorrectly

3. **Whitespace normalization:**
   - Uses `re.sub(r"\s+", " ", ...)` to collapse whitespace
   - But doesn't handle SQL multi-line formats consistently

---

### 6. `app/prompts/sql.py`

**Purpose:** SQL generation prompt templates

#### `SQL_PROMPT_DEFINITION` (lines 14-50)

System role (lines 19-27):
```
Rules:
- Read-only queries only (SELECT or WITH ... SELECT).
- Only use tables/columns from the provided schema context.
- Prefer LIMIT clauses to keep results small (<=200 rows).
- Always keep language neutral and precise; return SQL text only.
```

User template (lines 31-47):
```
{{#if session_context}}
Previous conversation context (for follow-up questions):
{{session_context}}

{{/if}}
Question:
{{query}}

Schema context:
{{schema_context}}

Dataset stats (row counts, min/max dates, sample rows):
{{dataset_context}}

{{#if semantic_context}}
Relevant semantic context:
{{semantic_context}}

{{/if}}
Return SQL only.
```

**Critical issue:** "Prefer LIMIT clauses to keep results small (<=200 rows)" is guidance, not enforcement
- Agent may or may not add LIMIT
- If agent adds `LIMIT 200` but gold SQL has no limit:
  - Execution accuracy may falsely pass (first 100 rows match)
  - Spider exact match fails (LIMIT component different)

#### `SQL_SELF_CORRECTION_PROMPT_DEFINITION` (lines 52-98)

Similar structure, adds:
- Previous SQL attempt (marked FAILED)
- Error message
- Instructions to fix specific error

---

### 7. `evals/metrics/llm_judge.py`

**Purpose:** LLM-based answer quality evaluation

#### `LLMAnswerJudge.evaluate()` (lines 54-122)

Calls LLM with prompt evaluating answer on:
1. **Completeness:** Does it fully answer the question?
2. **Groundedness:** Is it supported by evidence?
3. **Clarity:** Is it clear and well-explained?

Returns `LLMJudgeResult` with scores 0.0-1.0 per dimension and overall score.

**Key detail:**
- Uses model: `"gh/gpt-4o"` (GitHub OpenAI proxy)
- Temperature: 0.0 (deterministic)
- Expects JSON response: `{"completeness": float, "groundedness": float, "clarity": float, "overall_score": float, "reasoning": str}`

---

### 8. `evals/groundedness.py`

**Purpose:** Verify answer is grounded in evidence (no hallucinations)

#### `evaluate_groundedness()` (lines 144-163)

**Hybrid approach:**
1. Keyword-based evaluation (fast)
2. LLM fallback if keyword score < 0.5 (slower, more accurate)

#### `_keyword_groundedness()` (lines 166-210)

```python
def _keyword_groundedness(answer: str, evidence: list[str], expected_keywords: list[str]) -> GroundednessResult:
    # Keyword coverage: How many expected keywords appear in answer?
    supported_keywords, missing_keywords = _keyword_coverage(answer, expected_keywords)
    
    # Numeric claims: Any numbers in answer supported by evidence?
    answer_numbers = set(_extract_number_claims(answer))
    evidence_numbers = set(_extract_number_claims(evidence_blob))
    
    unsupported_claims = [f"numeric_claim:{n}" for n in (answer_numbers - evidence_numbers)]
    
    keyword_score = len(supported_keywords) / len(expected_keywords) if expected_keywords else 1.0
    claim_penalty = min(0.5, 0.1 * len(unsupported_claims))
    score = max(0.0, keyword_score - claim_penalty)
    
    passed = score >= 0.7 and not unsupported_claims
    
    return GroundednessResult(score=score, passed=passed, ...)
```

**Key behaviors:**
- **Keyword score:** Ratio of supported expected keywords
- **Claim penalty:** 0.1 per unsupported numeric claim (max -0.5)
- **Pass criteria:** score >= 0.7 AND no unsupported claims
- **Marked answer:** Appends `[UNSUPPORTED_CLAIMS]` if present

#### `_llm_evaluate_groundedness()` (lines 49-141)

Calls LLM as fallback if keyword-based score < 0.5:
- Semantic evaluation (doesn't require exact keyword matching)
- Returns JSON: `{"score": float, "passed": bool, "reason": str}`

---

## Data Structures & Contracts

### `CaseResult` Dataclass (runner.py, lines 39-76)

```python
@dataclass
class CaseResult:
    # Input/Output
    case_id: str
    suite: str
    language: str
    query: str
    
    # Intent/Routing
    expected_intent: str
    predicted_intent: str
    routing_correct: bool
    
    # Tool path validation
    expected_tools: list[str]
    used_tools: list[str]
    tool_path_correct: bool
    
    # SQL Generation
    should_have_sql: bool
    generated_sql: str
    has_sql: bool
    sql_valid: bool
    
    # Answer quality
    answer_format_valid: bool
    confidence: str
    
    # Performance
    latency_ms: float
    
    # Metrics
    execution_match: bool | None
    spider_exact_match: bool | None
    spider_exact_match_f1: float | None
    answer_quality_score: float | None
    answer_quality_reasoning: str | None
    
    # Groundedness
    groundedness_score: float
    groundedness_pass: bool
    unsupported_claims: list[str]
    groundedness_fail_reasons: list[str]
    marked_answer: str
    
    # Debug
    error_categories: list[str]
    failure_bucket: str | None
    run_id: str
    
    # Context
    expected_context_type: str = "default"
    predicted_context_type: str | None = None
    context_type_correct: bool | None = None
    
    # For official Spider eval
    gold_sql: str | None = None
    target_db_path: str | None = None
```

**Key observations:**
- Stores both expected and predicted values for comparison
- Three-valued logic for metrics (bool | None) - None means not applicable
- `failure_bucket` is priority-ordered categorization

---

## Evaluation Metrics Pipeline

### Metrics Evaluated for Each Case

| Metric | Type | Source | Range | Pass Gate |
|--------|------|--------|-------|-----------|
| `routing_correct` | bool | Intent matching | T/F | >= 0.90 (90%) |
| `tool_path_correct` | bool | Tool list check | T/F | >= 0.95 (95%) |
| `sql_valid` | bool | SQL syntax validation | T/F | >= 0.90 (90%) |
| `answer_format_valid` | bool | Payload structure | T/F | = 1.00 (100%) |
| `groundedness_pass` | bool | No hallucinations | T/F | >= 0.70 (70%) |
| `execution_match` | bool\|None | Row data comparison | T/F/None | N/A |
| `spider_exact_match` | bool\|None | Component match | T/F/None | N/A |
| `spider_exact_match_f1` | float\|None | Component F1 | 0-1/None | N/A |
| `answer_quality_score` | float\|None | LLM judge | 0-1/None | N/A |
| `groundedness_score` | float | Keyword+LLM | 0-1 | N/A |

### Gate Thresholds (runner.py, lines 30-36)

```python
GATE_THRESHOLDS = {
    "routing_accuracy": 0.90,
    "sql_validity_rate": 0.90,
    "tool_path_accuracy": 0.95,
    "answer_format_validity": 1.00,
    "groundedness_pass_rate": 0.70,
}
```

**Pass logic:** All thresholds must be met for gates to pass (line 462-469)

---

## SQL Parsing & Comparison

### Three-Layer SQL Validation

1. **Syntax validation** (`app.tools.validate_sql`):
   - Parses SQL without executing
   - Checks SQLite syntax rules
   - Does NOT check schema (tables/columns must exist)

2. **Execution accuracy** (ExecutionAccuracyEvaluator):
   - Executes both against database
   - Compares result sets (row count, columns, data)
   - Order-independent normalization
   - **LIMIT 100 comparison** (critical bug)

3. **Component matching** (SpiderExactMatchEvaluator):
   - Parses SQL structure
   - Compares SELECT, FROM, WHERE, ... components
   - Calculates precision/recall/F1 per component
   - Overall F1 average of all 11 components
   - Exact match = ALL components identical

### Comparison Strategy

**When to use each:**
- **Syntax validation:** Always, before execution
- **Execution accuracy:** Primary (gives True/False, easiest to understand)
- **Component matching:** Secondary (gives F1 scores for debugging)
- **Official Spider eval:** Only for batch evaluation (requires gold SQL in result)

---

## Prompts & SQL Generation

### Prompt Injection Points

1. **System message:** "Prefer LIMIT clauses to keep results small (<=200 rows)"
   - Guidance only, not enforced
   - Agent may ignore or add different limit

2. **User message template variables:**
   - `{{query}}`: The user question
   - `{{schema_context}}`: Table/column definitions
   - `{{dataset_context}}`: Row counts, samples, min/max dates
   - `{{semantic_context}}`: RAG-retrieved business context (optional)
   - `{{session_context}}`: Conversation history (optional)

3. **Self-correction prompt:**
   - Includes error message from previous SQL attempt
   - Asks agent to fix specific error

### LIMIT Injection Issue

**Current guidance:** "Prefer LIMIT clauses to keep results small (<=200 rows)"
- NOT enforced by prompt
- NOT guaranteed by post-processing
- Agent may:
  - Add `LIMIT 200` (not in gold)
  - Add `LIMIT 100` (partial match)
  - Add `LIMIT 50` (different LIMIT value)
  - Omit LIMIT entirely

**Symptom:**
- Spider exact match fails: LIMIT component different
- Execution accuracy may pass: First 100 rows identical

**Recommended fix:** Post-process generated SQL to enforce LIMIT before execution if not present

---

## Critical Integration Points

### 1. Database Path Resolution

**Path formats across codebase:**

```
EvalCase.target_db_path:  "data/spider_1/spider_data/database/concert_singer/concert_singer.sqlite"
                          ↓
                          Used by app.tools (validate_sql, query_sql)
                          Used by ExecutionAccuracyEvaluator._execute_sql()
                          Used by OfficialSpiderEvaluator (extract db_id via Path.stem)
```

**Extraction logic in OfficialSpiderEvaluator (line 448):**
```python
db_id = Path(db_path).stem  # "concert_singer"
gold_pairs.append((gold_sql, db_id))
```

**Assumption:** Path format is exactly `.../<db_id>/<db_id>.sqlite`

**Fragility:** Non-standard paths will extract wrong db_id

---

### 2. Payload Structure

**Expected payload keys** (runner.py, line 83):
```python
required = {"answer", "evidence", "confidence", "used_tools", "generated_sql"}
```

**Validation:**
- Check all keys present
- Check evidence is list
- Check used_tools is list

**If missing:** `answer_format_valid = False` → categorized as SYNTHESIS_ERROR

---

### 3. Intent Extraction

**Priority order** (runner.py, lines 93-100):
1. Check `payload.get("intent")` directly
2. Search evidence list for items starting with "intent=" prefix
3. Default to "unknown"

**Comparison:** `predicted_intent == case.expected_intent` (line 241)

---

### 4. Gold SQL Availability

**Requirement:** `CaseResult.gold_sql` must be set for official Spider eval

**Current status:**
- `build_spider_cases.py` writes gold_sql to case JSON ✓
- `runner.py:run_case()` stores `case.gold_sql` on result ✓
- `runner.py:_run_official_spider_eval()` retrieves via `getattr(r, "gold_sql", None)` ✓

**Issue:** If any step omits gold_sql, official eval silently fails

---

## Known Issues & Gaps

### 1. Tool Path Accuracy = 0.0%

**Current behavior:**
```python
def _tool_path_ok(expected_tools, used_tools) -> bool:
    used = set(used_tools)
    return all(tool in used for tool in expected_tools)
```

**Expected tools:** `["route_intent", "get_schema", "generate_sql", "validate_sql", "query_sql", "analyze_result"]`

**Actual used tools:** (varies by run, but typically subset of expected)

**Issue:** Function checks if ALL expected tools are present, but agent may short-circuit pipeline after generating SQL

**Current data:** tool_path_accuracy = 0.0% (all cases fail)

**Resolution options:**
- A) Make expected_tools dynamic (based on intent/route)
- B) Change `_tool_path_ok` to check subset/order/presence
- C) Accept that tool paths won't be exact matches

---

### 2. LIMIT Injection Creates Execution Accuracy False Positives

**Problem:**
- Prompt says "Prefer LIMIT <=200"
- Agent may add `LIMIT 200`, `LIMIT 50`, or omit LIMIT
- Execution accuracy compares only first 100 rows
- Example:
  - Gold SQL: `SELECT col FROM table` → 500 rows
  - Pred SQL: `SELECT col FROM table LIMIT 200` → 200 rows
  - After normalization: First 100 rows of each → **MATCH** ✓ (false positive!)

**Symptom in metrics:**
- Spider exact match fails (LIMIT component different)
- Execution accuracy passes (first 100 rows identical)
- Contradiction suggests comparison mismatch

**Fix options:**
- A) Enforce LIMIT in post-processing (remove LIMIT before comparison)
- B) Compare full result sets (no LIMIT)
- C) Add LIMIT to gold_sql before comparison

---

### 3. Schema Name Case-Sensitivity in Component Parsing

**Problem:**
- Gold SQL: `SELECT Song_Name FROM singer`
- Pred SQL: `SELECT song_name FROM singer`
- Parser normalizes both to `song_name` (lowercase)
- Spider exact match: SELECT component exact match fails (different objects before normalization)
- But after normalization in F1 calculation: precision/recall may be high

**Symptom:**
- exact_match = False
- partial_scores["select"]["f1"] = high (e.g., 0.9)

**Root cause:**
- `_normalize_value()` lowercases but doesn't account for schema naming conventions
- Different databases use different conventions: snake_case, PascalCase, camelCase

---

### 4. Official Spider Eval Data Loss

**Issue:** CaseResult doesn't automatically store gold_sql
- Fixed by storing in `run_case()` (line 274)
- But if gold_sql omitted from EvalCase, result is None
- OfficialSpiderEvaluator falls back to error (no cases_with_gold)

**Current status:** Likely already fixed in code

---

### 5. No Tool Order Validation

**Current implementation:**
```python
def _tool_path_ok(expected_tools, used_tools) -> bool:
    used = set(used_tools)
    return all(tool in used for tool in expected_tools)
```

**Does NOT validate:**
- Order of tool execution
- Whether tools were called multiple times
- Whether unexpected tools were called

**Example:**
- Expected: `[A, B, C, D]`
- Actual: `[B, A, C, E, D]` (reordered + extra tool E)
- Check: **PASSES** (all expected present)

**Impact:** Can't detect incorrect execution flow

---

### 6. Groundedness Only Checks Expected Keywords, Not General Hallucinations

**Issue:**
- `evaluate_groundedness()` only checks if expected_keywords appear
- For Spider cases: `expected_keywords = []` (empty)
- Therefore: groundedness_pass = True for all Spider cases (vacuous truth)
- Not detecting hallucinations in numbers or explanations

**Symptom:**
- groundedness_pass_rate = 100% for Spider suite
- But visually, some answers have fabricated numbers

**Root cause:**
- Spider dataset has no expected_keywords defined
- Keyword-based evaluation is vacuous
- LLM fallback only triggers if keyword_score < 0.5
- With empty keywords: keyword_score = 1.0 (no missing keywords)
- LLM fallback never triggered

**Fix needed:**
- Define expected_keywords for Spider cases
- OR always use LLM evaluation for Spider (not just fallback)
- OR use different groundedness metric for SQL benchmarks

---

### 7. No Parametrization of Evaluators

**Current:**
- All evaluators hardcoded (no configuration)
- ExecutionAccuracyEvaluator: limit=100 hardcoded
- SpiderExactMatchEvaluator: always uses same algorithm
- LLMAnswerJudge: always uses gpt-4o

**Flexibility needed:**
- Different limits for different datasets
- Different evaluators for different metrics
- Model selection per environment

---

## Summary Table

| Component | File | Purpose | Key Issue |
|-----------|------|---------|-----------|
| **Case Loading** | `build_spider_cases.py` | Generate test cases | Hardcoded expected_tools, no per-case customization |
| **Case Contract** | `case_contracts.py` | Data structure | Works well, but expected_tools always same list |
| **Runner** | `runner.py` | Orchestrator | tool_path_accuracy always 0%, gold_sql sometimes lost |
| **Execution Accuracy** | `metrics/execution_accuracy.py` | Row comparison | LIMIT 100 causes false positives |
| **Spider Exact Match** | `metrics/spider_exact_match.py` | Component comparison | Case-sensitivity in schema names |
| **LLM Judge** | `metrics/llm_judge.py` | Answer quality | Good, no major issues |
| **Groundedness** | `groundedness.py` | Hallucination detection | Empty keywords = vacuous truth for Spider |
| **Official Spider Eval** | `metrics/official_spider_eval.py` | Subprocess eval | Fragile output parsing, requires gold_sql |
| **SQL Prompts** | `prompts/sql.py` | LLM instructions | LIMIT guidance not enforced |

---

## Recommended Next Steps

1. **Investigate tool_path_accuracy = 0.0%**: Are expected_tools correct? Or should check be different?
2. **Fix LIMIT injection**: Add post-processing or change comparison strategy
3. **Define expected_keywords for Spider**: Enable groundedness validation
4. **Add configurable parameters**: Make evaluators testable with different settings
5. **Validate schema name handling**: Test case-sensitivity scenarios
6. **Strengthen official Spider eval**: Add better output parsing, fallbacks
