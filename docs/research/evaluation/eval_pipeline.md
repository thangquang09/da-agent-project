# Eval Pipeline (Dataset-Driven)
Updated: 2026-03-31

## Goal
Run behavior-first evaluation with real datasets instead of hardcoded default queries.

## Data Inputs
- `data/uci_online_retail/online_retail_II.csv`
- `data/movie_lens/ml-32m/`
- `data/spider_1/spider_data/`

## Build Cases
```powershell
uv run python -m evals.build_cases
```

Outputs:
- `data/warehouse/domain_eval.db`
- `evals/cases/domain_cases.jsonl` (36 cases, bilingual 50/50, split 40/30/30)
- `evals/cases/spider_cases.jsonl` (default 24 cases, bilingual pairs)

## Run Eval
Small-fast full run:
```powershell
uv run python -m evals.runner --suite all
```

Spider-only run:
```powershell
uv run python -m evals.runner --suite spider
```

Spider with official test-suite-sql-eval scoring:
```powershell
uv run python -m evals.runner --suite spider --official-spider-eval
```
**Note:** Official Spider eval requires NLTK data. Run once to download:
```powershell
uv run python -c "import nltk; nltk.download('punkt_tab')"
```

Domain-only run (12 cases, fast):
```powershell
uv run python -m evals.runner --suite domain --limit 12
```

Gate-enforced run:
```powershell
uv run python -m evals.runner --suite all --enforce-gates
```

Enable LLM SQL generation during eval:
```powershell
uv run python -m evals.runner --suite spider --enable-llm-sql-generation
```

## Reports
- `evals/reports/latest_summary.json`
- `evals/reports/latest_summary.md`
- `evals/reports/per_case.jsonl`

## Gate Thresholds
- `routing_accuracy >= 0.90`
- `sql_validity_rate >= 0.90`
- `tool_path_accuracy >= 0.95`
- `answer_format_validity == 1.00`
- `groundedness_pass_rate >= 0.70`

## Latest Results (2026-03-31, LLM-Generalized)
After removing hardcoded logic and making all nodes LLM-driven:
- routing_accuracy: **1.0**
- tool_path_accuracy: **1.0**
- sql_validity_rate: **1.0**
- answer_format_validity: **1.0**
- groundedness_pass_rate: **0.1667** (needs improvement - see `EVAL_FIX_TASK.md`)

## Known Issue: Groundedness
The low groundedness score (~0.17) is due to keyword-based evaluation mismatch, NOT agent quality.
See `docs/research/evaluation/EVAL_FIX_TASK.md` for fix specification.

## Official Spider Evaluation
Implementation: `evals/metrics/official_spider_eval.py`
- Uses official test-suite-sql-eval from taoyds/test-suite-sql-eval
- Provides execution accuracy comparable to Spider leaderboard
- Reports breakdown by hardness: easy/medium/hard/extra/all

**Key differences from custom eval:**
- Only checks execution results (values), not column names
- Allows column permutation (doesn't require exact column name match)
- Uses test suite generation for more robust execution matching
- Scores are comparable with Spider1 leaderboard

**Comparison with legacy eval:**
- `execution_accuracy.py`: Stricter - checks column names, no permutation
- `spider_exact_match.py`: Checks SQL structure with regex tokenizer
- `official_spider_eval.py`: Most aligned with academic benchmark
