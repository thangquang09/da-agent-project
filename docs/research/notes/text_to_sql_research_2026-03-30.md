# Text-to-SQL Deep Research Notes (NotebookLM)
Date: 2026-03-30

## 1) Scope and method
- Objective: create a new NotebookLM notebook for Text-to-SQL and extract practical, production-oriented guidance for this DA Agent Lab.
- Notebook created:
  - Title: `Text-to-SQL`
  - Notebook ID: `c66a9f5f-8355-49cc-be72-5295fe6e0f18`
- Research task:
  - Task ID: `e61673a5-45b8-471a-9d8c-e855849489ef`
  - Mode: `deep`
  - Result: imported `87` sources
- Synthesis queries executed (NotebookLM `notebook query --json`):
  - Landscape 2024-2026
  - Production architecture + guardrails
  - Evaluation framework
  - Prompting/reasoning strategies
  - Implementation playbook for LangGraph

## 2) Artifacts and traceability
- Raw query outputs:
  - `/tmp/text2sql_nlm/q1_landscape.json`
  - `/tmp/text2sql_nlm/q2_architecture.json`
  - `/tmp/text2sql_nlm/q3_eval.json`
  - `/tmp/text2sql_nlm/q4_prompting.json`
  - `/tmp/text2sql_nlm/q5_playbook.json`
- Notebook URL:
  - `https://notebooklm.google.com/notebook/c66a9f5f-8355-49cc-be72-5295fe6e0f18`

## 3) Consolidated findings (for this repo)

### A. Architecture trend (2024-2026)
- Strong shift from monolithic one-shot SQL generation to agentic pipelines:
  - planner/decomposer
  - schema linker/retriever
  - SQL generator
  - validator/executor
  - critic/refiner
  - selector/judge (for multi-candidate flows)
- Benchmark-to-enterprise gap is still the main issue; high benchmark scores do not transfer directly to messy enterprise schemas.
- Practical conclusion: architecture quality + guardrails matter more than only model choice.

### B. Production architecture defaults
- Keep explicit staged flow:
  - intent routing
  - schema retrieval/linking
  - SQL generation
  - deterministic validation (AST + read-only policy)
  - execution (sandbox/read-only)
  - correction loop with max retry
  - synthesis
- Add semantic cache for repeated NL queries (latency and cost reduction).
- Prefer role-aware schema context (prune inaccessible tables/columns before prompting).

### C. Prompting and reasoning
- Use structured prompting over giant prompts:
  - clear task decomposition
  - schema-focused context
  - dynamic few-shot from a verified SQL corpus
- Self-correction should be execution-guided (error-aware refine loop), bounded by strict retry limits.
- Keep deterministic code for security-critical logic; do not rely on prompt-only constraints.

### D. Evaluation insights
- Evaluate behavior, not only final prose:
  - execution accuracy
  - test-suite accuracy
  - schema-linking quality (recall + false positives)
  - routing/tool path correctness
  - answer groundedness
  - latency and step budget
- Maintain a regression set sourced from real team questions + verified SQL.
- Important caveat: some benchmark labels can be noisy; include manual spot checks for critical cases.

### E. Failure modes to prioritize
- Silent semantic errors (query runs but answers wrong business intent).
- Schema hallucination/staleness (wrong table/column or outdated schema).
- Query efficiency failure (expensive joins/full scans).
- Business-rule drift (old few-shot examples or stale semantic logic).

## 4) Recommended impact on DA Agent Lab

### Immediate (high ROI)
- Keep strict node separation (`route -> schema -> gen -> validate -> execute -> analyze -> synthesize`).
- Strengthen `validate_sql`:
  - enforce `SELECT` only
  - AST checks for disallowed operations
  - allow-list table/column validation
- Add bounded correction loop with explicit error taxonomy and retry policy.
- Log schema-linking quality metrics and route decisions per run.

### Next iteration
- Add semantic cache layer for recurring natural-language questions.
- Add enterprise-like eval buckets:
  - simple/moderate/complex query classes
  - business ambiguity cases
  - schema drift and naming-noise cases
- Track efficiency metric in eval/reporting (runtime or normalized score), not only correctness.

## 5) Source quality notes
- This research set includes mixed source types: papers, benchmark pages, engineering blogs, and community posts.
- Treat peer-reviewed papers/official benchmark docs as primary evidence.
- Treat blog/community sources as implementation signals that still require local validation via evals.

## 6) Suggested follow-up tasks
- Update eval contracts to include:
  - schema-linking metrics
  - silent semantic error tagging
  - efficiency-oriented score
- Add one dedicated "Text-to-SQL hard set" in `evals/cases/` for regression after prompt/tool changes.
