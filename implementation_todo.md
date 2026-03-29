# Implementation TODO - DA Agent (Week/Day Build Plan)
Date: 2026-03-29

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
- [ ] Manual test 10 SQL queries

## Week 2 - RAG + Mixed + Tracing
### Day 1 - RAG corpus and indexing
- [ ] Create docs: `metric_definitions.md`, `retention_rules.md`, `revenue_caveats.md`, `data_quality_notes.md`
- [ ] Implement chunking + embedding + local vector index
- [ ] Add retriever nodes/tools: `retrieve_metric_definition`, `retrieve_business_context`

### Day 2 - Routing quality and mixed path
- [x] Upgrade `route_intent` prompt to strict enum output (`sql/rag/mixed`)
- [ ] Add conditional edges for `rag` and `mixed`
- [ ] For `mixed`, execute SQL + retrieval then merge at synth node
- [ ] Add fallback when one branch fails but partial answer is possible

### Day 3 - Observability layer
- [ ] Implement trace schema (run-level + node-level)
- [ ] Log: intent, tools used, generated SQL, retries, errors, latency
- [ ] Add failure taxonomy: `ROUTING_ERROR`, `SQL_VALIDATION_ERROR`, etc.
- [ ] Persist traces as JSONL for replay

### Day 4 - Prompt hardening
- [ ] Split prompts by purpose: router, SQL gen, synthesis
- [ ] Add anti-hallucination rules (must cite tool/context, admit missing data)
- [ ] Add structured output parsing + strict validation
- [ ] Add prompt regression examples (good/bad cases)

### Day 5 - UX polish for demo
- [ ] Streamlit tabs: Answer / SQL / Trace / Errors
- [ ] Add latency and confidence badge
- [ ] Add sample queries button set (SQL, RAG, Mixed)
- [ ] Demo dry run and issue list

## Week 3 - Evaluation + MCP minimal server
### Day 1 - Eval dataset
- [ ] Create `evals/cases.json` with 40-60 cases
- [ ] Label fields: expected intent, expected tools, should_have_sql, keywords
- [ ] Split by type: 40% SQL, 30% RAG, 30% Mixed

### Day 2 - Eval runner
- [ ] Build `evals/runner.py` to run batch queries
- [ ] Track metrics: routing accuracy, SQL validity, tool-call correctness, answer format validity, latency
- [ ] Save run artifacts and per-case errors

### Day 3 - Groundedness checks
- [ ] Add groundedness evaluator (keyword/support-based baseline)
- [ ] Mark unsupported claims in final answer
- [ ] Add fail reasons for hallucination patterns
- [ ] Define pass thresholds for local gate

### Day 4 - MCP server (minimal)
- [ ] Expose 3 tools: `get_schema`, `query_sql`, `retrieve_metric_definition`
- [ ] Define explicit input/output/error schemas
- [ ] Add tool-level tests for contract validity
- [ ] Add usage examples for interview walkthrough

### Day 5 - Regression and stabilization
- [ ] Run full eval and compare with baseline metrics
- [ ] Fix top failure buckets by impact
- [ ] Freeze prompts/tool contracts for demo branch
- [ ] Prepare reproducible run commands

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
- [ ] Eval runner produces metric summary + per-case report
- [ ] MCP minimal server responds with valid tool contracts
- [ ] Streamlit demo is stable for interview flow

## Suggested daily cadence (lightweight)
- 30m: plan + define acceptance criteria for the day
- 3-5h: implementation
- 1h: tests/eval checks
- 30m: update `research.md` or changelog with lessons/failures
