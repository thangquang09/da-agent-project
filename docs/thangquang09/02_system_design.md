# System Design — DA Agent Lab v3

> Phân tích latency, token economy, và scalability dựa trên code thực tế.
> Cập nhật: 2026-04-05

---

## 1. Token Economy

### 1.1 Per-Node Token Usage


| Node                      | Model         | Input/Call   | Output/Call | Calls/Query |
| ------------------------- | ------------- | ------------ | ----------- | ----------- |
| `task_grounder`           | `gpt-4o-mini` | ~600-900     | ~200-400    | 1           |
| `leader_agent` (1 step)   | `gpt-4o`      | ~1,200-3,000 | ~300-600    | 1-5         |
| `sql_worker.generate_sql` | `gpt-4o`      | ~800-2,500   | ~200-800    | 1/task      |
| `sql_worker.aggregate`    | `gpt-4o`      | ~500-1,500   | ~200-500    | 0-1         |
| `synthesis`               | `gpt-4o`      | ~400-1,200   | ~200-1,000  | 1           |


### 1.2 Token Budget Estimates

**Simple SQL query** (1 SQL task, no viz):

- task_grounder: ~800 tokens
- leader (1 step): ~2,000 tokens
- sql_worker LLM: ~1,200 tokens
- synthesis: ~600 tokens
- **Total: ~4,600 tokens/input + ~500 tokens/output**

**Mixed query** (SQL + RAG, 2 leader steps):

- task_grounder + leader (2 steps) + sql_worker + rag + synthesis
- **Total: ~7,000-10,000 tokens**

**Report query** (multi-section):

- task_grounder + leader + sql_worker + report_planner + report_writer + report_critic
- **Total: ~12,000-20,000 tokens**

### 1.3 Context Growth

Scratchpad trong `leader_agent` tăng mỗi step:

```
[Step 1] tool=ask_sql_analyst
{status, row_count, generated_sql (truncated 800 chars)...}
```

- Mỗi step thêm ~500-1,500 chars vào scratchpad
- Max 5 steps → scratchpad có thể grow tới ~7KB

XML database context:

- Phụ thuộc vào số tables trong schema
- Ví dụ: 10 tables × 5 columns × avg 20 chars/column = ~1KB
- Được build 1 lần ở đầu (`_ensure_v3_schema_context`) và reuse

---

## 2. Latency Analysis

### 2.1 Sequential Bottlenecks (Critical Path)

```
task_grounder (1-2s)
    ↓
leader_agent (2-5s per step × 1-5 steps)
    ↓
┌─────────────────────────────────────────────┐
│  ask_sql_analyst / ask_sql_analyst_parallel │
│  (parallel dispatch via ThreadPoolExecutor)  │
│  Per-task: 2-5s (LLM + DB + validation)    │
└─────────────────────────────────────────────┘
    ↓
synthesis (1-2s)
    ↓
[Optional] visualization E2B sandbox (5-15s)
```

**Total critical path:**

- Simple query: **6-15s**
- With visualization: **15-30s** (E2B sandbox startup dominates)

### 2.2 Parallel Opportunities

Đã implement:

- `ask_sql_analyst_parallel` dùng `ThreadPoolExecutor(max_workers=4)` để dispatch multiple SQL tasks song song
- Mỗi task chạy independent `sql_worker_graph`

Chưa parallel:

- task_grounder → leader: sequential (leader cần task_profile)
- leader steps: sequential (mỗi step cần output từ step trước)
- synthesis: sequential sau khi tất cả tasks hoàn thành

### 2.3 E2B Sandbox Latency

`standalone_visualization.py` và `sql_worker_graph._task_generate_visualization`:

```python
service = get_visualization_service()
sbx = service._get_sandbox()  # Sandbox startup: 3-10s
sbx.files.write(data_path, csv_content)
execution = sbx.run_code(python_code)  # Execution: 1-5s
```

**Bottleneck chính:** E2B sandbox cold start (~5-15s)
**Optimization potential:** Persistent sandbox, pre-warm pool

---

## 3. Scalability

### 3.1 Concurrent User Handling

```python
# app/graph/app.py
checkpointer = MemorySaver()
app = workflow.compile(checkpointer=checkpointer)
# State per thread_id: LangGraph checkpointer tự động isolate
```

- Mỗi user session = unique `thread_id`
- State được persist vào MemorySaver (in-memory, lost on restart)
- **Giới hạn: Memory usage tăng tuyến tính với concurrent sessions**

### 3.2 Database Concurrency

- SQLite với WAL mode (concurrent read OK, write serialized)
- `query_sql` tool dùng duckdb/SQLite connection
- **Write contention:** session memory saves, result_store writes
- **Read concurrency:** OK cho multiple concurrent reads

### 3.3 Memory Pressure Points


| Component              | Growth                    | Mitigation                                 |
| ---------------------- | ------------------------- | ------------------------------------------ |
| `artifacts` list       | Max 5 items (leader loop) | Auto-cleanup on finalize                   |
| `scratchpad`           | Grows ~1KB/step           | Truncated summary at 800 chars/tool result |
| `session_context`      | 5 recent turns            | Compacts at 10+ turns                      |
| `xml_database_context` | Schema size               | Built once, cached in state                |


### 3.4 Context Window Pressure

Token limit risk scenarios:

1. **Large schema** (>50 tables) → xml_database_context ~10KB
2. **Long session** (many turns) → session_context grows
3. **Many parallel tasks** → scratchpad accumulates

Current mitigations:

- Schema truncated to 1000 chars cho `task_planner`
- Session compact at 10 turns, keep last 5
- 5-step limit on leader loop

---

## 4. Model Routing

### 4.1 Current Routing Table


| Component     | Model         | Env Override           | Notes                   |
| ------------- | ------------- | ---------------------- | ----------------------- |
| task_grounder | `gpt-4o-mini` | `MODEL_PRECLASSIFIER`  | Lightweight classifier  |
| leader_agent  | `gpt-4o`      | `MODEL_LEADER`         | Supervisor decisions    |
| sql_worker    | `gpt-4o`      | `MODEL_SQL_GENERATION` | SQL + viz code gen      |
| synthesis     | `gpt-4o`      | `MODEL_SYNTHESIS`      | Natural language output |
| task_planner  | `gpt-4o`      | `MODEL_TASK_PLANNER`   | Query decomposition     |
| aggregation   | `gpt-4o`      | `MODEL_AGGREGATION`    | Parallel result merge   |
| fallback      | `gpt-4o-mini` | `MODEL_FALLBACK`       | Simple error handling   |


### 4.2 Cost Optimization Gaps

**Hiện tại:**

- Static model assignment via env vars
- Không có adaptive routing theo query complexity
- Không có model fallback nếu primary model fails

**Opportunities:**

1. Route simple queries (single table, no join) → `gpt-4o-mini`
2. Complex queries (multi-table, aggregation) → `gpt-4o`
3. Add retry with smaller model on failure

---

## 5. Failure Taxonomy

### 5.1 Failure Types & Recovery


| Failure                  | Detection                                 | Recovery                               | User Feedback                             |
| ------------------------ | ----------------------------------------- | -------------------------------------- | ----------------------------------------- |
| `SQL_VALIDATION_ERROR`   | `validate_sql()` returns `is_valid=False` | Retry generate_sql (max 2)             | "Query syntax error, retrying..."         |
| `SQL_EXECUTION_ERROR`    | `duckdb` exception                        | Retry generate_sql (max 2)             | User-friendly message (no raw DB errors)  |
| `LLM_API_FAILURE`        | Exception in `chat_completion()`          | Leader falls back to direct sql_worker | "Analysis completed with limited context" |
| `RAG_IRRELEVANT_CONTEXT` | Empty retrieved chunks                    | Finalize with low confidence           | "No relevant documentation found"         |
| `E2B_TIMEOUT`            | Sandbox startup/exec timeout              | User-friendly error, skip viz          | "Visualization service busy, try later"   |
| `AMBIGUOUS_QUERY`        | `task_grounder.confidence=low`            | Interrupt + clarification question     | Clarification prompt shown                |
| `STEP_LIMIT_REACHED`     | Leader loop > 5 iterations                | Finalize with current artifacts        | Partial answer + suggestion               |


### 5.2 Error Flow Examples

**SQL Validation Failure:**

```python
# sql_worker_graph._after_validate()
if status == "failed" and sql_retry_count <= 2:
    return "generate_sql"  # Retry
return END  # Stop, report error
```

**Visualization E2B Failure:**

```python
# standalone_visualization.py inline_data_worker()
except Exception as exc:
    if "sandbox" in error and "timeout" in error:
        user_error = "Visualization sandbox timed out. Please try again later."
    # Returns error artifact, leader finalizes without viz
```

**Ambiguous Query:**

```python
# nodes.py artifact_evaluator()
if task_mode == "ambiguous" or confidence == "low":
    decision = "wait_for_user"
    clarification_question = _generate_clarification_question(...)
    # Graph halts, caller shows clarification prompt
```

### 5.3 Observability Integration

Tất cả failures được capture trong `tracer.py`:

```python
NODE_TO_FAILURE = {
    "route_intent": "ROUTING_ERROR",
    "generate_sql": "SQL_GENERATION_ERROR",
    "validate_sql_node": "SQL_VALIDATION_ERROR",
    "execute_sql_node": "SQL_EXECUTION_ERROR",
    "retrieve_context_node": "RAG_RETRIEVAL_ERROR",
    "synthesis": "SYNTHESIS_ERROR",
}
```

Metrics logged:

- `error_categories`: Array of failure types
- `retry_count`: Total retries across nodes
- `fallback_used`: Boolean flag if fallback was triggered
- `total_cost_usd`: Estimated cost per run

---

## 6. Summary & Recommendations

### Key Findings

1. **Token Budget**: Simple query ~5K tokens, mixed query ~10K, report ~20K
2. **Latency**: E2B visualization là bottleneck chính (5-15s), rest ~6-15s
3. **Scalability**: Checkpointer-based isolation, memory bounded by concurrent sessions
4. **Model Routing**: Static assignment, gpt-4o-mini cho lightweight nodes
5. **Failure Handling**: Multi-level retry (2 attempts), graceful degradation, user clarification

### Recommended Optimizations


| Priority | Improvement                      | Expected Impact           |
| -------- | -------------------------------- | ------------------------- |
| HIGH     | E2B sandbox pool/pre-warm        | -50% viz latency          |
| MEDIUM   | Adaptive model routing           | -30% token cost           |
| MEDIUM   | Session memory compaction tuning | Better long conversation  |
| LOW      | Persistent checkpointer (Redis)  | Multi-instance deployment |


