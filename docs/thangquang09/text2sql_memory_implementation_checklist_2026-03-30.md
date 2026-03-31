# Text2SQL + Memory Implementation Checklist (Concrete)
Date: 2026-03-30

## 1) Technology decisions (what to use)

### Text2SQL core
- Orchestration: `LangGraph` (`StateGraph`, conditional edges, checkpointer).
- LLM calls: existing `LLMClient` with `stream=false`.
- SQL engine: `SQLite` (local-first), optional adapter later.
- SQL validation: deterministic parser/guardrail (`sqlglot` style AST checks + allow-list policy in code).
- Retrieval for schema/examples: local vector index (current retriever path), optional `pgvector` later.
- Observability: `loguru` + JSONL traces in `evals/reports/traces.jsonl`.
- Evaluation: `evals/runner.py` + domain/spider case suites.

### Memory core
- Short-term memory: LangGraph thread state + checkpointer.
- Long-term memory:
  - episodic summaries (session/task outcomes)
  - semantic facts (stable business definitions/preferences)
  - procedural hints (validated workflow constraints)
- Storage approach (v1): local JSON/SQLite store + vector index for semantic retrieval.
- Memory quality control:
  - write-qualification gate
  - RIF scoring (`recency`, `relevance`, `frequency/utility`)
  - soft-delete archive before hard delete.
- Memory retrieval strategy: hybrid
  - vector search for broad semantic recall
  - optional graph relation layer when multi-hop is required.

## 2) Concrete implementation targets (repo mapping)

### Text2SQL modules
- `app/graph/state.py`
  - add strict state fields for SQL artifacts and confidence.
- `app/graph/nodes.py`
  - keep separated nodes: route -> schema -> generate -> validate -> execute -> analyze -> synthesize.
- `app/tools/validate_sql.py`
  - enforce read-only + known table/column checks + row limit policy.
- `app/observability/tracer.py`
  - capture route decision, generated SQL, validation reason, retries, latency.
- `evals/`
  - add metrics: execution validity, tool path correctness, response format validity.

### Memory modules (new/extend)
- `app/graph/state.py`
  - add: `active_constraints`, `episodic_summary`, `semantic_facts`, `uncertainty_flags`, `memory_version`.
- `app/graph/nodes.py`
  - add `memory_retrieve` node before synthesis.
  - add `memory_commit` node after synthesis/tool completion.
- `app/memory/` (new folder)
  - `store.py`: memory read/write API
  - `scoring.py`: RIF scoring + retention policy
  - `schemas.py`: typed memory record models
  - `cleanup.py`: soft-delete + compaction job
- `app/observability/tracer.py`
  - add memory observability: memory footprint, write count, retrieval hit rate, drift flags.
- `evals/`
  - add memory stress suite: contradiction/noise/update-drift cases.

## 3) Build checklist (actionable)

### Phase A: Text2SQL hardening
- [ ] Add strict SQL validator policy in `app/tools/validate_sql.py`.
- [ ] Add retry policy split: transient execution errors vs hard validation errors.
- [ ] Add generated SQL evidence block to final response object.
- [ ] Add eval assertions for route/tool path correctness.
- [ ] Add regression cases for semantic SQL mistakes (query runs but wrong intent).

### Phase B: Memory v1 integration
- [ ] Introduce memory state fields in `app/graph/state.py`.
- [ ] Implement `memory_retrieve` and `memory_commit` nodes.
- [ ] Add write-qualification gate (commit only validated facts/constraints).
- [ ] Implement RIF score and soft-delete archive.
- [ ] Add per-thread memory namespace isolation.

### Phase C: Memory evaluation + operations
- [ ] Add long-horizon eval cases (20-50 turns simulation).
- [ ] Track metrics: hallucination-over-turns, drift-rate, memory-footprint growth.
- [ ] Add memory cleanup command and schedule.
- [ ] Add dashboard/log summary for memory health.
- [ ] Add rollback plan when memory policy causes regression.

## 4) Done criteria (clear pass/fail)

### Text2SQL done
- [ ] Unsafe SQL is blocked deterministically before execution.
- [ ] SQL node path and retries are visible in trace per run.
- [ ] Eval suite reports stable routing + SQL validity on domain/spider subsets.
- [ ] Mixed queries produce grounded answer with explicit evidence.

### Memory done
- [ ] Cross-session recall works for validated facts.
- [ ] No unbounded transcript growth in prompt context.
- [ ] Memory commit path is auditable (who/what/why committed).
- [ ] Drift and hallucination metrics are measurable from eval reports.
- [ ] Memory cleanup does not break critical recall cases.

## 5) Commands to verify quickly
```bash
uv run pytest -q
uv run python -m evals.runner --suite domain
uv run python -m evals.runner --suite spider
uv run python -m app.main "DAU 7 ngày gần đây có giảm không?"
uv run streamlit run streamlit_app.py
```
