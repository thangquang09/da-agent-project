# Eval Pipeline (Dataset-Driven)
Updated: 2026-03-30

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
