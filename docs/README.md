# docs — DA Agent Lab Documentation

## Nguồn chân lý

Mọi tài liệu ở đây phải **đúng với code hiện tại**. Nếu code thay đổi — cập nhật docs ngay. Không có aspirational documentation.

---

## Thư mục

### `thangquang09/` — Thắng & Phỏng vấn viên
**Ngôn ngữ:** Tiếng Việt · **Quy tắc:** Ghi WHY + HOW, không ghi WHAT (WHAT = đọc code)

| File | Nội dung |
|------|----------|
| [01_architecture.md](thangquang09/01_architecture.md) | Sơ đồ khối, graph flow, Task Grounder, Artifact Evaluator, Clarify Interrupt |
| [02_system_design.md](thangquang09/02_system_design.md) | Token economy, latency analysis, scalability, failure taxonomy |
| [03_interview_qna.md](thangquang09/03_interview_qna.md) | Trả lời hóc búa: tại sao LangGraph, hybrid architecture, SQL safety, observability, scaling |

### `_tech_specs/` — Tài liệu kỹ thuật chi tiết
**Ngôn ngữ:** English · **Quy tắc:** Precise types, real function signatures, actual field names

| File | Nội dung |
|------|----------|
| [01_state_model.md](_tech_specs/01_state_model.md) | AgentState complete schema, Annotated merge semantics, state transitions |
| [02_worker_contracts.md](_tech_specs/02_worker_contracts.md) | WorkerArtifact contract, per-worker input/output, terminal signals |
| [03_observability.md](_tech_specs/03_observability.md) | RunTracer, @trace_node, Langfuse integration, JSONL format |
| [04_observability_schema.md](_tech_specs/04_observability_schema.md) | Trace event schema, error tracking format |

---

## Đọc nhanh theo vai trò

**Phỏng vấn viên** → `thangquang09/01_architecture.md` → `thangquang09/03_interview_qna.md`

**Review code mới** → `_tech_specs/01_state_model.md` + `_tech_specs/02_worker_contracts.md`

**Debug production** → `_tech_specs/03_observability.md`

**Thay đổi kiến trúc** → `thangquang09/01_architecture.md` → `_tech_specs/01_state_model.md` → PR với migration plan
