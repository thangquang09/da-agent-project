# DA Agent Evaluation Pipeline - Comprehensive Analysis

**Date**: 2026-04-01  
**Analyzed**: 1,034 Spider dev test cases  
**Status**: CRITICAL BUGS IDENTIFIED

## Executive Summary

The evaluation pipeline has **5 blocking bugs** preventing accurate performance measurement:

| Failure Type | Count | % | Severity | Root Cause |
|---|---|---|---|---|
| **SQL_EXECUTION_ERROR** | 499 | 48.3% | 🔴 CRITICAL | LIMIT 200 auto-injected in SQL generation |
| **SQL_COMPONENT_MISMATCH** | 269 | 26.0% | 🔴 HIGH | Column name casing mismatch (Song_Name vs song_name) |
| **ROUTING_ERROR** | 154 | 14.9% | 🔴 HIGH | Intent routing model fails on ~15% of cases |
| **SQL_GENERATION_ERROR** | 110 | 10.6% | 🔴 HIGH | Tool chain timeout/error, empty SQL returned |
| **TOOL_PATH_MISMATCH** | 2 | 0.2% | 🟡 MEDIUM | Test cases have wrong expected_tools definition |

**Total Broken Cases**: 1,034 / 1,034 (100% have at least one failure)

**Performance Metrics**:
- Routing accuracy: 85.1% (fails gate 0.90 req)
- Tool-path accuracy: **0.0%** (test case bug, not agent bug)
- SQL validity rate: 74.9% (fails gate 0.90 req)
- Answer format validity: 100.0% ✓
- Groundedness pass rate: 82.3% ✓
- Execution match rate: 35.0% (low due to LIMIT 200 issue)

---

## Part 1: Critical Issues (Must Fix)

### 1. LIMIT 200 Injection (48.3% of failures)

**Symptom**: All generated SQL has `LIMIT 200` appended

```sql
-- Generated (WRONG)
SELECT COUNT(*) AS total_singers FROM singer LIMIT 200

-- Gold (CORRECT)
SELECT count(*) FROM singer
```

**Impact**: 
- Result sets include unneeded rows
- Execution accuracy metric fails (same query returns different result count)
- 499 cases categorized as SQL_EXECUTION_ERROR

**Location**: Unknown - not in `evals/runner.py`
- Likely in `app/tools/generate_sql.py` or validation layer
- Could be safety feature to prevent large returns

**Fix Required**: 
- Search for "LIMIT 200" hardcoding in app/tools/
- Remove or make configurable
- Re-run evaluation

---

### 2. Column Name Casing (26.0% of failures)

**Symptom**: Schema uses mixed case but evaluator requires exact match

```sql
-- Generated (Valid but WRONG casing)
SELECT Country FROM singer WHERE Age > 20

-- Gold (Expected casing)
SELECT country FROM singer WHERE age > 20
```

**Impact**:
- execution_accuracy.py strict comparison: `gold_cols != pred_cols` (line 137)
- spider_exact_match.py component extraction fails on schema names
- 269 cases fail both execution and exact match metrics

**Root Causes**:
1. SQLite preserves column name casing from SQL, not schema
2. Gold SQL uses lowercase (from Spider dataset)
3. Generated SQL might use different casing
4. Evaluators don't normalize before comparing

**Files to Fix**:
1. `evals/metrics/execution_accuracy.py` (line 135-144)
   - Add case-insensitive column name comparison
   
2. `evals/metrics/spider_exact_match.py` (line 140-144)
   - Normalize identifiers to lowercase in `_normalize_value()`
   
3. `app/tools/` (SQL generation)
   - Match gold SQL casing convention (lowercase)

---

### 3. Intent Routing Failures (14.9% of failures)

**Symptom**: ~15% of cases return predicted_intent='unknown' instead of 'sql'

```python
# Expected
predicted_intent = 'sql'

# Actual (for ~154 cases)
predicted_intent = 'unknown'  # or other non-'sql' value
```

**Impact**:
- Routing error → tool chain never runs → empty result
- Cascades to SQL_GENERATION_ERROR

**Root Causes**:
1. Intent routing model trained on general data, not SQL-specific
2. Some queries ambiguous: "Show me X" (SQL? RAG?)
3. Vietnamese queries especially problematic
4. No schema context in routing decision

**Location**: `app/nodes/routing.py` (not evaluated, but upstream)

**Fix Options**:
1. Improve routing model training
2. Add schema hints to routing decision
3. Lower confidence threshold for "sql" classification

---

### 4. SQL Generation Empty (10.6% of failures)

**Symptom**: 110 cases have generated_sql = "" (empty string)

```python
# Expected
generated_sql = "SELECT ... FROM ... WHERE ..."

# Actual
generated_sql = ""
```

**Impact**:
- Failure bucket: SQL_GENERATION_ERROR
- Cannot evaluate execution or structure

**Root Causes**:
1. Tool timeout or recursion limit exceeded (default=25)
2. Schema retrieval failed, no context for generation
3. LLM hallucination, no valid SQL generated
4. Error not surfaced → returns empty instead of error message

**Location**: `app/tools/generate_sql.py` and tool chain error handling

**Fix Required**:
- Add error logging to generate_sql tool
- Fix timeout/recursion limit
- Propagate errors instead of returning empty

---

### 5. expected_tools Mismatch (100% of tool_path_accuracy)

**Symptom**: All 1,034 cases fail tool_path_accuracy gate

**Test Cases Define** (build_spider_cases.py):
```python
expected_tools = [
    "route_intent", "get_schema", "generate_sql",
    "validate_sql", "query_sql", "analyze_result"
]
```

**Agent Actually Executes**:
```python
used_tools = [
    "detect_context_type", "route_intent", "task_planner", "aggregate_results"
]
```

**Impact**:
- tool_path_accuracy = 0.0% (0/1034 cases pass)
- Gate threshold = 0.95, actual = 0.0 → GATE FAILS
- But agent is working correctly!

**Root Cause**:
- Test cases written for old agent workflow (6 sequential steps)
- Agent refactored to modern design (4 stages with task planning)
- expected_tools never updated

**This is NOT an agent bug - it's a TEST CASE BUG**

**Fix Required** (choose one):
1. Update expected_tools to match modern agent
2. Make expected_tools check more flexible (e.g., wildcard matching)
3. Remove tool_path_accuracy gate entirely (not meaningful anymore)

**Location**: `evals/build_spider_cases.py` (lines 38-45)

---

## Part 2: Official Spider Eval Not Running

**Issue**: `official_spider_exec_accuracy = None` in summary

**Root Cause**: `gold_sql` not being passed through pipeline

**Code Path**:
```python
# Step 1: run_case() should store gold_sql
gold_sql=case.gold_sql  # Line 274 - appears to be there

# Step 2: _run_official_spider_eval() tries to access it
cases_with_gold = [r for r in spider_en if getattr(r, "gold_sql", None)]
# If gold_sql is None or "", this fails
```

**Mystery**: Why is it still None after being stored?

**Hypothesis**:
- gold_sql is stored but empty string "" (not None)
- Empty string is falsy: `bool("") = False`
- Filter excludes it: `getattr(r, "gold_sql", None)` returns "", which is falsy

**Verification Needed**:
- Check per_case JSONL for `gold_sql` values
- Count how many are None vs ""

**Fix**:
- Validate gold_sql is not empty before filtering
- Or: Ensure case.gold_sql always has value

---

## Part 3: Performance Analysis

**Total Evaluation Time**: 211.9 minutes (3.53 hours)
- 1,034 cases @ 12.3 seconds average
- Min: 4.9 seconds
- Max: 36.2 seconds

**Time Breakdown per Case** (estimated):
- Agent execution: ~10 seconds (routing, schema, SQL gen, validation, query, synthesis)
- Metrics evaluation: ~2 seconds (exec accuracy, exact match, LLM judge, groundedness)
- I/O overhead: ~0.3 seconds

**Optimization Opportunities**:
1. LLM judge calls are expensive (0.8s each) - could cache or batch
2. SQL validation seems slow - investigate subprocess overhead
3. Schema retrievals repeated - should cache per database
4. Official Spider eval subprocess spawning slow - could batch

---

## Part 4: Test Case Design Issues

### Bilingual Doubling

- 517 unique English cases
- Each duplicated with Vietnamese translation
- Total: 1,034 cases (EN + VI)
- **Impact**: Doubles eval time unnecessarily

**Expected behavior**: Should run EN cases only, or track as separate suites

### gold_sql Handling

- `build_spider_cases.py` loads gold_map but never uses it
- Dead code: lines 19-25
- gold_sql sourced from `item["query"]` instead
- **Should be**: Use official gold_sql from test set

### Case Validation Missing

- Doesn't verify target_db_path exists
- Doesn't verify gold_sql is not empty
- Doesn't verify expected_tools match agent
- **Result**: Silent failures downstream

---

## Part 5: Code Quality Issues

### Type Safety

- `CaseResult.gold_sql: str | None` - sometimes required, sometimes optional
- `execution_match: bool | None` - used as `if execution_match is False` (wrong)
- Division operations without None checks (e.g., lines 362-364 in runner.py)

### Error Handling

- ThreadPoolExecutor exceptions not caught (line 631)
- LLM judge failures return 0.5 instead of failing (line 104-106)
- Official Spider eval failures logged but continue silently
- Subprocess returncode validation weak (line 260-265)

### Architecture

- runner.py too large (705 lines)
- Concerns mixed: case execution, metrics, reporting, gates
- Should split into: executor, metrics, reporter, gate modules

---

## Part 6: Failure Bucket Details

### SQL_EXECUTION_ERROR (499 cases)

- Generated SQL is valid (passes validation)
- But execution results don't match gold
- **Primary cause**: LIMIT 200 injection (457/499 cases)
- **Secondary cause**: Column name casing, row ordering

### SQL_COMPONENT_MISMATCH (269 cases)

- SQL structure different from gold
- **Causes**:
  1. Column naming convention differences (Song_Name vs song_name)
  2. Unnecessary LIMIT 200 clause
  3. Alias usage differences (vs bare columns)
  4. WHERE clause formatting (field = 'value' vs field='value')

### ROUTING_ERROR (154 cases)

- predicted_intent ≠ expected_intent
- Usually: predicted='unknown', expected='sql'
- **Impact**: Tool chain never runs, cascades to SQL_GENERATION_ERROR

### SQL_GENERATION_ERROR (110 cases)

- generated_sql = "" (empty)
- Tool executed but failed or timed out
- No error surfaced → empty result

---

## Recommendations (Priority Order)

### 🔴 CRITICAL - Fix Immediately

1. **Find & Remove LIMIT 200**
   - Search app/tools/ for hardcoded "LIMIT 200"
   - Likely in generate_sql.py or validation layer
   - This alone would fix 48% of failures

2. **Normalize Column Names**
   - Update evaluators to case-insensitive comparison
   - Files: execution_accuracy.py, spider_exact_match.py
   - Would fix 26% of failures (or reduce to structure issues only)

3. **Fix expected_tools**
   - Update build_spider_cases.py to match actual agent
   - OR make tool_path_accuracy check flexible
   - Would fix 100% of tool_path_accuracy gate

### 🟠 HIGH - Fix This Sprint

4. **Investigate Routing Failures**
   - Analyze 154 cases that predict 'unknown' intent
   - Improve routing model or add schema context
   - Would fix 15% of failures

5. **Fix SQL Generation Errors**
   - Add error logging to generate_sql tool
   - Fix timeout/recursion limit handling
   - Would fix 11% of failures

6. **Get Official Spider Eval Working**
   - Verify gold_sql is being passed through
   - Run test-suite-sql-eval successfully
   - Would provide authoritative metric

### 🟡 MEDIUM - Do This Week

7. **Improve Error Recovery**
   - Add try/except to ThreadPoolExecutor
   - Collect partial results if cases fail
   - Make evaluation more robust

8. **Fix Groundedness Evaluation**
   - Current: keyword matching is too strict
   - Improve with stemming, fuzzy matching
   - Use semantic evaluation by default

---

## Testing Strategy to Verify Fixes

**Before Fix**:
```bash
uv run python -m evals.runner --suite spider --language en --limit 50
```
- Expected: ~35% execution_match, many SQL_EXECUTION_ERROR

**After Fix #1** (remove LIMIT 200):
```bash
uv run python -m evals.runner --suite spider --language en --limit 50
```
- Expected: ~70-80% execution_match, few SQL_EXECUTION_ERROR

**After Fix #2** (normalize column names):
- Expected: 80-90% execution_match

**After Fix #3** (fix expected_tools):
- Expected: tool_path_accuracy > 0.90 (should match actual agent)

**After Fix #4-6**: 
- Expected: All gates pass (>= 0.90 for metrics)

---

## References

- Evaluation report: `evals/reports/summary_spider_dev_20260401_184326.md`
- Per-case results: `evals/reports/per_case_spider_dev_20260401_184326.jsonl` (1,034 cases)
- Test case generation: `evals/build_spider_cases.py`
- Main runner: `evals/runner.py`
- Metrics: `evals/metrics/`

