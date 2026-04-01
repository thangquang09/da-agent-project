# DA Agent Evaluation Pipeline - Function Reference

Quick lookup for key functions, their signatures, behavior, and gotchas.

---

## runner.py

### `_tool_path_ok(expected_tools: list[str], used_tools: list[str]) -> bool`

**Location:** Lines 103-105

**Purpose:** Validate that agent used all expected tools

**Implementation:**
```python
def _tool_path_ok(expected_tools: list[str], used_tools: list[str]) -> bool:
    used = set(used_tools)
    return all(tool in used for tool in expected_tools)
```

**Behavior:**
- Converts `used_tools` to set
- Checks if ALL items in `expected_tools` are in the set
- Order-independent, duplicates ignored

**Usage:** Line 244 in `run_case()`
```python
tool_path_correct=_tool_path_ok(case.expected_tools, used_tools),
```

**Current Status:** ✗ Always returns False (tool_path_accuracy = 0.0%)
- Expected: `["route_intent", "get_schema", "generate_sql", "validate_sql", "query_sql", "analyze_result"]`
- Actual: Subset of expected (agent short-circuits after SQL generation)

**Gotcha:** 
- Doesn't check order
- Doesn't check for unexpected tools
- Doesn't detect if tools called multiple times

---

### `_sql_validity(sql: str, db_path: str | None) -> bool`

**Location:** Lines 108-114

**Purpose:** Check if SQL is syntactically valid

**Implementation:**
```python
def _sql_validity(sql: str, db_path: str | None) -> bool:
    if not sql:
        return False
    if not db_path:
        return False
    result = validate_sql(sql, db_path=Path(db_path))
    return result.is_valid
```

**Behavior:**
- Returns False if SQL empty or db_path not provided
- Calls `app.tools.validate_sql()` with database path
- Returns `.is_valid` property

**Usage:** Line 187-191 in `run_case()`
```python
sql_valid = (
    _sql_validity(generated_sql, case.target_db_path)
    if case.should_have_sql
    else True
)
```

**Gotcha:**
- Returns True if `should_have_sql = False` (vacuous truth)
- Doesn't execute SQL, only validates syntax
- Doesn't check if tables/columns exist in schema

---

### `_normalize_rows(rows: list[dict[str, Any]], limit: int = 100) -> list[tuple]`

**Location:** Lines 117-124

**Purpose:** Normalize query result rows for comparison

**Implementation:**
```python
def _normalize_rows(rows: list[dict[str, Any]], limit: int = 100) -> list[tuple]:
    compact = rows[:limit]  # ⚠️ LIMIT 100
    normalized: list[tuple] = []
    for row in compact:
        items = tuple(sorted((str(k), str(v)) for k, v in row.items()))
        normalized.append(items)
    normalized.sort()
    return normalized
```

**Behavior:**
1. Takes first 100 rows only
2. Converts each row dict to sorted tuple of (key, value) pairs
3. Sorts all tuples (order-independent)

**Usage:** Line 140-142 in `_execution_match()`
```python
return _normalize_rows(gold_result.get("rows", [])) == _normalize_rows(
    pred_result.get("rows", [])
)
```

**Critical Gotcha: LIMIT 100**
- Only compares first 100 rows
- If gold SQL has 500 rows, pred SQL has `LIMIT 200`
- Comparison: first 100 of each → may match (FALSE POSITIVE)
- If pred has `LIMIT 50` and gold has 500
- Comparison: first 50 (pred) vs first 100 (gold, but only 50 rows in pred) → still may match

**Impact on metrics:**
- execution_match may be true even if result sets differ beyond first 100 rows
- spider_exact_match may be false (LIMIT component differs)

---

### `_execution_match(gold_sql: str | None, pred_sql: str, db_path: str | None) -> bool | None`

**Location:** Lines 127-142

**Purpose:** Compare SQL execution results

**Implementation:**
```python
def _execution_match(gold_sql: str | None, pred_sql: str, db_path: str | None) -> bool | None:
    if not gold_sql or not pred_sql or not db_path:
        return None
    try:
        gold_result = query_sql(gold_sql, db_path=Path(db_path))
        pred_result = query_sql(pred_sql, db_path=Path(db_path))
    except Exception:
        return False
    
    if gold_result.get("columns") != pred_result.get("columns"):
        return False
    return _normalize_rows(gold_result.get("rows", [])) == _normalize_rows(
        pred_result.get("rows", [])
    )
```

**Behavior:**
- Returns None if any input missing
- Executes both SQLs against database
- Checks columns match (exact)
- Compares rows (normalized, limited to 100)
- Returns False on any execution error

**Return values:**
- `True`: Rows and columns match (after normalization)
- `False`: Execution error OR results don't match
- `None`: Missing inputs (gold_sql, pred_sql, db_path)

**Gotcha:**
- Any execution error → returns False (not propagated)
- LIMIT 100 normalization → false positives possible
- Column comparison is exact (case-sensitive)

---

### `_failure_bucket(case_result: CaseResult) -> str | None`

**Location:** Lines 145-166

**Purpose:** Categorize failure by priority

**Implementation:**
```python
def _failure_bucket(case_result: CaseResult) -> str | None:
    if not case_result.routing_correct:
        return "ROUTING_ERROR"
    if not case_result.answer_format_valid:
        return "SYNTHESIS_ERROR"
    if case_result.should_have_sql and not case_result.has_sql:
        return "SQL_GENERATION_ERROR"
    if case_result.should_have_sql and case_result.has_sql and not case_result.sql_valid:
        return "SQL_VALIDATION_ERROR"
    if case_result.execution_match is False:
        return "SQL_EXECUTION_ERROR"
    if case_result.spider_exact_match is False:
        return "SQL_COMPONENT_MISMATCH"
    if not case_result.groundedness_pass:
        return "HALLUCINATION_RISK"
    if not case_result.tool_path_correct:
        return "TOOL_PATH_MISMATCH"
    return None
```

**Bucket priority (first match wins):**
1. ROUTING_ERROR (intent mismatch)
2. SYNTHESIS_ERROR (missing answer/evidence/confidence)
3. SQL_GENERATION_ERROR (no SQL when expected)
4. SQL_VALIDATION_ERROR (SQL syntax error)
5. SQL_EXECUTION_ERROR (rows don't match)
6. SQL_COMPONENT_MISMATCH (Spider exact match fails)
7. HALLUCINATION_RISK (groundedness fails)
8. TOOL_PATH_MISMATCH (wrong tools)
9. None (all pass)

**Gotcha:**
- Tool path is last priority (rarely assigned if anything else fails)
- Execution error takes priority over component mismatch
- None means no specific failure identified (but may have low metrics)

---

### `run_case(case: EvalCase, recursion_limit: int) -> CaseResult`

**Location:** Lines 169-278

**Purpose:** Execute single eval case and compute all metrics

**Key steps:**
1. Invoke agent: `payload = run_query(case.query, db_path=case.target_db_path)`
2. Extract from payload: intent, tools, SQL, answer, evidence
3. Validate SQL: `_sql_validity(generated_sql, case.target_db_path)`
4. Run metrics:
   - `SpiderExactMatchEvaluator.evaluate(generated_sql, case.gold_sql, ...)`
   - `ExecutionAccuracyEvaluator.evaluate(generated_sql, case.gold_sql, ...)`
   - `LLMAnswerJudge.evaluate(question, answer, evidence)`
   - `evaluate_groundedness(answer, evidence, expected_keywords)`
5. Categorize: `failure_bucket = _failure_bucket(result)`
6. Return `CaseResult`

**Critical storage:**
- Line 274: `gold_sql=case.gold_sql` (preserves for official eval)
- Line 275: `target_db_path=case.target_db_path` (preserves for db_id extraction)

**Time complexity:** 10-30s per case (includes agent invocation and metric computation)

---

## metrics/execution_accuracy.py

### `_normalize_result_rows(rows: list[dict[str, Any]], limit: int = 100) -> list[tuple]`

**Location:** Lines 27-34

**Purpose:** Normalize result rows for comparison

**Same as runner.py `_normalize_rows()`** — see above

---

### `_execute_sql(sql: str, db_path: Path) -> tuple[list[dict[str, Any]] | None, str | None]`

**Location:** Lines 37-49

**Purpose:** Execute SQL and return rows or error

**Implementation:**
```python
def _execute_sql(sql: str, db_path: Path) -> tuple[list[dict[str, Any]] | None, str | None]:
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(sql)
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows, None
    except Exception as e:
        return None, str(e)
```

**Behavior:**
- Connects to SQLite database
- Executes SQL
- Converts rows to list of dicts
- Returns (rows, error) tuple

**Return values:**
- `(rows: list[dict], None)`: Success
- `(None, error: str)`: Execution error

**Gotcha:**
- Always fetches all rows (no limit in execution)
- Caller applies limit via normalization
- Row order depends on SQL (ORDER BY not guaranteed)

---

### `ExecutionAccuracyEvaluator.evaluate(pred_sql: str, gold_sql: str, db_path: str | Path | None) -> ExecutionAccuracyResult`

**Location:** Lines 52-161

**Purpose:** Compare SQL execution results

**High-level flow:**
1. Validate inputs (both SQLs non-empty, db_path exists)
2. Execute both
3. Compare: columns first, then rows

**Output: ExecutionAccuracyResult**
```python
@dataclass
class ExecutionAccuracyResult:
    execution_match: bool  # Did rows/columns match?
    pred_result: list[dict] | None  # Actual predicted rows
    gold_result: list[dict] | None  # Actual gold rows
    result_comparison: str  # "match", "row_count_mismatch", "column_mismatch", "data_mismatch", ...
    error: str | None  # If execution failed
```

**Possible result_comparison values:**
- `"match"`: Execution match ✓
- `"no_db_path"`, `"db_not_found"`: DB unavailable
- `"no_pred_sql"`, `"no_gold_sql"`: Missing SQL
- `"pred_execution_error"`, `"gold_execution_error"`: SQL failed to execute
- `"row_count_mismatch"`: Different number of rows
- `"column_mismatch"`: Different column names
- `"data_mismatch"`: Rows don't match after normalization

---

## metrics/spider_exact_match.py

### `_tokenize(sql: str) -> list[str]`

**Location:** Lines 67-80

**Purpose:** Break SQL into tokens

**Implementation:**
```python
tokens = re.split(r"(\bSELECT\b|\bFROM\b|\bWHERE\b|...)", sql, flags=re.IGNORECASE)
cleaned = [tok.strip() for tok in tokens if tok.strip()]
return cleaned
```

**Behavior:**
- Removes SQL comments (`--` and `/* */`)
- Splits on SQL keywords (case-insensitive)
- Strips whitespace from each token
- Keeps keywords as separate tokens

**Example:**
```
"SELECT name FROM users WHERE id = 1"
→ ["SELECT", "name", "FROM", "users", "WHERE", "id", "=", "1"]
```

---

### `_split_by_clause(tokens: list[str]) -> dict[str, list[str]]`

**Location:** Lines 83-137

**Purpose:** Group tokens by SQL clause

**Behavior:**
- Starts in "select" clause
- When keyword encountered (SELECT, FROM, WHERE, ...), switch clause
- Accumulate non-keyword tokens into current clause

**Output:**
```python
{
    "select": [...],
    "from": [...],
    "where": [...],
    "group_by": [...],
    "having": [...],
    "order_by": [...],
    "limit": [...],
    "offset": [...],
    "intersect": [...],
    "union": [...],
    "except": [...]
}
```

---

### `_normalize_value(val: str) -> str`

**Location:** Lines 140-144

**Purpose:** Normalize a value string

**Implementation:**
```python
def _normalize_value(val: str) -> str:
    val = val.strip()
    val = re.sub(r"'([^']*)'", r"\1", val)  # Remove single quotes
    val = re.sub(r'"([^"]*)"', r"\1", val)  # Remove double quotes
    return val.lower()
```

**Behavior:**
- Strips whitespace
- Removes quote characters (but keeps content)
- Converts to lowercase

**Example:**
- `"'Song_Name'"` → `song_name`
- `'"Age"'` → `age`
- `"COUNT(*)"` → `count(*)`

---

### `_extract_select_items(items: list[str]) -> frozenset[str]`

**Location:** Lines 147-165

**Purpose:** Extract SELECT clause column/expression items

**Behavior:**
- Iterates tokens, accumulating to current item
- Splits on comma (respecting parentheses depth)
- Normalizes each item
- Returns frozenset (order-independent, no duplicates)

**Example:**
```
items: ["name", ",", "COUNT", "(", "age", ")", "as", "count_age"]
→ frozenset({"name", "count ( age ) as count_age"})
```

---

### `_extract_where_conditions(items: list[str]) -> frozenset[str]`

**Location:** Lines 217-238

**Purpose:** Extract WHERE clause conditions

**Behavior:**
- Splits on AND/OR (at paren depth 0)
- Normalizes each condition
- Returns frozenset

**Normalization in `_normalize_condition()`:**
- Collapses whitespace
- Removes quotes
- Normalizes comparison operators: `1 <= 2` → `2 >= 1`
- Splits condition on operators

**Example:**
```
"age > 20 AND status = 'active'"
→ frozenset({"age > 20", "status = active"})
```

---

### `parse_sql_into_components(sql: str) -> SQLComponentSet`

**Location:** Lines 339-354

**Purpose:** Parse SQL into all 11 components

**Behavior:**
1. Tokenize
2. Split by clause
3. Extract each component type

**Returns:**
```python
@dataclass
class SQLComponentSet:
    select: frozenset[str]
    from_: frozenset[str]
    where: frozenset[str]
    group_by: frozenset[str]
    having: frozenset[str]
    order_by: frozenset[str]
    limit: frozenset[str]
    offset: frozenset[str]
    intersect: frozenset[str]
    union: frozenset[str]
    except_: frozenset[str]
```

---

### `_set_metrics(pred_set: frozenset[str], gold_set: frozenset[str]) -> dict[str, float]`

**Location:** Lines 363-379

**Purpose:** Compute precision/recall/F1 for component sets

**Implementation:**
```python
def _set_metrics(pred_set: frozenset[str], gold_set: frozenset[str]) -> dict[str, float]:
    if not pred_set and not gold_set:
        return {"acc": 1.0, "rec": 1.0, "f1": 1.0}
    if not pred_set or not gold_set:
        return {"acc": 0.0, "rec": 0.0, "f1": 0.0}
    
    tp = len(pred_set & gold_set)  # Intersection
    precision = tp / len(pred_set)
    recall = tp / len(gold_set)
    f1 = 2 * precision * recall / (precision + recall)
    return {"acc": precision, "rec": recall, "f1": f1}
```

**Metrics:**
- `"acc"`: Precision (TP / all predicted)
- `"rec"`: Recall (TP / all gold)
- `"f1"`: Harmonic mean

**Gotcha:** "acc" means precision, not accuracy

---

### `SpiderExactMatchEvaluator.evaluate(pred_sql: str, gold_sql: str, db_path: str | None) -> SpiderExactMatchResult`

**Location:** Lines 398-442

**Purpose:** Component-by-component SQL comparison

**Behavior:**
1. Parse both SQLs into components
2. For each of 11 components, compute precision/recall/F1
3. exact_match = all components identical (pred_set == gold_set)
4. overall_f1 = average of all component F1s

**Returns:**
```python
@dataclass
class SpiderExactMatchResult:
    exact_match: bool  # All components match?
    partial_scores: dict[str, dict[str, float]]  # Component -> {"acc", "rec", "f1"}
    component_breakdown: dict[str, bool]  # Component -> exact match?
    overall_f1: float  # Average of all F1s
```

**Gotcha:**
- exact_match = all 11 components must match exactly
- partial_scores may be high even if exact_match = False
- overall_f1 may be high (e.g., 0.8) but exact_match = False

---

## groundedness.py

### `_normalize(text: str) -> str`

**Location:** Lines 24-25

**Purpose:** Normalize text for keyword matching

**Implementation:**
```python
def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()
```

**Behavior:**
- Collapses whitespace
- Converts to lowercase
- Strips edges

---

### `_keyword_coverage(answer: str, expected_keywords: list[str]) -> tuple[list[str], list[str]]`

**Location:** Lines 32-46

**Purpose:** Check which expected keywords appear in answer

**Returns:**
- `supported_keywords`: Keywords found in answer
- `missing_keywords`: Keywords not found in answer

**Behavior:**
- Normalizes both answer and keywords
- Substring match (keyword must appear in answer)

**Example:**
```
answer: "The average age is 25"
keywords: ["average", "age", "sum"]
→ (["average", "age"], ["sum"])
```

---

### `_keyword_groundedness(answer: str, evidence: list[str], expected_keywords: list[str]) -> GroundednessResult`

**Location:** Lines 166-210

**Purpose:** Fast keyword-based groundedness evaluation

**Behavior:**
1. Check keyword coverage
2. Extract numeric claims from answer and evidence
3. Find unsupported numeric claims
4. Calculate score: keyword_score - claim_penalty
5. Pass if score >= 0.7 AND no unsupported claims

**Score calculation:**
```python
keyword_score = len(supported_keywords) / len(expected_keywords) if expected_keywords else 1.0
claim_penalty = min(0.5, 0.1 * len(unsupported_claims))
score = max(0.0, keyword_score - claim_penalty)
passed = score >= 0.7 and not unsupported_claims
```

**Gotcha:**
- If expected_keywords empty: keyword_score = 1.0 (no penalty for missing keywords)
- Numeric unsupported claims incur 0.1 penalty each (max 0.5)
- Must have zero unsupported claims to pass (even if score >= 0.7)

---

### `evaluate_groundedness(answer: str, evidence: list[str], expected_keywords: list[str], use_llm_fallback: bool = True) -> GroundednessResult`

**Location:** Lines 144-163

**Purpose:** Evaluate groundedness with optional LLM fallback

**Behavior:**
1. Compute keyword-based score
2. If use_llm_fallback and keyword_score < 0.5 and expected_keywords:
   - Call LLM for semantic evaluation
   - If LLM score > keyword score, use LLM result
3. Return keyword or LLM result

**Gotcha:**
- LLM fallback requires BOTH low keyword score AND non-empty expected_keywords
- If expected_keywords empty: keyword score = 1.0, LLM never called
- Spider cases have empty expected_keywords → LLM never fallback → always keyword eval

---

## Metric Calculations

### Metric Aggregation: `_metric_ratio(results: list[CaseResult], attr: str) -> float`

**Location:** Lines 281-286

**Purpose:** Calculate pass rate for a boolean metric

**Implementation:**
```python
def _metric_ratio(results: list[CaseResult], attr: str) -> float:
    if not results:
        return 0.0
    return round(
        sum(1 for item in results if bool(getattr(item, attr))) / len(results), 4
    )
```

**Behavior:**
- Counts True values for attribute
- Divides by total count
- Rounds to 4 decimals

**Example:**
- `_metric_ratio(results, "routing_correct")` → routing_accuracy
- `_metric_ratio(results, "tool_path_correct")` → tool_path_accuracy

---

## Summary

| Function | File | Key Behavior | Critical Issue |
|----------|------|--------------|-----------------|
| `_tool_path_ok()` | runner.py | ALL expected tools present? | Always returns False |
| `_normalize_rows()` | runner.py | Normalize first 100 rows | LIMIT 100 causes false positives |
| `_execution_match()` | runner.py | Compare result sets | Relies on LIMIT 100 normalization |
| `_failure_bucket()` | runner.py | Categorize failure | Tool path lowest priority |
| `_tokenize()` | spider_exact_match.py | Break SQL into tokens | Works well |
| `_split_by_clause()` | spider_exact_match.py | Group by SQL clause | Works well |
| `_normalize_value()` | spider_exact_match.py | Lowercase, unquote | Loses case information |
| `parse_sql_into_components()` | spider_exact_match.py | Parse all components | Case-sensitivity issues |
| `_set_metrics()` | spider_exact_match.py | Calculate F1 | Works well |
| `SpiderExactMatchEvaluator.evaluate()` | spider_exact_match.py | Component comparison | Exact match too strict |
| `_keyword_groundedness()` | groundedness.py | Fast eval | Vacuous for empty keywords |
| `evaluate_groundedness()` | groundedness.py | Keyword + LLM | LLM never called for Spider |

