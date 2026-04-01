# Evaluation Analysis Documentation Index

**Generated**: 2026-04-01 | **Purpose**: Sprint 1 eval pipeline investigation

## Quick Navigation

This folder contains detailed analysis of the DA Agent evaluation pipeline and identified bugs.

### Key Documents (Read in Order)

1. **[EVAL_ANALYSIS_SUMMARY.md](./EVAL_ANALYSIS_SUMMARY.md)** ⭐ START HERE
   - Executive summary of 5 blocking bugs
   - Performance metrics and failure breakdown
   - Fixes applied in Sprint 1

2. **[EVAL_PIPELINE_DEEP_DIVE.md](./EVAL_PIPELINE_DEEP_DIVE.md)**
   - Technical deep-dive into eval architecture
   - How `ExecutionAccuracyEvaluator` works
   - Case generation and matching logic

3. **[EVAL_FUNCTIONS_REFERENCE.md](./EVAL_FUNCTIONS_REFERENCE.md)**
   - Code-level function reference
   - Method signatures and behaviors
   - Integration points

### Supporting Analysis

- `EVAL_ANALYSIS_DETAILED.md` - Full case-by-case breakdown
- `EVAL_EXPLORATION_SUMMARY.md` - Exploration methodology and findings
- `EVAL_DOCS_INDEX.md` - Original navigation doc
- `EVAL_QUICK_REFERENCE.md` - One-page reference

---

## Sprint 1 Fixes Applied

✅ **Fixed in this session:**

1. **Tool-path accuracy (0% → 100%)**
   - Updated `expected_tools` in case builders to v2 graph names
   - Files: `evals/build_spider_cases.py`, `evals/generate_movielens_cases.py`, `evals/cases/domain_cases.jsonl`

2. **Column name casing (execution mismatch)**
   - Normalized column names to lowercase in comparison logic
   - Files: `evals/runner.py`, `evals/metrics/execution_accuracy.py`

3. **Routing and SQL validity (still WIP)**
   - Addressed memory injection for semantic context lookup
   - Deterministic Qdrant point ID generation

---

## Next Steps (Sprint 2/3)

- Investigate LIMIT 200 injection in SQL generation
- Improve routing accuracy to 90%+ (currently 85%)
- Optimize schema retrieval for SQL generation
- Add sqlglot-based validation for safer SQL parsing

See `docs/thangquang09/implementation_todo.md` for full backlog.
