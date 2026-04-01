# DA Agent Evaluation Pipeline - Documentation Index

Complete exploration completed April 1, 2026. **3 new analysis documents created** + 2 pre-existing docs.

---

## Navigation Guide

### 📋 START HERE (Pick based on your goal)

| Goal | Document | Read Time | Key Sections |
|------|----------|-----------|--------------|
| **Quick overview of issues** | EVAL_EXPLORATION_SUMMARY.md | 10 min | Critical Issues Summary table |
| **Function lookup/reference** | EVAL_FUNCTIONS_REFERENCE.md | 20 min | Use Ctrl+F to search by function name |
| **Complete technical understanding** | EVAL_PIPELINE_DEEP_DIVE.md | 40 min | All sections in order |
| **Bug investigation** | EVAL_ANALYSIS_DETAILED.md | 30 min | Part 1 and Part 4 (Known Issues) |
| **Quick facts** | EVAL_QUICK_REFERENCE.md | 5 min | One-page bullet points |
| **Summary metrics** | EVAL_ANALYSIS_SUMMARY.md | 15 min | Part 1-2 (Metrics & Categorization) |

---

## Document Descriptions

### 1. **EVAL_PIPELINE_DEEP_DIVE.md** (1,028 lines, 35 KB)
**Most comprehensive reference**

**Contains:**
- High-level architecture diagram
- Complete file-by-file analysis (10 sections)
- Data structures & contracts
- Detailed algorithm explanations
- SQL parsing component breakdown
- Three-layer SQL validation strategy
- Recommended next steps

**Best for:** Understanding every detail of how the pipeline works

**Key sections to jump to:**
- Overview & Architecture (big picture)
- File Analysis (specific implementation)
- Critical Integration Points (how pieces connect)
- Known Issues & Gaps (what's broken)

---

### 2. **EVAL_FUNCTIONS_REFERENCE.md** (679 lines, 19 KB)
**Detailed function manual**

**Contains:**
- Every major function with signature
- Behavior description for each
- Implementation code snippets
- Usage examples
- Known gotchas/edge cases
- Summary comparison table

**Best for:** Understanding specific functions before modifying code

**Organized by file:**
- runner.py (8 functions)
- metrics/execution_accuracy.py (2 functions)
- metrics/spider_exact_match.py (8 functions)
- groundedness.py (4 functions)
- Metric aggregation functions

---

### 3. **EVAL_EXPLORATION_SUMMARY.md** (328 lines, 12 KB)
**Executive summary + roadmap**

**Contains:**
- What was read (10 files, 100% coverage)
- Key findings (10 sections)
- Critical issues table (7 issues with severity)
- What works well (8 strengths)
- Questions for clarification
- Recommended next steps (short/medium/long term)
- File statistics & size breakdown
- How to use these docs

**Best for:** Getting oriented quickly, planning fixes

**Key tables:**
- Critical Issues Summary (severity & impact)
- File Statistics (lines, functions, purpose)

---

### 4. **EVAL_ANALYSIS_DETAILED.md** (921 lines, 30 KB)
**Pre-existing, detailed metrics analysis**

**Contains:**
- 5 major failure categories (with % breakdown)
- Part 1: File-by-file analysis of evaluation metrics
- Part 2: Critical metrics breakdown
- Part 3: Failure categorization
- Part 4: Known issues
- Part 5: Recommendations

**Best for:** Understanding metric calculations and failure modes

---

### 5. **EVAL_ANALYSIS_SUMMARY.md** (415 lines, 12 KB)
**Pre-existing, condensed overview**

**Contains:**
- Executive summary (key numbers)
- Metric definitions
- Failure categories explained
- Recommendations

**Best for:** Quick understanding of current state

---

### 6. **EVAL_QUICK_REFERENCE.md** (65 lines, 2.3 KB)
**Pre-existing, one-page cheat sheet**

**Contains:**
- Bullet-point summary of key concepts
- Quick lookups
- Definition of terms

**Best for:** Quick reminders while coding

---

## File Coverage Map

### Fully Analyzed Files (100% line-by-line review)

```
evals/
├── runner.py (705 lines)
│   └─ 13 functions: _tool_path_ok, _sql_validity, _normalize_rows, 
│                    _execution_match, _failure_bucket, run_case, summarize, 
│                    _run_official_spider_eval, _pass_gate, _render_markdown,
│                    _load_suite_cases, parse_args, main
│   └─ CaseResult dataclass (76 fields)
│
├── case_contracts.py (82 lines)
│   └─ EvalCase dataclass (9 fields)
│   └─ load_cases_jsonl, dump_cases_jsonl
│
├── build_spider_cases.py (121 lines)
│   └─ load_dev_cases, load_test_cases
│
├── groundedness.py (211 lines)
│   └─ evaluate_groundedness, _keyword_groundedness, 
│      _llm_evaluate_groundedness, _keyword_coverage, 
│      _extract_number_claims, _normalize
│   └─ GroundednessResult dataclass
│
├── metrics/
│   ├── execution_accuracy.py (162 lines)
│   │   └─ ExecutionAccuracyEvaluator.evaluate
│   │   └─ _execute_sql, _normalize_result_rows
│   │   └─ ExecutionAccuracyResult dataclass
│   │
│   ├── spider_exact_match.py (443 lines)
│   │   └─ SpiderExactMatchEvaluator.evaluate
│   │   └─ parse_sql_into_components
│   │   └─ 14 helper functions for parsing/comparing
│   │   └─ SQLComponentSet, SpiderExactMatchResult dataclasses
│   │
│   ├── official_spider_eval.py (269 lines)
│   │   └─ OfficialSpiderEvaluator.evaluate_batch
│   │   └─ _parse_stdout
│   │   └─ OfficialSpiderResult, HardnessScore dataclasses
│   │
│   ├── llm_judge.py (123 lines)
│   │   └─ LLMAnswerJudge.evaluate
│   │   └─ _call_llm_judge
│   │   └─ LLMJudgeResult dataclass
│   │
│   └── __init__.py (27 lines)
│       └─ Exports 6 classes
│
└── prompts/
    └── sql.py (99 lines)
        └─ SQL_PROMPT_DEFINITION (chat-based)
        └─ SQL_SELF_CORRECTION_PROMPT_DEFINITION (chat-based)
```

**Total analyzed:** ~2,215 lines of code across 10 files

---

## Critical Issues Quick Reference

### Issue #1: Tool Path Accuracy = 0.0%
- **File:** runner.py, lines 103-105
- **Function:** `_tool_path_ok()`
- **Problem:** Checks if ALL 6 expected tools are in used_tools set; agent doesn't call all 6
- **Impact:** tool_path_accuracy gate (95% threshold) impossible to pass
- **Fix options:** A) Fix tool invocation logic, B) Make expected_tools dynamic, C) Change check to subset validation

### Issue #2: LIMIT 100 Comparison
- **File:** runner.py, lines 117-124
- **Function:** `_normalize_rows()`
- **Problem:** Only compares first 100 rows; hidden assumption
- **Impact:** execution_match false positives when pred has LIMIT different from gold
- **Fix options:** A) Remove limit, B) Compare full sets, C) Add LIMIT to both before comparison

### Issue #3: Empty Expected Keywords for Spider
- **File:** build_spider_cases.py, line 47
- **Problem:** All Spider cases have `expected_keywords = []`
- **Impact:** Groundedness evaluation always passes (vacuous truth); hallucinations not detected
- **Fix options:** A) Define expected_keywords for cases, B) Always use LLM eval for Spider

### Issue #4: Case-Sensitivity in SQL Parsing
- **File:** spider_exact_match.py, lines 140-144
- **Function:** `_normalize_value()`
- **Problem:** Normalizes to lowercase, losing original schema naming conventions
- **Impact:** exact_match fails on `Song_Name` vs `song_name`
- **Fix options:** A) Keep original casing, B) Pre-normalize schema definitions, C) Case-insensitive comparison

### Issue #5: Fragile Official Spider Eval Parsing
- **File:** official_spider_eval.py, lines 55-133
- **Function:** `_parse_stdout()`
- **Problem:** Regex-based parsing of subprocess output; fragile to format changes
- **Impact:** Silent failures if test-suite-sql-eval changes output format
- **Fix options:** A) Use JSON output format, B) Add fallback parsers, C) Better error handling

---

## How to Navigate When Investigating

### "I need to fix the tool path issue"
1. Read: EVAL_FUNCTIONS_REFERENCE.md → `_tool_path_ok()` section
2. Read: EVAL_PIPELINE_DEEP_DIVE.md → `runner.py` section
3. Check: expected_tools definition in build_spider_cases.py
4. Check: How used_tools is populated in app/main.py (not analyzed here)

### "I'm debugging execution match inconsistencies"
1. Read: EVAL_FUNCTIONS_REFERENCE.md → `_normalize_rows()` and `_execution_match()` sections
2. Read: EVAL_PIPELINE_DEEP_DIVE.md → "SQL Parsing & Comparison" section
3. Note: LIMIT 100 comparison is the issue
4. Check: Whether pred SQL has LIMIT and what value

### "I need to understand the failure bucket categorization"
1. Read: EVAL_FUNCTIONS_REFERENCE.md → `_failure_bucket()` section
2. Read: EVAL_ANALYSIS_DETAILED.md → Part 3 (Failure Categorization)
3. Reference: Priority order in EVAL_FUNCTIONS_REFERENCE.md

### "I'm adding new eval metrics"
1. Read: EVAL_PIPELINE_DEEP_DIVE.md → "Evaluation Metrics Pipeline" section
2. Look at: ExecutionAccuracyEvaluator and SpiderExactMatchEvaluator as templates
3. Reference: CaseResult dataclass to see what fields to populate
4. Check: _metric_ratio() function for aggregation pattern

---

## Search Cheat Sheet

Use Ctrl+F in the appropriate document:

| Question | Search Term | Document |
|----------|------------|----------|
| What does `_tool_path_ok` do? | `_tool_path_ok` | EVAL_FUNCTIONS_REFERENCE.md |
| How are rows normalized? | `_normalize_rows` | EVAL_FUNCTIONS_REFERENCE.md |
| What's the LIMIT issue? | `LIMIT 100` | EVAL_EXPLORATION_SUMMARY.md |
| How does Spider parsing work? | `parse_sql_into_components` | EVAL_FUNCTIONS_REFERENCE.md |
| What are the gate thresholds? | `GATE_THRESHOLDS` | EVAL_FUNCTIONS_REFERENCE.md |
| Which functions have gotchas? | `Gotcha:` | EVAL_FUNCTIONS_REFERENCE.md |
| Complete flow of execution? | `Case Execution Flow` | EVAL_PIPELINE_DEEP_DIVE.md |
| All 7 critical issues? | `Critical Issues Summary` | EVAL_EXPLORATION_SUMMARY.md |
| How to improve? | `Recommended Next Steps` | EVAL_EXPLORATION_SUMMARY.md |

---

## Context for Each Document

### When Documents Were Created
- **EVAL_ANALYSIS_DETAILED.md** & **EVAL_ANALYSIS_SUMMARY.md**: Pre-existing (March 31 - April 1)
- **EVAL_PIPELINE_DEEP_DIVE.md**: April 1, 2026 (new, comprehensive)
- **EVAL_FUNCTIONS_REFERENCE.md**: April 1, 2026 (new, function-by-function)
- **EVAL_EXPLORATION_SUMMARY.md**: April 1, 2026 (new, executive summary)

### Complementary Reading Order
1. Start: EVAL_EXPLORATION_SUMMARY.md (5 min orientation)
2. Reference: EVAL_QUICK_REFERENCE.md (when you need quick facts)
3. Deep dive: EVAL_PIPELINE_DEEP_DIVE.md (when you need to understand architecture)
4. Function lookup: EVAL_FUNCTIONS_REFERENCE.md (when you need specifics)
5. Debug reference: EVAL_ANALYSIS_DETAILED.md (when investigating issues)

---

## Statistics

| Document | Lines | Size | Focus | Audience |
|-----------|-------|------|-------|----------|
| EVAL_PIPELINE_DEEP_DIVE.md | 1,028 | 35 KB | Architecture & implementation | Engineers doing deep work |
| EVAL_FUNCTIONS_REFERENCE.md | 679 | 19 KB | Function signatures & behavior | Code reviewers & debuggers |
| EVAL_EXPLORATION_SUMMARY.md | 328 | 12 KB | Overview & issues | Project managers & planners |
| EVAL_ANALYSIS_DETAILED.md | 921 | 30 KB | Metrics breakdown | Performance analysts |
| EVAL_ANALYSIS_SUMMARY.md | 415 | 12 KB | Quick metrics | Dashboard viewers |
| EVAL_QUICK_REFERENCE.md | 65 | 2.3 KB | One-pager | Quick lookup |
| **TOTAL** | **3,436** | **108 KB** | Full coverage | Everyone |

---

## Corrections & Updates

If you find errors or outdated information in these docs:
1. Check when the doc was created (header dates)
2. The code itself is the source of truth
3. Create a new doc for corrections (follow same naming convention)

---

## Contact & Questions

Questions marked in EVAL_EXPLORATION_SUMMARY.md:
- Tool path accuracy = 0.0% — Is this expected?
- Empty expected_keywords — Intentional design?
- LIMIT 100 — How was this chosen?
- Official Spider eval — Currently working?
- Tool path priority — Why lowest?

These are open questions that need clarification from the team.

