# AI Agent Memory Deep Research Notes (NotebookLM)
Date: 2026-03-30

## 1) Scope and method
- Objective: continue deep research on memory for AI agents using the existing NotebookLM knowledge base.
- Notebook used:
  - Title: `LLM - KD - AI AGENT`
  - Notebook ID: `5220d387-0fa4-4250-8206-435e684c1c0e`
  - Source count at research time: `76`
- Method:
  - Restricted synthesis to memory-relevant sources (memory architecture papers, LangGraph/LangChain memory docs, MemGPT/ACC-related references, vector-vs-graph memory references).
  - Ran 5 focused synthesis queries:
    - taxonomy
    - architecture
    - read/write policy
    - evaluation framework
    - LangGraph playbook for DA Agent Lab

## 2) Traceability artifacts
- Raw outputs:
  - `/tmp/agent_memory_nlm/q1_taxonomy.json`
  - `/tmp/agent_memory_nlm/q2_architecture.json`
  - `/tmp/agent_memory_nlm/q3_write_policy.json`
  - `/tmp/agent_memory_nlm/q4_evaluation.json`
  - `/tmp/agent_memory_nlm/q5_playbook.json`
- Notebook URL:
  - `https://notebooklm.google.com/notebook/5220d387-0fa4-4250-8206-435e684c1c0e`

## 3) Consolidated findings

### A. Practical memory taxonomy
- Working memory:
  - short-lived active state inside/near context window.
  - best used as bounded control state, not full transcript replay.
- Episodic memory:
  - interaction/event history across turns.
  - should be summarized/compressed periodically.
- Semantic memory:
  - durable facts, definitions, domain knowledge.
  - represented via vector index and/or graph knowledge layer.
- Procedural memory:
  - tool usage rules, workflows, policies, prompts/instructions.
  - should be explicit and auditable.

### B. Architecture pattern that scales
- Prefer layered memory design:
  - bounded working state
  - episodic event store
  - semantic knowledge store
  - procedural policy/tool store
- Strong recommendation from sources:
  - avoid unbounded transcript replay as the primary persistence strategy.
  - use compressed cognitive state (bounded schema-governed state) for cross-turn control stability.
- Retrieval strategy:
  - hybrid vector-first + graph follow-up for relationship-heavy queries.

### C. Write policy and memory hygiene
- Do not write everything.
- Write triggers should be event-driven:
  - sub-task completion
  - dead-end/failure diagnostics
  - validated facts and stable constraints
- Use importance scoring for retention/eviction:
  - RIF style: recency + relevance + frequency/utility.
- Prevent memory pollution:
  - separate "candidate recall" from "committed memory."
  - commit only verified, high-value information.
- Use temporal/version controls:
  - timestamp/version fields
  - soft-delete before hard-delete
  - configurable TTL/decay.

### D. Evaluation for memory reliability
- Evaluate memory behavior over long horizons (multi-turn), not only single-turn quality.
- Suggested memory metrics:
  - hallucination rate over turns
  - drift rate against active constraints
  - memory footprint growth per turn
  - retrieval latency and retrieval precision/recall
- Regression design:
  - include stress scenarios:
    - conflicting updates
    - noisy/misleading context
    - requirement changes mid-conversation
    - memory poisoning attempts.

### E. Risks and guardrails
- Key risks:
  - context poisoning
  - context distraction
  - context clash (contradictory facts)
  - goal/constraint drift over long dialogs
- Guardrails:
  - commit only validated facts to long-term memory
  - enforce namespace/user-level isolation for memory privacy
  - keep a strict, typed memory schema for predictable updates.

## 4) Recommended impact on DA Agent Lab

### Immediate (high ROI)
- Add bounded memory controller behavior into graph flow:
  - keep compressed state fields instead of full transcript carry-over.
- Add explicit memory fields to state model:
  - `active_constraints`
  - `episodic_summary`
  - `semantic_facts`
  - `uncertainty_flags`
  - `memory_version`
- Add write-qualification gate before persisting long-term memory.
- Track memory observability:
  - per-turn memory token footprint
  - drift violations
  - hallucination audit flags.

### Next iteration
- Add hybrid memory retrieval path:
  - vector retrieval default
  - graph-assisted retrieval for relational/multi-hop questions.
- Add memory-focused regression suite in `evals/` with stress scenarios.
- Add memory cleanup job:
  - RIF scoring
  - soft-delete archive
  - recovery checks for over-pruning.

## 5) Source quality note
- This notebook includes mixed source quality (official docs, papers, blogs, and community content).
- For implementation decisions:
  - prioritize official docs + peer-reviewed/technical papers.
  - treat blog/community content as directional signals, then verify with local eval runs.
