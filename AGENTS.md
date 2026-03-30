# AGENTS.md

Luôn update documents sau khi implement hoàn toàn một tính năng gì đó để cho tôi có thể theo dõi được tiến độ.

## Project
DA Agent Lab

A LangGraph-based Data Analyst Agent focused on answering business/data questions through a combination of SQL tools, retrieval over business docs, deterministic analysis, and strong observability.

This document is for coding agents working in this repository. Treat it as the source of truth for architecture, scope, constraints, and implementation priorities.

---

## Why this project exists
This project is meant to be a **realistic applied AI portfolio project** aligned with an AI/Agent Engineer role.

The goal is **not** to build a toy chatbot.
The goal is to build an **agentic analytics system** that can:

1. understand user questions about metrics / KPIs / trends,
2. decide whether it needs SQL, documentation retrieval, or both,
3. use tools in a controlled way,
4. produce grounded answers,
5. expose traces, logs, and eval results so the system can be debugged and discussed in interviews.

---

## Job-fit intent
This project is intentionally designed to map to the job requirements described in `JD.txt`, especially:

- AI application prototyping
- tool-calling agents
- RAG pipelines
- prompt design and optimization
- MCP-style tool surfaces
- SQL/data infrastructure support
- evaluation and iteration
- debugging agent failures via logs and traces

When making implementation decisions, prefer choices that make the project easier to explain in terms of:

- agent behavior
- system design
- evaluation
- observability
- trade-offs

---

## Core product idea
Build an **AI Data Analyst Agent** that answers questions such as:

- "DAU 7 ngày gần đây có giảm không?"
- "Retention D1 là gì?"
- "Top 5 video có retention cao nhất tuần này"
- "Revenue giảm từ ngày nào và có thể do đâu?"
- "Giải thích metric này và so sánh 2 tuần gần nhất"

This system should support three main classes of questions:

1. **SQL questions**
   - direct metric lookup
   - aggregations
   - comparisons
   - top-k / trend questions

2. **RAG / business-context questions**
   - metric definitions
   - caveats
   - business rules
   - known data quality notes

3. **Mixed questions**
   - require both structured data and retrieved business context

This distinction is important. It is one of the main ways this project demonstrates an actual agentic routing pattern.

---

## Non-goals
Do **not** optimize for the following in early versions:

- polished enterprise UI
- multi-tenant auth
- full production infra
- large-scale deployment
- premature multi-agent complexity
- over-engineered microservices

This repository should prioritize:

- clarity
- correctness
- explainability
- traceability
- evaluation

---

## Architectural philosophy
The project should be built as a **constrained agent**, not an unconstrained autonomous system.

Important principle:

> Most useful production agents are controlled planners with explicit tools, deterministic execution layers, and observable traces.

So:

- LLM decides what to do next.
- Tools do the real work.
- Deterministic code handles analytics where possible.
- State captures the current run.
- Logging and eval are first-class.

Do not let the model freely invent actions outside the defined tool surfaces.

---

## High-level architecture

```text
User / CLI / Streamlit
        |
        v
   LangGraph App
        |
        v
   Router / Supervisor Node
   /         |          \
  /          |           \
SQL Path    RAG Path    Mixed Path
  |           |            |
  v           v            v
Schema      Retrieve     Retrieve + Schema
SQL Gen     Context      SQL Gen
Validate                  Validate
Execute                   Execute
Analyze                   Analyze
   \          |           /
    \         |          /
       Final Synthesizer
              |
              v
      Trace + Eval Logging
```

---

## LangGraph requirement
Use **LangGraph** as the orchestration layer.

Why:

- explicit state
- explicit node transitions
- support for routing
- retry / loop control
- easier debugging
- easier to discuss workflow vs agent trade-offs

This repository should make it easy to inspect:

- what node ran,
- why it ran,
- what inputs it saw,
- what outputs it produced,
- where failures occurred.

---

## Recommended implementation phases

### Phase 1: minimal working agent
Build the smallest usable version with:

- routing
- schema retrieval
- SQL generation
- SQL validation
- SQL execution
- answer synthesis

No need for advanced UI.
CLI is enough.

### Phase 2: add RAG
Add:

- metric definition retrieval
- business context retrieval
- mixed question handling

### Phase 3: add observability
Add:

- run traces
- structured logs
- node-level metadata
- SQL history
- error taxonomy

### Phase 4: add evaluation
Add:

- eval dataset
- eval runner
- task success metrics
- tool usage metrics
- regression tracking

### Phase 5: optional MCP exposure
Expose a subset of tools through an MCP-compatible server surface.

---

## State model
Define a central `AgentState` for LangGraph.

Suggested fields:

```python
{
  "user_query": str,
  "intent": str,                 # sql | rag | mixed
  "messages": list,
  "schema_context": str,
  "retrieved_context": list,
  "generated_sql": str,
  "validated_sql": str,
  "sql_result": dict,
  "analysis_result": dict,
  "final_answer": str,
  "tool_history": list,
  "errors": list,
  "step_count": int,
  "confidence": str,
  "run_id": str,
}
```

Guidelines:

- Keep the state explicit and debuggable.
- Do not hide critical intermediate values.
- Prefer structured fields over raw strings when useful.
- Preserve enough context for tracing and eval.

---

## Node design
Coding agents should implement nodes as small, testable units.

### 1. `route_intent`
Purpose:
- classify the query into `sql`, `rag`, or `mixed`

This is a key node for evaluation.
Routing errors should be observable.

### 2. `get_schema`
Purpose:
- retrieve DB schema context relevant to the user query

Should return:
- tables
- columns
- short descriptions where available

### 3. `retrieve_context`
Purpose:
- retrieve business documentation / KPI definitions / caveats from local docs or vector store

### 4. `generate_sql`
Purpose:
- generate a read-only SQL query for the question

Constraints:
- `SELECT` only
- no write operations
- output must be structured and traceable

### 5. `validate_sql`
Purpose:
- enforce safety and catch obvious errors before execution

Checks may include:
- only read-only statements
- table/column validity
- syntax sanity
- row-limit protections where relevant

### 6. `execute_sql`
Purpose:
- run the validated query against the local warehouse

### 7. `analyze_result`
Purpose:
- perform deterministic post-processing and analysis of result data

Examples:
- trend detection
- top-k extraction
- simple comparison
- anomaly checks

Prefer deterministic Python for this layer where possible.
Do not offload everything to the LLM.

### 8. `synthesize_answer`
Purpose:
- combine SQL results, retrieved context, and deterministic analysis into the final answer

The answer should be:
- concise
- grounded
- honest about uncertainty
- explicit when data is missing or ambiguous

### 9. `record_trace`
Purpose:
- persist run metadata, tool history, SQL, errors, and latency info

---

## Routing behavior
Routing logic should roughly follow this pattern:

- If the query asks for values, rankings, trends, or comparisons from data -> `sql`
- If the query asks for meaning, definition, business rule, or caveat -> `rag`
- If it asks for both -> `mixed`

Examples:

- "DAU hôm qua là bao nhiêu?" -> `sql`
- "Retention D1 là gì?" -> `rag`
- "Retention tuần này giảm từ ngày nào và metric này tính ra sao?" -> `mixed`

Routing is part of the system's intelligence and must be measurable.

---

## Tools design
Tools should be implemented with **MCP-compatible thinking**, even if the first version uses local Python tools.

That means each tool should have:

- clear name
- clear description
- input schema
- output schema
- error schema

At minimum, implement the following tools:

- `get_schema`
- `query_sql`
- `validate_sql`
- `retrieve_metric_definition`
- `retrieve_business_context`
- `analyze_trend`

Possible optional tools:

- `generate_chart_spec`
- `explain_result`
- `list_tables`
- `preview_table`

Important:
- Tool contracts must be explicit.
- Tools should be reusable independently of the graph.
- Keep business logic in tools, not buried inside prompts.

---

## MCP guidance
The JD references MCP, so this project should be **MCP-aware**.

However, the project does **not** need to start with a full MCP server.

Recommended approach:

1. Build tools locally with clean schemas.
2. Keep them MCP-compatible by design.
3. Optionally expose selected tools later through an MCP server layer.

Good candidate MCP-exposed tools:

- `query_sql`
- `get_schema`
- `retrieve_metric_definition`

If building an MCP server, place it in a separate adapter layer instead of mixing protocol logic with core business logic.

---

## Data strategy
The project needs realistic data.

Recommended approach:

### Preferred data style
Use a **small analytics warehouse** with realistic business-style questions.

Possible sources:

1. public e-commerce datasets
2. analytics sample datasets
3. local synthetic warehouse tables derived from public data

### Suggested warehouse tables
At minimum, support tables like:

#### `daily_metrics`
- date
- dau
- revenue
- retention_d1
- avg_session_time

#### `videos`
- video_id
- title
- publish_date
- views
- watch_time
- retention_rate
- ctr

#### `campaigns` (optional)
- campaign_id
- date
- spend
- impressions
- clicks
- installs
- revenue

#### `metric_definitions`
- metric_name
- definition
- caveat
- business_note

This can be stored in SQLite for simplicity.

### Docs for RAG
Also maintain a small business documentation layer in markdown files:

- `docs/research/rag/metric_definitions.md`
- `docs/research/rag/retention_rules.md`
- `docs/research/rag/revenue_caveats.md`
- `docs/research/rag/data_quality_notes.md`

These docs are used to support grounded business answers.

---

## Data constraints
Coding agents should preserve the following constraints:

- keep setup simple
- avoid requiring expensive infra by default
- prefer SQLite or other easy local options first
- if adding BigQuery or cloud backends, make them optional adapters

The repository should run locally for demos.

---

## Output design
The final answer should not just be prose.
It should be structured enough to debug and evaluate.

Suggested final response object:

```json
{
  "answer": "...",
  "evidence": ["..."],
  "confidence": "high|medium|low",
  "used_tools": ["..."],
  "generated_sql": "..."
}
```

A user-facing formatter can render this into markdown.

---

## Observability requirements
Observability is a first-class feature.

Every run should ideally capture:

### Run-level fields
- run_id
- timestamp
- original query
- routed intent
- total steps
- total latency
- total token usage (if available)
- final status

### Node-level fields
- node_name
- start_time
- end_time
- latency_ms
- summarized input
- summarized output
- error if any

### Agent-specific fields
- generated SQL
- validation result
- retrieved docs/chunks
- retry count
- fallback used or not
- final confidence

The goal is to make runs explainable and debuggable.

---

## Failure taxonomy
Maintain a consistent failure taxonomy.

Suggested categories:

- `ROUTING_ERROR`
- `SQL_GENERATION_ERROR`
- `SQL_VALIDATION_ERROR`
- `SQL_EXECUTION_ERROR`
- `EMPTY_RESULT`
- `RAG_RETRIEVAL_ERROR`
- `RAG_IRRELEVANT_CONTEXT`
- `SYNTHESIS_ERROR`
- `STEP_LIMIT_REACHED`

All major failures should be logged using one of these categories.

---

## Evaluation requirements
The project is not complete unless it has an evaluation layer.

At minimum, create an `evals/` directory with:

- test cases
- runner
- metrics summary

Each eval case should ideally contain:

```json
{
  "id": "case_001",
  "query": "DAU 7 ngày gần đây có giảm không?",
  "expected_intent": "sql",
  "expected_tools": ["get_schema", "generate_sql", "execute_sql", "analyze_result"],
  "should_have_sql": true,
  "expected_keywords": ["giảm", "7 ngày"]
}
```

Metrics to track:

- routing accuracy
- SQL validity rate
- task success rate
- tool-call accuracy
- answer format validity
- average steps
- latency
- regression over time

Important:
- Evaluate behavior, not just the final answer.
- Trace quality and tool usage matter.

---

## Repository structure
Suggested directory layout:

```text
app/
  graph/
    state.py
    nodes.py
    edges.py
    graph.py
  tools/
    get_schema.py
    query_sql.py
    validate_sql.py
    retrieve_metric_definition.py
    retrieve_business_context.py
    analyze_trend.py
  rag/
    index_docs.py
    retriever.py
  observability/
    tracer.py
    logger.py
    schemas.py
  main.py

data/
  raw/
  warehouse/
  seeds/

docs/
  AGENTS.md
  thangquang09/
    AGENTS.md
    overview.md
    implementation_todo.md
  research/
    AGENTS.md
    rag/
      AGENTS.md
      metric_definitions.md
      retention_rules.md
      revenue_caveats.md
      data_quality_notes.md
    datasets/
      AGENTS.md
      dataset_research_2026-03-29.md
    evaluation/
      AGENTS.md
      eval_pipeline.md
    notebooklm/
      AGENTS.md
      notebooklm_mcp_codex_setup_2026-03-29.md
    notes/
      AGENTS.md
      research_notes_2026-03-29.md

evals/
  cases.json
  runner.py
  metrics.py

mcp_server/
  server.py
```

This structure is a recommendation, not a strict requirement, but keep the same conceptual separation.

---

## Prompting guidance
Prompts should be treated as controlled system components.

Prefer:
- structured output
- explicit tool-use instructions
- grounded synthesis
- refusal to invent data

Do not:
- hide business logic only in prompts
- allow vague tool descriptions
- use giant unstructured prompts when smaller targeted prompts are sufficient

Important behaviors to instruct the model on:

- do not invent metrics or numbers
- use tools when needed
- admit uncertainty when data is missing
- distinguish between factual retrieved context and inferred analysis

---

## SQL safety guidance
All generated SQL must be read-only.

Never allow:
- `DROP`
- `DELETE`
- `UPDATE`
- `INSERT`
- schema modifications

If the query is invalid or unsafe:
- capture the error,
- log it,
- optionally retry once,
- otherwise fail clearly.

---

## How coding agents should prioritize work
When contributing to this repository, prioritize in this order:

1. correctness
2. observability
3. evaluation
4. clarity of architecture
5. feature expansion
6. UI polish

If time is limited, always choose a smaller but more measurable implementation over a larger but vague implementation.

---

## What makes this project interview-worthy
Coding agents should preserve the parts of the project that create discussion value in interviews.

That includes:

- explicit routing
- SQL generation + validation + execution separation
- RAG vs SQL trade-offs
- deterministic analytics vs LLM reasoning
- traces and failure logs
- eval datasets and regression thinking
- MCP-compatible tool design

This project should help the owner explain not only:
- what the system does,

but also:
- where it fails,
- how it is observed,
- how it is improved.

---

## Success criteria
A good version of this project should let the owner demonstrate:

- a LangGraph-based agent architecture
- tool-calling over data + docs
- SQL safety and validation
- grounded answers
- observable traces
- a measurable eval loop
- a clean story connecting the project to the job description in `JD.txt`

---

## Final instruction to coding agents
When in doubt, ask:

> Does this change make the system easier to explain, debug, evaluate, and defend in an interview?

If yes, it is probably a good change.
If no, it is probably a distraction.


## Các tools có thể sử dụng:
- Bạn có thể sử dụng github MCP để tìm kiếm public code tham khảo
- NotebookLM MCP tôi có đoạn chat https://notebooklm.google.com/notebook/5220d387-0fa4-4250-8206-435e684c1c0e chi tiết về kiến thức thực tế lẫn lý thuyết về AI Engineer (LLM, Agent, RAG), bạn có thể dùng nó để lấy kiến thức tối ưu nhất.

---

## Practical LangGraph playbook (research update: 2026-03-29)
This section upgrades the draft with concrete implementation defaults.

### 1) State and schema discipline
- Use a typed `AgentState` and keep critical artifacts explicit (`intent`, `generated_sql`, `retrieved_context`, `tool_history`, `errors`).
- Define graph `input_schema` and `output_schema` to avoid accidental state leakage.
- Keep private/internal fields separate from user-facing output fields.

### 2) Routing and control flow
- Route with structured output (enum-style decision: `sql | rag | mixed`) instead of free-form text.
- Use conditional edges for primary routing; use `Command(goto=...)` only when dynamic jumps are necessary.
- Enforce a recursion/step limit on each run and fail with a clear `STEP_LIMIT_REACHED` error.

### 3) Reliability and safety
- Add node-level retry policies with different caps by failure type:
  - SQL/tool transient errors: retry.
  - validation/safety errors: do not retry blindly.
- Keep SQL validation deterministic and strict (`SELECT` only, known tables/columns, optional row limit).
- Reject unsafe SQL before execution and log the exact rejection reason.

### 4) Persistence and resumability
- Compile graph with a checkpointer (SQLite saver is acceptable for local-first demo).
- Use stable `thread_id` per conversation/run to support replay/debug/resume.
- Keep session memory small and scoped; do not mix long-term memory into SQL correctness logic.

### 5) Observability defaults
- Log run-level + node-level telemetry with consistent IDs:
  - run metadata, routing decision, used tools, generated SQL, latency, status.
  - per-node start/end timestamps, summarized input/output, error class.
- Store traces in a format that can be replayed for interview demos.

### 6) Eval requirements (non-optional)
- Evaluate behavior, not just final prose:
  - routing accuracy
  - SQL validity rate
  - tool-call path correctness
  - answer format validity
  - latency/step budget
- Maintain a small regression set and run it after prompt/tool changes.

### 7) Anti-patterns to avoid
- Do not hide business logic inside one giant prompt.
- Do not let the LLM directly execute SQL without validation.
- Do not skip traces/evals just to add UI polish.
- Do not overbuild multi-agent complexity in V1.

---

## Logging rule (project convention)
- All runtime logging must use `loguru` only.
- Do not add `logging` module handlers unless there is a hard external integration need.
- Log at component boundaries (router, tools, SQL validation, execution, retrieval, synthesis).
- Never log secrets (`LLM_API_KEY`, raw auth headers, tokens).
- Preferred levels:
  - `info`: normal flow events
  - `warning`: recoverable issues or degraded mode
  - `error`/`exception`: failed operations
