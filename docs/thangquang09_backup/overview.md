# Ghi chú riêng cho Thắng - DA Agent
Cập nhật: 2026-03-30

## 1) Trạng thái hiện tại
- **Week 1 hoàn thành** + đã xong **Week 2 Day 1-2** (RAG + mixed routing).
- Đã có:
  - LangGraph orchestration (không phải code thuần)
  - SQL tools + safety validation
  - CLI chạy end-to-end
  - Streamlit UI cơ bản
  - Router đã chuyển sang **LLM-first** + fallback an toàn
  - Prompt tách riêng để quản lý
  - Local RAG index (chunk + cosine lexical embedding)
  - Retriever tools: `retrieve_metric_definition`, `retrieve_business_context`
  - Mixed path có fallback partial answer khi 1 nhánh fail

## 2) Bạn hỏi đúng 2 điểm quan trọng
### A. "LLM code thuần, không có LangGraph?"
- Hiện tại **có LangGraph thật** ở `app/graph/graph.py`.
- Node/tool vẫn là Python function (đây là chuẩn của LangGraph).

### B. "route_intent fix cứng"
- Đã đổi sang **agent (LLM) quyết định intent** (`sql/rag/mixed`) bằng output JSON có kiểm soát.
- Nếu LLM lỗi/JSON sai, hệ thống fallback heuristic để không vỡ luồng.

## 3) Quy ước kỹ thuật đang áp dụng
- Env loader: `pydotenv`
- Logger chuẩn toàn project: `loguru`
- API rule bắt buộc: luôn `stream=false`

### Stack cụ thể cho Text2SQL + Memory
- Checklist kỹ thuật chi tiết (công nghệ + module + tiêu chí done):
  - `docs/thangquang09/text2sql_memory_implementation_checklist_2026-03-30.md`
- Tóm tắt công nghệ đang/chốt dùng:
  - Orchestration: `LangGraph`
  - SQL runtime: `SQLite` + deterministic SQL guardrail
  - Retrieval: local vector index (hybrid vector/graph roadmap cho memory)
  - Observability: `loguru` + JSONL traces
  - Eval: `evals/runner.py` (domain/spider + memory stress planned)

## 4) Test để ổn định (mới thêm)
Mục tiêu: tránh việc phải chạy đi chạy lại nhiều lệnh thủ công.

### Đã thiết lập
- `pytest` + `pytest-cov`
- `tests/conftest.py` tự seed DB trước test
- Test SQL tools
- Test graph flow (SQL path, RAG retrieval, mixed fallback)
- Test RAG tools
- Config pytest trong `pyproject.toml`

### Chạy test 1 lệnh
```powershell
uv run pytest
```

### Nếu muốn xem coverage
```powershell
uv run pytest --cov=app --cov-report=term-missing
```

## 5) Lệnh chạy nhanh hàng ngày
### Seed DB
```powershell
uv run python data/seeds/create_seed_db.py
```

### Smoke test CLI
```powershell
uv run python -m app.main "DAU 7 ngày gần đây như thế nào?"
```

### Chạy UI
```powershell
uv run streamlit run streamlit_app.py
```

## 6) Các file chính nên đọc
- `docs/thangquang09/implementation_todo.md`
- `app/graph/graph.py`
- `app/graph/nodes.py`
- `app/prompts/router.py`
- `app/prompts/sql.py`
- `app/tools/`
- `tests/`

## 7) Bước kế tiếp mình đang làm
- Chuyển qua Week 2 Day 4 (Prompt hardening), vì Day 3 đã xong:
  - trace schema run-level + node-level
  - log intent/tools/sql/retry/errors/latency
  - failure taxonomy chuẩn hóa
  - persist `evals/reports/traces.jsonl`
  - optional Langfuse adapter (bật qua env)

## 8) Kết quả smoke test Day 5
- Đã chạy 10 query SQL manual bằng script:
```powershell
uv run python -m evals.manual_sql_smoke
```
- Output:
  - `evals/manual_sql_smoke_report.md`
  - `evals/manual_sql_smoke_report.json`

## 9) Cập nhật fix regression (2026-03-29)
Đã fix 3 lỗi quan trọng ở nhánh RAG/mixed:
- Fallback router hỗ trợ query tiếng Việt có dấu qua chuẩn hóa dấu (`là gì`, `bao nhiêu`, `giảm`, `7 ngày`) để tránh lệch route khi LLM router unavailable.
- RAG intent không còn luôn ép dùng `retrieve_metric_definition`; query dạng định nghĩa mới dùng metric retriever, còn query caveat/rule dùng `retrieve_business_context`.
- Mixed synthesis coi SQL chạy thành công nhưng `0 rows` là **SQL success** (không gán nhầm là SQL branch failed).

Test regression đã thêm:
- `test_route_intent_fallback_supports_vietnamese_diacritics`
- `test_retrieve_context_rag_non_definition_uses_business_context`
- `test_mixed_synthesis_treats_empty_sql_result_as_success`

## 10) Eval overhaul (2026-03-30)
- Replaced hardcoded manual eval questions with dataset-driven eval logic.
- Added case contract and generators:
  - `evals/case_contracts.py`
  - `evals/build_cases.py`
- Added two suites:
  - `domain` suite (UCI + MovieLens derived SQLite)
  - `spider` suite (Spider dev subset with per-case DB path)
- Added batch runner and reports:
  - `evals/runner.py`
  - `evals/reports/latest_summary.json`
  - `evals/reports/latest_summary.md`
  - `evals/reports/per_case.jsonl`
- Graph now supports per-run DB override via `target_db_path` for eval cases.

## 11) Observability layer (Week2 Day3 - hoàn thành)
- Đã thêm module:
  - `app/observability/schemas.py`
  - `app/observability/tracer.py`
- Graph nodes được instrument bằng wrapper ở `app/graph/graph.py`:
  - record node start/end, attempt, latency, input/output summary
  - map observation type theo Langfuse concept (`agent`, `generation`, `tool`, `retriever`, `guardrail`, `chain`)
- `run_query` tích hợp tracer lifecycle:
  - set/reset tracer context
  - ghi run record success/failure
- Đã thêm test observability:
  - `tests/test_observability.py`
- Cấu hình mới:
  - `TRACE_JSONL_PATH` (default: `evals/reports/traces.jsonl`)
  - `ENABLE_LANGFUSE` (default: `true`)

## 12) Streamlit logic upgrade (2026-03-30)
- Refactor `streamlit_app.py` sang kiểu **chatbot thực thụ** với `st.chat_input` + `st.chat_message`.
- Thêm hàng đợi `pending_queries` để xử lý tuần tự khi người dùng gửi liên tục (spam query).
- Mỗi query có trạng thái assistant `thinking` trước khi trả kết quả.
- Kết quả mỗi turn giữ đầy đủ debug panel:
  - metrics: confidence / intent / tokens / cost
  - logs: SQL / Trace / Errors / Raw payload
- Thêm sidebar session control:
  - trạng thái `idle|processing`
  - số lượng query đang chờ
  - nút `Clear Chat History`
- Logging theo chuẩn project (`loguru`) ở các boundary của luồng Streamlit.
- Regression check: `uv run pytest -q` => `19 passed`.

## 13) Bugfix: natural question routing (2026-03-30)
- Vấn đề: câu hỏi kiểu tự nhiên/capability như `bạn có thể làm gì?` bị route sang `rag` khiến flow không hợp lý.
- Đã fix:
  - Router hỗ trợ intent `unknown` (LLM output + fallback keyword).
  - Graph route `unknown` đi thẳng `synthesize_answer`, không gọi SQL/RAG tools.
  - `synthesize_answer` thêm câu trả lời capability rõ ràng cho `unknown`.
- Không thay đổi rule-based SQL trong đợt fix này (theo yêu cầu).
- Regression tests đã thêm:
  - `test_route_intent_fallback_handles_natural_question_as_unknown`
  - `test_graph_unknown_intent_goes_direct_to_synthesize`
- Verify: `uv run pytest -q` => `21 passed`.

## 14) Prompt hardening + Langfuse management (2026-03-30)
- Added `PromptManager` to pull router/SQL prompts from Langfuse (with per-prompt caching) and keep local templates as fallbacks when credentials are missing or offline.
- Router prompt now requires JSON intent output, logs the prompt name in `tool_history`, and uses Langfuse fallback when the API is unavailable; SQL prompt reiterates read-only rules and schema grounding before every generation call.
- NotebookLM prompt-hardening queries (commands issued via session IDs 34781 and 39650) plus Langfuse prompt-management docs shaped the anti-hallucination checklist collected at `docs/research/notes/prompt_hardening_2026-03-30.md`.
- Tests impacted: `tests/test_prompt_manager.py`, `tests/test_graph_flow.py` (autouse fixture for disabling LLM SQL), plus `uv run pytest -q` => `26 passed`.

## 15) Regression fix: empty SQL after prompt-manager migration (2026-03-30)
- Root cause: SQL extractor in `generate_sql` parsed markdown fences with `split("```")[-1]`, which returns empty string when the model emits a standard ` ```sql ... ``` ` block.
- Fix: add `_extract_sql_from_content(...)` in `app/graph/nodes.py` that:
  - prefers fenced SQL blocks,
  - falls back to first `SELECT/WITH` statement,
  - otherwise keeps raw content.
- Added regression test `test_generate_sql_extracts_from_markdown_fence`.
- Verify:
  - `uv run pytest -q` => all tests pass
  - `uv run python -m app.main "DAU 7 ngày gần đây như thế nào?"` now validates SQL and executes query successfully.

## 16) Langfuse prompt issue note (2026-03-30)
- Current runtime warning observed:
  - `Langfuse.get_prompt() got an unexpected keyword argument 'labels'`
- Impact:
  - Prompt fetch from Langfuse fails for now, but local prompt fallback remains active and stable.
- Decision:
  - Keep this as a tracked issue only (non-blocking) per current project priority.
  - Continue using local prompt templates while preserving Langfuse prompt-manager structure for later SDK/version alignment.

## 17) Week2 Day5 + Week3 Day3 completion (2026-03-30)
- Week2 Day5:
  - Streamlit now includes sample query buttons in sidebar (`SQL`, `RAG`, `Mixed`) to speed up demo flow.
- Week3 Day3:
  - Added groundedness baseline module at `evals/groundedness.py`.
  - Eval runner now computes:
    - `groundedness_score`
    - `groundedness_pass`
    - `unsupported_claims`
    - `groundedness_fail_reasons`
    - `marked_answer`
  - Gate threshold extended with `groundedness_pass_rate`.
  - Failure taxonomy extended with `HALLUCINATION_RISK` when groundedness check fails.
  - Runtime answer payload now includes `unsupported_claims`; if detected, answer is marked with `[UNSUPPORTED_CLAIMS] ...`.

## 18) WSL path migration for eval stability (2026-03-30)
- Problem confirmed:
  - Eval cases used Windows-style paths (`data\\...`) while running in WSL.
  - SQLite opened unintended empty DB files, causing widespread `Unknown table(s)` and low SQL validity.
- Implemented fixes:
  - `evals/case_contracts.py`: normalize `target_db_path` on load (`\\` -> `/`).
  - `evals/build_cases.py`: always emit POSIX-style `target_db_path` via `.as_posix()`.
  - Rewrote `evals/cases/domain_cases.jsonl` and `evals/cases/spider_cases.jsonl` with normalized paths.
  - Removed accidental backslash-named DB artifacts created in repo root.
- Re-run result (`uv run python -m evals.runner`):
  - `sql_validity_rate`: **0.2727 -> 0.7500**
  - `tool_path_accuracy`: **0.2500 -> 0.7273**
  - `groundedness_pass_rate`: **0.1591 -> 0.2045**
- Remaining top blockers after WSL migration:
  - SQL validator still flags CTE aliases as unknown tables in some domain cases (`last_7_days`, `last_two_days`, `recent_dates`).
  - Groundedness rule is overly strict by treating retrieval scores/time tokens as unsupported numeric claims.
