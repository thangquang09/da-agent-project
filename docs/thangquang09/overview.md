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
