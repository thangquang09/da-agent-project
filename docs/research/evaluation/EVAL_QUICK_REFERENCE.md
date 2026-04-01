# Evaluation Pipeline - Quick Reference Guide

## 📊 Current Status (as of 2026-04-01)

```
Total Cases Analyzed: 1,034 Spider dev cases (517 EN + 517 VI)
Total Broken Cases: 1,034 (100% have ≥1 failure)
Evaluation Time: 211.9 minutes (3.53 hours)
```

## 🔴 5 Critical Bugs (Must Fix)

| # | Issue | Location | Impact | Fix Time |
|---|-------|----------|--------|----------|
| 1 | **LIMIT 200 injection** | `app/tools/` | 48% cases fail execution accuracy | 1 hour |
| 2 | **Column name casing** | `evals/metrics/` | 26% cases fail structure match | 2 hours |
| 3 | **Routing failures** | `app/nodes/routing.py` | 15% cases no SQL generated | 4 hours |
| 4 | **SQL generation empty** | `app/tools/generate_sql.py` | 11% cases fail | 3 hours |
| 5 | **expected_tools wrong** | `evals/build_spider_cases.py` | 100% of tool_path metric fails | 0.5 hours |

## 📈 Metrics Breakdown

| Metric | Current | Gate | Status |
|--------|---------|------|--------|
| routing_accuracy | 85.1% | ≥90% | ❌ FAIL |
| tool_path_accuracy | **0.0%** | ≥95% | ❌ FAIL (test bug) |
| sql_validity_rate | 74.9% | ≥90% | ❌ FAIL |
| answer_format_validity | 100.0% | 100% | ✅ PASS |
| groundedness_pass_rate | 82.3% | ≥70% | ✅ PASS |
| execution_match_rate | 35.0% | n/a | ⚠️ LOW |
| official_spider_eval | None | n/a | ⚠️ BLOCKED |

## 🎯 Fix Priority

### Tier 1: Critical (Immediate)
```bash
# 1. Search for LIMIT 200
grep -r "LIMIT 200" app/tools/

# 2. Fix test case expected_tools
# File: evals/build_spider_cases.py, lines 38-45
expected_tools = [
    "detect_context_type",    # New
    "route_intent",
    "task_planner",           # New
    "aggregate_results"       # New
]

# 3. Add case-insensitive column comparison
# Files:
#   - evals/metrics/execution_accuracy.py (line 135-144)
#   - evals/metrics/spider_exact_match.py (line 140-144)
```

### Tier 2: High (This Sprint)
```bash
# 4. Investigate routing failures
python3 << 'EOF'
import json
with open('evals/reports/per_case_spider_dev_20260401_184326.jsonl') as f:
    cases = [json.loads(line) for line in f]
routing_errors = [c for c in cases if c['failure_bucket'] == 'ROUTING_ERROR']
print(f"Sample routing errors (first 5):")
for c in routing_errors[:5]:
    print(f"  {c['case_id']}: expected={c['expected_intent']}, got={c['predicted_intent']}")
