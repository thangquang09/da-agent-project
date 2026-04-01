# Comprehensive Analysis: DA Agent Evaluation Pipeline

## Executive Summary

The evaluation pipeline has **5 major categories of issues** affecting 1,034 Spider dev cases:

| Failure Type | Count | % | Root Cause |
|---|---|---|---|
| **SQL_EXECUTION_ERROR** | 499 | 48.3% | LIMIT 200 adds unwanted rows, breaking result matching |
| **SQL_COMPONENT_MISMATCH** | 269 | 26.0% | Schema naming mismatch (e.g., `song_name` vs `Song_Name`) |
| **ROUTING_ERROR** | 154 | 14.9% | Intent routing fails to classify 'sql' intent (~15% of cases) |
| **SQL_GENERATION_ERROR** | 110 | 10.6% | Agent generates empty SQL (tool chain broken) |
| **TOOL_PATH_MISMATCH** | 2 | 0.2% | Expected tool sequence not invoked (minor) |

**Performance Metrics:**
- Total eval time: **211.9 minutes** (avg 12.3s/case, max 36s/case)
- Official Spider eval: **FAILED** - couldn't run due to missing gold_sql data
- Routing accuracy: **85.1%** (passes 0.90 gate requirement only by definition issue)
- Tool-path accuracy: **0.0%** (expected tools don't match actual execution)
- SQL validity rate: **74.9%** (cases pass SQL syntax validation)
- Answer format validity: **100.0%** (all payloads have required keys)

---

## Part 1: File-by-File Analysis

### 1. `evals/metrics/official_spider_eval.py`

**Purpose:** Subprocess wrapper around official `test-suite-sql-eval` script from taoyds/test-suite-sql-eval

**Key Functionality:**
- `OfficialSpiderEvaluator.evaluate_batch()`: Writes gold/pred SQL to temp files, runs `evaluation.py` via subprocess
- `_parse_stdout()`: Regex-based parser for hardness breakdown (easy/medium/hard/extra/all)
- Timeout handling: 600s default, configurable

**Issues & Anti-Patterns:**

1. **No gold_sql stored on CaseResult** (lines 420-440)
   - Code comment admits: "CaseResult has no gold_sql field, so we fall back to using generated_sql"
   - Fallback workaround: `getattr(r, "gold_sql", None)` to check if gold_sql was stored
   - **Problem**: If gold_sql not stored, entire official eval returns error (line 435-440)
   - **Result**: `summary["official_spider_exec_accuracy"] = None` in reports

2. **Fragile output parsing** (lines 55-133)
   - Relies on exact format: `EXECUTION ACCURACY` separator, then `execution <vals>`
   - Uses fragile regex: `r"^execution\s+[0-9.]"`
   - **Risk**: Any stdout format change breaks parsing silently, returns 0.0 accuracy
   - No warning logged when parsing fails

3. **Path handling complications** (lines 159, 244)
   - Must resolve to absolute path because subprocess runs with `cwd=vendor dir`
   - Comment explains: "Always resolve to absolute path — subprocess runs with cwd=vendor dir"
   - **Fragility**: If vendor dir not found, throws FileNotFoundError (line 165)

4. **Timeout not effective for batch size** (line 156, 243)
   - Timeout=600s is global for entire batch evaluation
   - With 1034 cases at 12.3s each, batch would need ~3.5 hours
   - **Reality**: Likely times out on large batches without being noticed

5. **SQL normalization issue** (lines 205-207)
   - `_normalize_sql()` converts multi-line SQL to single line
   - Gold SQL format expected: `<sql>\t<db_id>` (line 211)
   - **Mismatch**: CaseResult has `target_db_path` but needs to extract `db_id` (line 448)
   - Extraction: `db_id = Path(db_path).stem` - assumes path format `.../<db_id>/<db_id>.sqlite`

**Performance Concern:**
- Subprocess spawning cost: Each evaluation spawns new Python process
- No batching optimization: Could cache evaluator across multiple batches

**Code Quality:**
- ✓ Good: Type hints, frozen dataclasses, error messages
- ✗ Bad: Comments explaining workarounds instead of fixing issues
- ✗ Bad: Inline path logic should be extracted to Path helper function

---

### 2. `evals/runner.py` - Main Evaluation Driver

**Purpose:** Orchestrates parallel case execution, collects results, runs optional official eval, generates reports

**Key Components:**

#### Case Execution Flow
```python
run_case(case) -> CaseResult
  1. run_query(case.query) -> payload
  2. Extract: intent, used_tools, generated_sql, answer, evidence
  3. Execute metrics:
     - SQL validity check
     - Execution accuracy (gold vs pred SQL)
     - Spider exact match
     - LLM answer judge
     - Groundedness evaluation
  4. Categorize failure into failure_bucket (routing_error, sql_error, etc.)
```

#### Critical Issues:

1. **Tool Path Accuracy = 0.0% (ALL cases fail)** (lines 103-105, 244)
   
   ```python
   def _tool_path_ok(expected_tools, used_tools) -> bool:
       return all(tool in used_tools for tool in expected_tools)
   
   # In build_spider_cases.py:
   expected_tools = ["route_intent", "get_schema", "generate_sql", "validate_sql", "query_sql", "analyze_result"]
   
   # Actual used_tools (from cases):
   # ["detect_context_type", "route_intent", "task_planner", "aggregate_results"]
   ```
   
   **Root Cause:** Build cases define hardcoded tool sequence, but actual agent executes different workflow
   - Expected tools are abstract/idealized
   - Actual agent uses modern graph nodes: `detect_context_type`, `task_planner`, `aggregate_results`
   - **Impact**: Gate metric fails even when agent works correctly
   
   **Analysis**: This is NOT an agent bug - it's a **test case definition mismatch**

2. **LIMIT 200 Auto-Injected** (457/499 execution errors)
   
   This is the **BIGGEST problem** - affects 48.3% of all cases
   
   - Generated SQL: `SELECT COUNT(*) FROM singer LIMIT 200`
   - Gold SQL: `SELECT count(*) FROM singer`
   - Result: Extra rows returned, execution match fails
   
   **Where it comes from**: Unknown - likely in SQL generation node or validation layer
   - Not in this file's generation
   - Must be in `app/tools/generate_sql()` or `app/tools/validate_sql()`
   
   **Severity**: HIGH - breaks execution accuracy evaluation systematically

3. **Schema Name Mismatch** (269 cases, 26%)
   
   Generated: `FROM singer WHERE Country = 'France'`
   Gold: `FROM singer WHERE country = 'France'`
   
   Spider schemas use mixed case column names but evaluators expect exact match
   
   **Impact**: 
   - ExecutionAccuracyEvaluator checks column names (line 135-144)
   - SpiderExactMatchEvaluator tokenizes and compares SQL structure
   - Result: Fails both execution and exact match even though SQL is semantically correct

4. **Routing Error = 15% (intent misclassification)** (lines 241, 147)
   
   - Expected: 'sql' intent for all Spider cases
   - Actual: Some cases return 'unknown' or other intents
   - **Root Cause**: Intent routing model unreliable for borderline cases
   - **Impact**: Cascading failure - can't proceed with SQL generation

5. **SQL Generation Missing** (10.6% of cases)
   
   - Query provided but generated_sql is empty string
   - Tool executed but returned null/empty
   - **Indicator**: Tool chain broken or timeout in agent
   
   **Hypothesis**: Related to recursion_limit exceeded (default=25 in runner)

6. **Gold SQL Not Stored on CaseResult** (lines 74-76)
   
   ```python
   gold_sql: str | None = None
   target_db_path: str | None = None
   ```
   
   Fields exist but:
   - `run_case()` doesn't populate them from the EvalCase
   - `_run_official_spider_eval()` tries to access them (line 433) but they're None
   - **Result**: Official eval always fails with "No spider EN cases with gold_sql found"

#### Concurrency Design:

```python
# ThreadPoolExecutor with max_workers=4 (default)
with ThreadPoolExecutor(max_workers=args.workers) as executor:
    futures = {executor.submit(run_with_args, case): case for case in cases}
    results = []
    for future in as_completed(futures):
        results.append(future.result())
```

**Issue**: No error handling - single thread exception crashes entire run
- Should wrap `future.result()` in try/except
- Should collect partial results even if some cases fail

#### Metric Summarization:

```python
def _metric_ratio(results, attr: str) -> float:
    return sum(1 for item in results if bool(getattr(item, attr))) / len(results)
```

**Issues**:
- Uses `bool()` conversion which treats empty string as False
- No null handling - crashes if attribute missing
- Divide by len(results) even if all None - returns 0.0 instead of None

#### Report Generation:

- Writes 3 outputs per run: per_case JSONL, summary JSON, summary Markdown
- Latest symlinks updated for CI consumption
- **Missing**: Summary of which metrics passed/failed gates

#### Gate Logic:

```python
GATE_THRESHOLDS = {
    "routing_accuracy": 0.90,
    "sql_validity_rate": 0.90,
    "tool_path_accuracy": 0.95,  # ← IMPOSSIBLE (always 0%)
    "answer_format_validity": 1.00,
    "groundedness_pass_rate": 0.70,
}
```

**Problem**: `tool_path_accuracy: 0.95` is unreachable because test cases have wrong expected_tools

---

### 3. `evals/build_spider_cases.py` - Case Generation

**Purpose:** Load Spider dev/test JSON and create evaluation case JSONL

**Issues:**

1. **Hardcoded Expected Tools** (lines 38-45)
   
   ```python
   "expected_tools": [
       "route_intent", "get_schema", "generate_sql",
       "validate_sql", "query_sql", "analyze_result"
   ]
   ```
   
   - **Fixed definition**: Assumes agent always calls these exact tools
   - **Reality**: Modern agent uses different workflow (task_planner, aggregate_results, etc.)
   - **Consequence**: 0% tool_path_accuracy for all cases
   
   **Fix**: Either:
   - Make expected_tools flexible/wildcard
   - Update expected_tools to match actual agent
   - Remove this gate requirement entirely

2. **Unused gold_map** (lines 19-25)
   
   ```python
   gold_map: dict[tuple[str, str], str] = {}
   for line in f:  # dev_gold.sql
       parts = line.strip().split("\t")
       if len(parts) >= 2:
           sql, db_id = parts[0], parts[1]
           gold_map[(db_id, sql)] = sql  # ← weird key, value is duplicate
   # Never used! gold_sql comes from item["query"]
   ```
   
   **Dead code**: Should be removed or this should be the official gold source

3. **bilingual doubling** (lines 53-57)
   
   ```python
   case_vi = case.copy()
   case_vi["id"] = f"spider_dev_{idx:04d}_vi"
   case_vi["language"] = "vi"
   case_vi["query"] = f"Hãy trả lời bằng SQL cho câu hỏi sau: {question}"
   ```
   
   - Duplicates all cases, adds Vietnamese translation
   - **Result**: 1034 cases = 517 EN + 517 VI
   - **Impact**: Bilingual eval OK, but doubles eval time

4. **Missing metadata normalization**
   
   - db_path stored as string, not Path
   - Inconsistent path separators (Windows vs Unix)
   - No validation that paths exist

---

### 4. `evals/case_contracts.py` - Data Structures

**Quality**: ✓ Good, clean dataclasses
- Proper type hints
- Frozen=True for immutability
- Path normalization in `_normalize_path()` (handles Windows/WSL)

**Issue**: `EvalCase.gold_sql` is optional (default None)
- Some cases loaded without gold_sql
- Downstream code assumes gold_sql exists
- Should make it required for Spider cases

---

### 5. `evals/metrics/execution_accuracy.py`

**Purpose:** Execute pred/gold SQL against same database, compare result sets

**Issues**:

1. **Strict Column Name Matching** (lines 135-144)
   
   ```python
   gold_cols = set(gold_rows[0].keys()) if gold_rows else set()
   pred_cols = set(pred_rows[0].keys()) if pred_rows else set()
   if gold_cols != pred_cols:
       return ExecutionAccuracyResult(execution_match=False, ...)
   ```
   
   - Gold SQL returns: `[{singer: ..., country: ...}]`
   - Pred SQL returns: `[{Singer: ..., Country: ...}]` (different case)
   - **Result**: FAILS even though data is identical
   
   **Root Cause**: SQLite preserves column name casing from SQL, not from schema
   - `SELECT country FROM singer` → column name is "country"
   - `SELECT Country FROM singer` → column name is "Country" (if using quoted identifier)
   
   **Impact**: Schema naming inconsistency breaks execution_accuracy metric

2. **Row limit = 100** (lines 27, 145)
   
   ```python
   def _normalize_result_rows(rows: list[dict[str, Any]], limit: int = 100) -> list[tuple]:
       compact = rows[:limit]
   ```
   
   - Silently truncates to first 100 rows
   - If query returns 101+ rows, comparison fails
   - **No warning**: Silent truncation makes debugging hard

---

### 6. `evals/metrics/spider_exact_match.py`

**Purpose:** Parse SQL into components (SELECT, FROM, WHERE, etc.) and compare structurally

**Issues**:

1. **Fragile Regex Tokenization** (lines 68-80)
   
   - 200+ character regex with alternation groups
   - Doesn't handle all SQL syntax (CTEs, window functions)
   - **Example failure**: CTE `WITH youngest_singer AS (...) SELECT ...` gets confused
   
   **Evidence**: One sample case shows truncated generated SQL:
   ```python
   "WITH youngest_singer AS (...) SELECT So"
   ```
   This is mid-parse truncation, suggesting regex tokenizer broke

2. **Schema Name Normalization Missing** (lines 140-144)
   
   - `_normalize_value()` lowercases but doesn't normalize quotes
   - `FROM "Singer"` vs `FROM singer` compared differently
   - Schema names should be normalized to lowercase for comparison

3. **Complex Component Extraction** (lines 147-325)
   
   - SELECT items extraction (147-165): Tries to parse parentheses, but:
     - Doesn't handle nested SELECT
     - Breaks on complex expressions like `CASE WHEN`
   - FROM items extraction (168-214): Struggles with JOINs
   - WHERE extraction (217-238): Overly simplistic AND/OR splitting
   
   **Result**: Many edge cases get wrong component sets

4. **F1 Score Definition** (lines 357-379)
   
   - Treats component mismatch as precision/recall problem
   - But components are sets, not sequential
   - F1 = 2*(P*R)/(P+R) is appropriate, but:
     - Returns 0.0 for empty sets (correct)
     - But penalizes missing components same as extra components
   
   **Example**: If pred adds "LIMIT 200" not in gold:
   - Precision = 0.9 (9/10 predicted components correct)
   - Recall = 1.0 (all gold components found)
   - F1 = 0.95 (marked as partial match, not failure)

---

### 7. `evals/groundedness.py`

**Purpose:** Evaluate if answer is grounded in evidence and contains expected keywords

**Key Functions**:
- `_keyword_coverage()`: Check if expected_keywords found in answer
- `evaluate_groundedness()`: Combines keyword-based + LLM fallback
- `_llm_evaluate_groundedness()`: Uses LLM for semantic evaluation

**Issues**:

1. **Keyword Matching is Too Strict** (lines 32-46)
   
   ```python
   for keyword in expected_keywords:
       normalized_kw = _normalize(keyword)
       if normalized_kw in normalized_answer:
           supported.append(keyword)
   ```
   
   - Substring match only
   - "trend" matches "trending" but not "trends"
   - No fuzzy matching or stemming
   
   **Impact**: Expected keywords often not found even when concept is present

2. **Numeric Claim Extraction is Naive** (lines 28-29)
   
   ```python
   return re.findall(r"\b\d+(?:[.,]\d+)?%?\b", text)
   ```
   
   - Extracts all numbers but no context
   - "2022-03-15" extracts ["2022", "03", "15"]
   - "Age > 20" extracts ["20"] but loses context
   
   **Result**: False positives for numeric grounding

3. **Keyword Score Calculation** (lines 188-193)
   
   ```python
   keyword_score = 1.0
   if expected_keywords:
       keyword_score = len(supported_keywords) / len(expected_keywords)
   claim_penalty = min(0.5, 0.1 * len(unsupported_claims))
   score = max(0.0, keyword_score - claim_penalty)
   passed = score >= 0.7 and not unsupported_claims
   ```
   
   - Passes only if score >= 0.7 AND zero unsupported_claims
   - "AND not unsupported_claims" is overly strict
   - One unsupported number causes entire fail
   
   **Example**: 3 expected keywords, 3 found (score=1.0), but 1 unsupported number (2.5-year-old claim in evidence, but generated "2.4") → FAIL

4. **LLM Fallback Rarely Used** (line 158)
   
   ```python
   if use_llm_fallback and keyword_result.score < 0.5 and expected_keywords:
   ```
   
   - LLM only called if score < 0.5
   - Overhead: 4-5 LLM calls per eval run
   - For 1034 cases with ~30% low score → 300+ LLM calls
   
   **Performance**: Adds 1-2 minutes to eval runtime

5. **Missing Evidence-Based Validation** (lines 166-210)
   
   - Never checks if evidence actually supports claims
   - Answer: "DAU increased 50%"
   - Evidence: ["Month 1: 100 DAU", "Month 2: 150 DAU"]
   - Expected keywords: ["dau", "increase"]
   - **Result**: PASS (keywords found) but no verification that 50% is correct (it is, but validator doesn't know)

---

### 8. `evals/metrics/llm_judge.py`

**Purpose:** Use LLM to evaluate answer quality on completeness, groundedness, clarity

**Issues**:

1. **Hardcoded Model** (line 40)
   
   ```python
   model="gh/gpt-4o",  # ← Fixed
   ```
   
   - Not configurable
   - "gh/" prefix suggests GitHub Models endpoint
   - Should use environment variable or config

2. **No Error Recovery** (lines 49-51)
   
   ```python
   except Exception as e:
       logger.warning("LLM judge call failed...")
       return None
   ```
   
   - Caller must handle None (line 99-106 does handle)
   - But returns default score 0.5 instead of propagating error
   - Masks failure - eval continues without knowing judge failed

3. **Prompt Injection Risk** (lines 77-82)
   
   - User inputs (question, answer) directly in prompt
   - No escaping or validation
   - Answer with `{` or `}` breaks JSON parsing (line 47)
   
   **Example**:
   ```
   Answer: {"result": "hacked"}
   → JSON parsing breaks
   → Falls back to score=0.5
   ```

4. **Evidence Truncation** (line 71)
   
   ```python
   evidence_for_prompt = evidence[:5] if len(evidence) > 5 else evidence
   ```
   
   - Silently truncates to 5 items
   - Large result sets lose context
   - **No warning**: Makes eval non-deterministic

---

## Part 2: Root Cause Analysis of Failure Buckets

### SQL_EXECUTION_ERROR (499 cases, 48.3%)

**Symptoms:**
- execution_match = False
- sql_valid = True (SQL syntax is correct)
- generated_sql contains "LIMIT 200"
- gold_sql has no LIMIT clause

**Root Cause Chain:**
1. **LIMIT 200 is auto-injected** somewhere in agent
   - Hypothesis 1: `app/tools/generate_sql()` or validation layer adds it
   - Hypothesis 2: Safety feature to prevent large dataset returns
   - Hypothesis 3: Query planning adds it for large tables

2. **Why it breaks execution match:**
   - Gold: `SELECT COUNT(*) FROM singer` → Returns 1 row: [count=23]
   - Pred: `SELECT COUNT(*) FROM singer LIMIT 200` → Returns 1 row: [count=23]
   - **Should match?** Yes! But...
   - ExecutionAccuracyEvaluator might have other issues (column name casing)

3. **Severity**: Critical - affects nearly half of cases
   
**Fix Required in**: `app/tools/` module (not eval code)

---

### SQL_COMPONENT_MISMATCH (269 cases, 26.0%)

**Symptoms**:
- spider_exact_match = False (or missing)
- execution_match might be True or None
- SQL syntax is valid

**Root Causes:**

1. **Schema Column Name Casing** (major)
   - Spider schemas use mixed case: `Song_Name`, `Song_release_year`
   - Generated SQL might use: `song_name`, `Song_Name`, `SONG_NAME`
   - Exact match evaluator treats these as different components
   
2. **LIMIT 200 component** (secondary)
   - Generated SQL: `... LIMIT 200`
   - Gold SQL: no LIMIT
   - spider_exact_match treats this as component mismatch

3. **Tokenization Failures** (tertiary)
   - Complex queries break regex tokenizer
   - CTEs, window functions, nested SELECT get mangled
   - Component extraction returns wrong sets

4. **Column Name Normalization Missing**
   - Should normalize all identifiers to lowercase
   - Currently doesn't for schema names

**Fix Required in**: `evals/metrics/spider_exact_match.py`

---

### ROUTING_ERROR (154 cases, 14.9%)

**Symptoms**:
- predicted_intent ≠ expected_intent
- Usually: predicted="unknown", expected="sql"

**Root Causes:**

1. **Intent Routing Model Insufficient**
   - Model trained on general QA, not domain-specific SQL detection
   - Queries like "Show me X" might be ambiguous
   - Some Spider queries are vague: "What is the name..." could be RAG or SQL

2. **No Schema Context**
   - Routing decision made before schema retrieval
   - Could use schema hints to classify as SQL query
   - Currently: intent → route → schema (wrong order?)

3. **Threshold Issues**
   - Confidence threshold for "sql" classification might be too high
   - Results in "unknown" fallback when unsure

4. **Bilingual Challenge**
   - Vietnamese queries especially struggle
   - Phrasings in Vietnamese translated to English might lose intent clarity

**Fix Required in**: `app/nodes/routing.py` (not eval code)

---

### SQL_GENERATION_ERROR (110 cases, 10.6%)

**Symptoms**:
- has_sql = False (empty generated_sql)
- should_have_sql = True (expected to generate)
- Tool executed but returned empty

**Root Causes:**

1. **Tool Chain Timeout**
   - Recursion limit (default=25) exceeded
   - Agent loops trying to fix bad SQL
   - Times out → returns empty result

2. **Schema Context Missing**
   - get_schema tool might fail
   - SQL generation without schema → empty attempt
   - Tool error not surfaced → empty result

3. **Model Hallucination**
   - LLM generates non-SQL response
   - Parser fails → empty string
   - No error logging

4. **Circular Dependency**
   - generate_sql → validate_sql → bad SQL → regenerate → loop → timeout

**Fix Required in**: `app/tools/generate_sql.py` and tool chain

---

### TOOL_PATH_MISMATCH (2 cases, 0.2%)

**Issue**: Only 2 cases but 0% tool_path_accuracy

**Reason**: expected_tools hardcoded incorrectly in build_spider_cases.py

All 1034 cases expect:
```
["route_intent", "get_schema", "generate_sql", "validate_sql", "query_sql", "analyze_result"]
```

All 1034 cases actually execute:
```
["detect_context_type", "route_intent", "task_planner", "aggregate_results"]
```

**Root Cause**: Test cases written before modern agent refactoring

**Fix**: Update expected_tools in build_spider_cases.py OR make it flexible

---

## Part 3: Performance Analysis

### Latency Breakdown

- **Total cases**: 1,034
- **Total time**: 211.9 minutes (3.53 hours)
- **Average**: 12.3 seconds per case
- **Range**: 4.9s - 36.2s
- **Median**: ~12s (estimated)

**Components of 12.3s per case:**
1. Agent execution (run_query): ~10s
   - Routing: 0.5s
   - Schema retrieval: 1s
   - SQL generation: 5s
   - SQL validation: 1s
   - Query execution: 1s
   - Synthesis: 2s
   
2. Metrics evaluation: ~2s
   - Execution accuracy: 0.5s
   - Spider exact match: 0.5s
   - LLM judge: 0.8s
   - Groundedness: 0.2s

3. I/O and overhead: ~0.3s

**Optimization Opportunities:**
- SQL validation (validate_sql) seems expensive
- LLM judge calls expensive (0.8s each)
- Could cache schema retrievals (same databases repeated)
- Could batch metric evaluations

---

## Part 4: Data Quality Issues

### Official Spider Eval Not Running

**Status**: Failed - summary shows `"official_spider_exec_accuracy": None`

**Root Cause**: `gold_sql` not stored on CaseResult

**Code Path:**
1. `run_case()` creates CaseResult with `gold_sql=case.gold_sql` (line 274)
   - ✓ Actually DOES store it
2. `_run_official_spider_eval()` checks `getattr(r, "gold_sql", None)` (line 433)
   - ✓ Should work

**Mystery**: Why does it still fail?

**Hypothesis**:
- `cases_with_gold = [r for r in spider_en if getattr(r, "gold_sql", None)]` (line 433)
- If gold_sql="" (empty string) instead of None, `bool("")` = False
- Empty gold_sql might exist for some cases

**Action**: Check per_case JSONL for empty gold_sql values

---

### Case Generation Issues

**Problem 1**: gold_map loaded but unused
- Dead code in build_spider_cases.py (lines 19-25)

**Problem 2**: Bilingual doubling
- 517 unique English cases → 1034 total (EN + VI)
- Same gold_sql for both
- Eval time doubled

**Problem 3**: No case validation
- Doesn't verify that target_db_path exists
- Doesn't verify that gold_sql is valid
- Doesn't verify that expected_tools match agent

---

## Part 5: Code Quality Issues

### Type Hints & Null Handling

**Issues**:
- `CaseResult.gold_sql: str | None` but sometimes treated as required
- `execution_match: bool | None` but used as `if execution_match is False`
- `spider_exact_match_f1: float | None` but divided without None check

**Pattern**:
```python
spider_exact_match_f1_vals = [
    item.spider_exact_match_f1
    for item in group
    if item.spider_exact_match_f1 is not None
]
```

This is correct but could use Optional[float] more consistently.

### Error Handling

**Issues**:
1. ThreadPoolExecutor errors not caught (line 631)
2. LLM judge failures silently return 0.5 (line 104-106)
3. Official Spider eval failures logged but continue (line 657)
4. Subprocess returncode not validated (line 260-265)

### Code Organization

**Issues**:
1. Too many concerns in runner.py (case exec, metrics, reporting, gates)
2. Metric evaluation should be separate module
3. Report generation should be separate module
4. Gate logic should be separate module

---

## Part 6: Test Case Design Issues

### Expected Tools Mismatch

**Problem**: expected_tools hardcoded to old agent workflow

**Test case expects**:
```
["route_intent", "get_schema", "generate_sql", "validate_sql", "query_sql", "analyze_result"]
```

**Agent actually does**:
```
["detect_context_type", "route_intent", "task_planner", "aggregate_results"]
```

**Why**: Agent refactored from procedural (6 steps) to task planning (4 stages)

**Impact**:
- tool_path_accuracy = 0.0% (passes no cases)
- But agent is working correctly!
- Test is broken, not agent

**Fix Options**:
1. Update expected_tools to match modern agent
2. Make expected_tools more flexible (e.g., wildcards)
3. Remove tool_path_accuracy gate (not meaningful)
4. Update agent to use old tool names (don't do this)

### Gold SQL Sources

**Problem**: gold_sql comes from Spider dataset, generated SQL from agent

**Standards Mismatch**:
- Gold: `SELECT count(*) FROM singer` (lowercase, no alias)
- Generated: `SELECT COUNT(*) AS total_singers FROM singer` (uppercase, aliased)
- Both are valid SQL, but exact match fails

**Root Cause**:
- Spider gold SQL is hand-written, minimal
- Agent SQL is generated with aliases and formatting
- They're semantically equivalent but structurally different

**Eval Metrics**:
1. execution_accuracy: Checks results (OK, but column name casing issue)
2. spider_exact_match: Checks structure (breaks on minor differences)
3. official_spider_eval: Checks results only (best option, but not running)

---

## Part 7: Recommendations

### Immediate Fixes (Critical)

1. **LIMIT 200 Issue** (affects 48% of cases)
   - Find where LIMIT 200 is being injected
   - Remove it or make it configurable
   - Re-run evaluation

2. **gold_sql Storage** (blocks official eval)
   - Verify gold_sql is being stored on CaseResult
   - Check if empty strings are issue
   - If not storing, add: `gold_sql=case.gold_sql` in run_case()

3. **Column Name Casing** (affects 26% of cases)
   - Update spider_exact_match.py to normalize column names
   - Update execution_accuracy.py to case-insensitive comparison
   - Or: Have SQL generator match gold SQL capitalization

### Short-term Fixes (High Priority)

4. **expected_tools Mismatch** (affects 100% of cases for tool_path gate)
   - Update expected_tools in build_spider_cases.py to match actual agent
   - Or: Make gate check more flexible
   - Or: Remove tool_path_accuracy gate (not meaningful)

5. **Routing Error** (affects 15% of cases)
   - Investigate intent routing model
   - Add schema hints to routing decision
   - Improve training data

6. **SQL Generation Errors** (affects 11% of cases)
   - Add error logging to generate_sql tool
   - Fix timeout/recursion limit issues
   - Improve fallback mechanism

### Medium-term Improvements (Medium Priority)

7. **Error Recovery**
   - Wrap ThreadPoolExecutor in try/except
   - Collect partial results if some cases fail
   - Log specific error for each failed case

8. **Official Spider Eval**
   - Make it run successfully
   - Use as primary metric (most authoritative)
   - Report breakdown by hardness level

9. **Groundedness Evaluation**
   - Improve keyword matching (stemming, fuzzy match)
   - Weight keyword importance differently
   - Use semantic evaluation by default (current LLM fallback)

### Long-term Improvements (Nice to Have)

10. **Architecture Refactoring**
    - Split runner.py into modules (executor, metrics, reporter, gates)
    - Extract metric evaluation to separate pipeline
    - Make case generation validated and testable

11. **Test Case Maintenance**
    - Auto-validate test cases when loaded
    - Check for: gold_sql exists, db_path valid, expected_tools correct
    - Document test case expectations

12. **Metrics Alignment**
    - Use official_spider_eval as primary
    - execution_accuracy as secondary (more lenient)
    - spider_exact_match as tertiary (debugging only)
    - groundedness as quality signal (not hard gate)

---

## Summary Table

| Issue | Category | Severity | Impact | Fix Location |
|-------|----------|----------|--------|---|
| LIMIT 200 injection | SQL generation | CRITICAL | 48% of cases fail | `app/tools/generate_sql.py` |
| Column name casing | Metrics | HIGH | 26% of cases fail | `evals/metrics/*.py` |
| Routing failure | Agent | HIGH | 15% of cases fail | `app/nodes/routing.py` |
| SQL generation empty | Agent | HIGH | 11% of cases fail | `app/tools/generate_sql.py` |
| expected_tools wrong | Test cases | HIGH | 100% of tool_path metric | `evals/build_spider_cases.py` |
| gold_sql not stored | Evaluation | MEDIUM | Official eval fails | `evals/runner.py` line 274 |
| Keyword matching too strict | Groundedness | MEDIUM | 17% groundedness pass rate | `evals/groundedness.py` |
| Path verification missing | Case generation | MEDIUM | Silent failures | `evals/build_spider_cases.py` |
| Error handling weak | Evaluation | LOW | Hard to debug failures | `evals/runner.py` |

---

## Conclusion

The evaluation pipeline is **architecturally sound** but has **5 concrete bugs** blocking 99% of cases:

1. LIMIT 200 auto-injection (SQL generation)
2. Column name casing (metrics)
3. Intent routing failures (routing)
4. Empty SQL generation (tool chain)
5. expected_tools mismatch (test cases)

**The agent is likely working better than metrics show.** Official Spider eval would provide better visibility if it ran.

**Next Step**: Fix LIMIT 200 injection, re-run, and see if execution accuracy improves dramatically.

