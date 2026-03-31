# Implementation TODO - DA Agent (Week/Day Build Plan)
Date: 2026-03-31

## Recent Updates (2026-03-31)
### Context Filtering & Dataset Context System
- **Phase 1** (COMMITTED): State & Flow updates for context filtering
  - Add ContextType literal: `user_provided | csv_auto | mixed | default`
  - Add `detect_context_type` node to graph (START → detect_context_type → route_intent)
  - Add GraphInputState fields for context input
  - Update SQL prompt to include semantic context template

- **Phase 2** (COMMITTED): LLM-driven context detection
  - Replace rule-based `_detect_context_type` with LLM-driven version
  - Add ContextMemoryStore for SQLite persistence
  - Add `needs_semantic_context` and `detected_intent` fields to state

- **Phase 3** (COMMITTED): CSV tools and MCP integration
  - Add `validate_csv`: File size, encoding, delimiter detection, column sanitization
  - Add `profile_csv`: Pandas-based profiling with type inference
  - Add `auto_register_csv`: Full pipeline (validate → profile → CREATE TABLE → INSERT)
  - Add `context_resolver`: Conflict resolution between user and dataset context
  - Expose `validate_csv`, `profile_csv`, `auto_register_csv` as MCP tools

- **Phase 4** (COMPLETED 2026-03-31): Eval metrics and Streamlit UI
  - Add `expected_context_type` field to EvalCase dataclass
  - Add `predicted_context_type`, `context_type_correct` fields to CaseResult
  - Add `context_type_accuracy` metric to eval summary
  - Add Streamlit UI for semantic context input and CSV file upload
  - Display context_type in result metrics

- **Phase 5** (COMPLETED 2026-03-31): CSV upload and processing pipeline
  - Add `uploaded_file_data` field to GraphInputState and AgentState
  - Create `process_uploaded_files` node to validate, profile, and auto-register CSVs
  - Update graph flow: detect_context_type → process_uploaded_files (if files) → route_intent
  - Update Streamlit to pass file bytes to the graph
  - CSVs are now auto-registered into SQLite for querying

### Remaining Work
- **Integration tests for CSV tools**: Test full CSV auto-register pipeline end-to-end
- **Eval cases with context_type**: Update existing eval cases to include expected_context_type

## Research links
- Text-to-SQL deep research (NotebookLM, 2026-03-30):
  - `docs/research/notes/text_to_sql_research_2026-03-30.md`
- AI Agent Memory deep research (NotebookLM, 2026-03-30):
  - `docs/research/notes/agent_memory_research_2026-03-30.md`
- Prompt hardening checklist (Langfuse + NotebookLM, 2026-03-30):
  - `docs/research/notes/prompt_hardening_2026-03-30.md`

## Execution checklist (concrete)
- Main checklist doc (technology + module mapping + done criteria):
  - `docs/thangquang09/text2sql_memory_implementation_checklist_2026-03-30.md`
- Priority execution order:
  1. Text2SQL hardening (`validate_sql`, retry policy, eval assertions)
  2. Memory v1 integration (`memory_retrieve`, `memory_commit`, write gate)
  3. Memory evaluation (`drift/hallucination/footprint`) + cleanup operations

## Goal
Build a portfolio-ready DA Agent with:
- LangGraph routing: `sql | rag | mixed`
- Local-first stack: SQLite + markdown docs + Streamlit
- Deterministic SQL safety + analysis
- Observability + evaluation loop
- Minimal MCP server for interview demo

## Working assumptions
- API endpoint: from `curl_command.txt`
- `LLM_API_KEY` loaded from `.env`
- Chat completion requests must always set `stream=false`
- Default model routing:
  - fast/control tasks: `gh/gpt-4o-mini`
  - synthesis/hard cases: `gh/gpt-4o`

## Week 1 - Core Agent Skeleton (SQL-first MVP)
### Day 1 - Project setup + contracts
- [x] Create base folders (`app/graph`, `app/tools`, `app/observability`, `data/warehouse`, `evals`)
- [x] Add config loader (`.env`, model mapping, endpoint config)
- [x] Implement `LLMClient` wrapper (hard enforce `stream=false`)
- [x] Define `AgentState` + input/output schema
- [x] Add run config contract (`thread_id`, `run_id`, `recursion_limit`)

### Day 2 - SQL data foundation
- [x] Create SQLite DB + seed script for `daily_metrics`, `videos`, `metric_definitions`
- [x] Add lightweight schema metadata helper
- [x] Add SQL execution adapter (`query_sql`) with timing and row count
- [x] Add SQL safety validator (`SELECT` only, disallow write DDL/DML)

### Day 3 - LangGraph flow v1 (SQL)
- [x] Implement nodes: `route_intent`, `get_schema`, `generate_sql`, `validate_sql`, `execute_sql`, `analyze_result`, `synthesize_answer`
- [x] Wire graph edges for `sql` path end-to-end
- [x] Add step guard with `recursion_limit`
- [x] Add fail-fast handling for unsafe SQL

### Day 4 - Retry + deterministic analysis
- [x] Add retry policy per node (transient DB/tool errors only)
- [x] Implement deterministic `analyze_result` for trend/top-k/compare
- [x] Add answer object shape: `answer`, `evidence`, `confidence`, `used_tools`, `generated_sql`
- [x] Add basic CLI entrypoint for smoke testing

### Day 5 - Streamlit basic UI
- [x] Build simple chat UI + run button
- [x] Display final answer and generated SQL
- [x] Add debug panel: routed intent, tool history, node latency summary
- [x] Manual test 10 SQL queries

## Week 2 - RAG + Mixed + Tracing
### Day 1 - RAG corpus and indexing
- [x] Create docs: `docs/research/rag/metric_definitions.md`, `docs/research/rag/retention_rules.md`, `docs/research/rag/revenue_caveats.md`, `docs/research/rag/data_quality_notes.md`
- [x] Implement chunking + embedding + local vector index
- [x] Add retriever nodes/tools: `retrieve_metric_definition`, `retrieve_business_context`

### Day 2 - Routing quality and mixed path
- [x] Upgrade `route_intent` prompt to strict enum output (`sql/rag/mixed`)
- [x] Add conditional edges for `rag` and `mixed`
- [x] For `mixed`, execute SQL + retrieval then merge at synth node
- [x] Add fallback when one branch fails but partial answer is possible
- [x] Fix regression: fallback Vietnamese diacritics + RAG retriever selection + mixed empty-SQL success classification
- [x] WSL migration check: verified UTF-8 with `uv` and normalized Vietnamese text (docs/tests/evals) to accented form

### Day 3 - Observability layer
- [x] Implement trace schema (run-level + node-level)
- [x] Log: intent, tools used, generated SQL, retries, errors, latency
- [x] Add failure taxonomy: `ROUTING_ERROR`, `SQL_VALIDATION_ERROR`, etc.
- [x] Persist traces as JSONL for replay

### Day 4 - Prompt hardening
- [x] Split prompts by purpose: router, SQL gen, synthesis (migrated to `PromptManager`)
- [x] Add anti-hallucination rules (router now insists on structured JSON, SQL prompt enforces read-only and schema grounding, fallback defined for Langfuse)
- [x] Add structured output parsing + strict validation (router output JSON still enforced; fallback prevents invalid strings)
- [x] Add prompt regression examples (good/bad cases)? (Doc links + NotebookLM checklist describe expected behavior)

### Day 5 - UX polish for demo
- [x] Streamlit tabs: Answer / SQL / Trace / Errors
- [x] Add latency and confidence badge
- [x] Add sample queries button set (SQL, RAG, Mixed)
- [x] Demo dry run and issue list

## Week 3 - Evaluation + MCP minimal server
### Day 1 - Eval dataset
- [x] Build dataset-driven eval generator `evals/build_cases.py`
- [x] Create case contracts + files: `evals/cases/domain_cases.jsonl`, `evals/cases/spider_cases.jsonl`
- [x] Domain split generated as 40% SQL, 30% RAG, 30% Mixed (bilingual 50/50)

### Day 2 - Eval runner
- [x] Build `evals/runner.py` to run batch queries
- [x] Track metrics: routing accuracy, SQL validity, tool-call correctness, answer format validity, latency
- [x] Save run artifacts and per-case errors (`evals/reports/latest_summary.{json,md}`, `evals/reports/per_case.jsonl`)

### Day 3 - Groundedness checks
- [x] Add groundedness evaluator (keyword/support-based baseline)
- [x] Mark unsupported claims in final answer
- [x] Add fail reasons for hallucination patterns
- [x] Define pass thresholds for local gate

### Day 4 - MCP server (minimal)
- [x] Expose 3 tools: `get_schema`, `query_sql`, `retrieve_metric_definition`
- [x] Define explicit input/output/error schemas
- [ ] Add tool-level tests for contract validity (pending dedicated MCP contract tests)
- [x] Add usage examples for interview walkthrough
- [x] Extended tooling with `dataset_context` (schema stats + samples) to support SQL generation context.
- [x] Fixed MCP runtime integration bug (2026-03-30):
  - corrected SDK import to `mcp.server.fastmcp.FastMCP`
  - added stdio transport option for client/server compatibility
  - routed per-case `target_db_path` through MCP tools so evals can run on domain + spider DBs

### Day 5 - Regression and stabilization
- [x] Run full eval and compare with baseline metrics (MCP-enabled run executed 2026-03-30)
- [ ] Fix top failure buckets by impact
- [ ] Freeze prompts/tool contracts for demo branch
- [ ] Prepare reproducible run commands

#### Latest MCP-enabled eval snapshot (2026-03-30)
- Command: `ENABLE_MCP_TOOL_CLIENT=1 uv run python -m evals.runner`
- Report:
  - `evals/reports/latest_summary.json`
  - `evals/reports/latest_summary.md`
  - `evals/reports/per_case.jsonl`
- Metrics:
  - routing_accuracy: `0.9545`
  - tool_path_accuracy: `0.8182`
  - sql_validity_rate: `0.8409`
  - groundedness_pass_rate: `0.1818`
- Gate status: failed (`sql_validity_rate`, `tool_path_accuracy`, `groundedness_pass_rate`)

#### MCP runtime optimization update (2026-03-30, same day)
- Problem: stdio MCP client spawned a new server process per tool call, causing large latency inflation.
- Fix:
  - Added persistent MCP mode via `MCP_TRANSPORT=streamable-http`.
  - Added auto-start long-lived MCP HTTP server in `app/tools/mcp_client.py`.
  - Reused MCP endpoint for subsequent tool calls (no per-call server spawn).
- New eval command:
  - `ENABLE_MCP_TOOL_CLIENT=1 MCP_TRANSPORT=streamable-http uv run python -m evals.runner`
- Latest metrics after optimization:
  - routing_accuracy: `0.9773`
  - tool_path_accuracy: `0.8636`
  - sql_validity_rate: `0.8864`
  - groundedness_pass_rate: `0.2045`
  - avg_latency_ms: `4400.65` (significantly lower than previous MCP stdio run)

## Evaluation System Enhancement (2026-03-31)
### New Folder Structure
```
evals/
├── cases/
│   ├── dev/                    # Development set
│   │   ├── spider_dev.jsonl    # ~200 cases (sampled from 1,034)
│   │   └── movielens_dev.jsonl # ~8 cases (auto-generated)
│   └── test/                   # Test set
│       ├── spider_test.jsonl   # Full 1,034 cases (EN+VI = 2,068)
│       └── movielens_test.jsonl# ~15 cases (auto-generated)
├── metrics/
│   ├── spider_exact_match.py   # Exact Set Match (SQL component comparison)
│   ├── execution_accuracy.py    # Execute & compare SQL results
│   └── llm_judge.py           # LLM-as-a-judge for answer quality
└── runner.py                   # Updated with new metrics
```

### Implementation Status
- [x] Created `evals/metrics/spider_exact_match.py` - SQL component set comparison
- [x] Created `evals/metrics/execution_accuracy.py` - Execution-based result comparison
- [x] Created `evals/metrics/llm_judge.py` - LLM answer quality evaluation
- [x] Created `evals/metrics/__init__.py` with exports
- [x] Created `evals/build_spider_cases.py` for Spider dataset splitting
- [x] Created `evals/generate_movielens_cases.py` for auto-generating MovieLens cases
- [x] Updated `evals/cases/domain_cases.jsonl` with gold_sql for all SQL/mixed cases
- [x] Updated `evals/runner.py` with new metrics integration

### New Metrics Added to Runner
- `spider_exact_match`: SQL component-level comparison (SELECT, FROM, WHERE, etc.)
- `spider_exact_match_f1`: F1 score for SQL component matching
- `answer_quality_score`: LLM-as-judge evaluation of answer completeness/groundedness/clarity
- `answer_quality_reasoning`: Reasoning from LLM judge

### Usage
```bash
# Run Spider dev set (default: 4 parallel workers)
uv run python -m evals.runner --suite spider --split dev

# Run Spider test set with 8 workers
uv run python -m evals.runner --suite spider --split test --workers 8

# Run all suites with custom tag
uv run python -m evals.runner --suite all --split dev --tag baseline

# Run limited sample for quick testing
uv run python -m evals.runner --suite spider --split dev --limit 10 --workers 4
```

### Output Files
- Timestamped files: `summary_{suite}_{split}_{timestamp}.json/md`
- `latest_summary.{json,md}` - always points to most recent run
- `per_case_{suite}_{split}_{timestamp}.jsonl` - per-case details

### Parallel Processing
- Uses `ThreadPoolExecutor` with configurable `--workers` (default: 4)
- Significant speedup for I/O-bound LLM calls
- Case results are collected and written after all workers complete

## Generalization Sprint (2026-03-31)
### Changes Made
- [x] Removed `_fallback_route_intent()` hardcoded keyword matching - now fully LLM-driven
- [x] Removed `_rule_based_sql()` hardcoded SQL patterns - now fully LLM-driven
- [x] Added `_llm_decide_retrieval_type()` for RAG retrieval type selection (metric_definition vs business_context)
- [x] Added `_llm_synthesize_fallback()` for unknown intent handling
- [x] Updated unit tests to reflect LLM-based behavior

### Latest Eval Results (2026-03-31, domain, 12 cases)
- routing_accuracy: **1.0** (100%)
- tool_path_accuracy: **1.0** (100%)
- sql_validity_rate: **1.0** (100%)
- answer_format_validity: **1.0** (100%)
- groundedness_pass_rate: **0.1667** (low - separate issue)
- avg_latency_ms: **7724.81**

### Known Issue: Groundedness Score
- **Problem**: LLM-generated answers don't contain expected keywords from eval case `expected_keywords` field
- **Root Cause**: The `groundedness` evaluator checks if answer contains `expected_keywords`, but LLM synthesis doesn't explicitly include those keywords
- **This is SEPARATE from the generalization work** - the system is architecturally sound, just needs prompt/content improvement
- **Next Step**: See `docs/research/evaluation/EVAL_FIX_TASK.md` for detailed task specification

## Week 4 - Interview Packaging (optional but recommended)
### Day 1
- [ ] Write architecture README with graph diagram and routing explanation
- [ ] Add trade-offs and known limitations

### Day 2
- [ ] Create demo script (3 scenarios: SQL, RAG, Mixed)
- [ ] Add failure-recovery demo (bad SQL -> validate -> retry/fail clearly)

### Day 3
- [ ] Add metrics snapshot from latest eval run
- [ ] Add trace screenshots/log snippets

### Day 4
- [ ] Final cleanup: naming, comments, docs consistency
- [ ] Dependency pinning + one-command startup

### Day 5
- [ ] Mock interview run: explain architecture, failures, and iterations
- [ ] Final backlog for v2 (cloud warehouse adapter, stronger judge eval, auth)

## Definition of Done (release gate)
- [ ] End-to-end works for `sql`, `rag`, `mixed`
- [ ] SQL safety validation enforced before execution
- [ ] Trace logs available per run and per node
- [x] Eval runner produces metric summary + per-case report
- [ ] MCP minimal server responds with valid tool contracts
- [ ] Streamlit demo is stable for interview flow

## Suggested daily cadence (lightweight)
- 30m: plan + define acceptance criteria for the day
- 3-5h: implementation
- 1h: tests/eval checks
- 30m: update `docs/research/notes/research_notes_2026-03-29.md` or changelog with lessons/failures

