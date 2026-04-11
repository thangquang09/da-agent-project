# Prompts Documentation

All LLM prompts are centralized in this folder. Each prompt is defined as a `PromptDefinition` dataclass with templating support for variables.

## Prompt Files

| File | Prompt Name | Purpose |
|------|-------------|---------|
| `router.py` | `ROUTER_PROMPT_DEFINITION` | Classifies user intent into sql/rag/mixed/unknown |
| `sql.py` | `SQL_PROMPT_DEFINITION` | Generates SQL queries from user questions |
| `sql.py` | `SQL_SELF_CORRECTION_PROMPT_DEFINITION` | Self-corrects SQL with error context |
| `sql_worker.py` | `SQL_WORKER_GENERATION_PROMPT` | SQL expert prompt for worker nodes |
| `analysis.py` | `ANALYSIS_PROMPT_DEFINITION` | Analyzes SQL query results |
| `synthesis.py` | `SYNTHESIS_PROMPT_DEFINITION` | Synthesizes natural language from SQL results |
| `context_detection.py` | `CONTEXT_DETECTION_PROMPT_DEFINITION` | Detects context type for RAG retrieval |
| `classifier.py` | `RETRIEVAL_TYPE_CLASSIFIER_PROMPT` | Classifies retrieval type: metric_definition vs business_context |
| `fallback.py` | `FALLBACK_ASSISTANT_PROMPT` | Handles unknown/unclassifiable queries |
| `auto_context.py` | `AUTO_CONTEXT_PROMPT_DEFINITION` | Auto-generates 1-2 sentence business context from schema + sample rows |
| `decomposition.py` | `TASK_DECOMPOSITION_PROMPT` | Decomposes queries into parallelizable sub-tasks |
| `visualization.py` | `VISUALIZATION_CODE_GENERATION_PROMPT` | Generates Python visualization code |
| `report_planner.py` | `REPORT_PLANNER_PROMPT` | Plans domain-aware multi-section report structure with per-section visualization flags |
| `report_data_profiler.py` | `REPORT_DATA_PROFILER_PROMPT_DEFINITION` | Analyzes 100 random sample rows + column stats + business context to produce domain summary and suggested sections |
| `report_insight.py` | `REPORT_INSIGHT_PROMPT` | Writes grounded section insights from chart image + computed stats, preserving grouped-row bindings so counts/rates from different rows are not mixed |
| `report_writer.py` | `REPORT_WRITER_PROMPT` | Synthesizes Executive Summary, section narratives, and Recommendations from grounded insights with domain context |
| `report_critic.py` | `REPORT_CRITIC_PROMPT` | Reviews report for unsupported claims, missing Executive Summary, and weak Recommendations |
| `continuity.py` | `CONTINUITY_DETECTION_PROMPT_DEFINITION` | Detects implicit follow-up queries |
| `evaluation.py` | `GROUNDEDNESS_EVALUATION_PROMPT` | Evaluates answer groundedness |

## Usage

Import via `PromptManager` for automatic variable substitution and Langfuse integration:

```python
from app.prompts import prompt_manager

# Get compiled messages with variables substituted
messages = prompt_manager.router_messages(query="What is DAU?", session_context="")
```

Or import definitions directly for custom handling:

```python
from app.prompts import ROUTER_PROMPT_DEFINITION
```

## Template Syntax

Prompts use `{{variable}}` syntax for variable substitution. Conditional blocks use `{{#if var}}...{{/if}}`.

## Langfuse Integration

`PromptManager` fetches prompts from Langfuse when available, with local fallbacks. Set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` environment variables to enable.

## Report Prompt Roles

Report generation is an 8-node pipeline using LangGraph `Send()` for per-section fan-out:

1. `profiler_sampler` — runs `SELECT * FROM table ORDER BY RANDOM() LIMIT 100` + column stats (min/max/unique/nulls), caps at 2 tables, 15 cols/table. Pure SQL, no LLM. Output: `report_sample_data`.
2. `profiler_analyzer` — LLM reads schema + sample data + business_context to produce domain summary + suggested_sections. Uses `report_data_profiler` prompt with {{sample_data_summary}} and {{business_context}} variables.
3. `report_planner` — uses profiler's `suggested_sections` directly (skip redundant LLM call) or falls back to LLM. Builds `ReportPlan` with `domain_context`.
4. `section_pipeline` (via `Send()` fan-out) — each section runs independently through: SQL worker → sandbox (compute_stats + chart) → insight generation. Single sandbox reused. Results fan-in via `_report_sections_raw` with `operator.add` reducer.
5. `sections_sort` — reassembles sections in original planner order after parallel fan-in.
6. `report_writer` — synthesizes Executive Summary (key findings + critical alerts), section narratives, and Recommendations section. Uses `domain_context` and matches user language.
7. `report_critic` — validates grounding of numeric claims, presence of Executive Summary, that grouped-row numbers are not cross-wired across subgroups, and that Recommendations reference actual findings. Max 2 revisions.
8. `report_finalize` — packages final markdown + section payloads for frontend.
