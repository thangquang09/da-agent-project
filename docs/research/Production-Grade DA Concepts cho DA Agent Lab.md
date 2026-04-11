  Research Report: Production-Grade DA Concepts cho DA Agent Lab

  Research Methodology

  - Effort Level: Medium (5 queries/agent)
  - Total Searches: ~20 searches
  - Research Agents: 2 (Star Schema + Semantic Model; RLS + Data Quality)
  - Deep Research Agents: 2 (Agentic BI production patterns; Data Storytelling + What-If + Query
  optimization)

  ---
  Executive Summary

  Bài post LinkedIn không sai — nhưng category error nằm ở chỗ so sánh nhầm đối tượng. DA Agent Lab không
  phải BI tool thay DA; nó là agentic analytics assistant. Và chính xác đây là hướng mà toàn bộ industry
  đang đi: Snowflake Cortex Analyst, Databricks Genie, ThoughtSpot Spotter, Microsoft Fabric Data Agents
  đều là Agentic BI — và tất cả đều hội tụ về cùng một kiến trúc.

  Gap lớn nhất của DA Agent Lab không phải thiếu tính năng, mà thiếu semantic layer — đây là thứ phân biệt
   toy demo và production system. Tin tốt: gap này có thể lấp đầy dần mà không cần rebuild từ đầu.

  ---
  Key Findings

  1. Semantic Layer — Ưu tiên #1, ROI cao nhất

  Định nghĩa: File YAML/JSON định nghĩa metrics, dimensions, business rules, synonyms — đặt giữa LLM và
  raw SQL.

  Tại sao quan trọng: Snowflake báo cáo +20% accuracy khi dùng semantic model vs raw schema prompting.
  Production systems hiện tại không trỏ LLM vào raw DDL — họ trỏ LLM vào governed business vocabulary.

  Áp dụng cho DA Agent Lab:
  # semantic_model.yaml
  metrics:
    - name: revenue
      description: "Total paid orders: SUM(payment_value) WHERE status NOT IN ('canceled')"
      synonyms: ["sales", "income", "doanh thu", "GMV"]
    - name: dau
      description: "Daily Active Users: COUNT(DISTINCT user_id) WHERE action_date = :date"
      synonyms: ["người dùng hàng ngày", "active users"]
  dimensions:
    - name: product_category
      table: products
      column: product_category_name

  Feasibility: Medium — 1–2 ngày để define 10–15 metrics. Có thể dùng ngay trong inject_session_context
  node.

  ---
  2. Schema Linker (RAG over metadata) — Thay thế full schema dump

  Định nghĩa: Thay vì dump toàn bộ schema vào LLM, embed tất cả table/column descriptions vào vector
  store, retrieve chỉ top-K relevant tables cho từng query.

  Tại sao quan trọng: Schema của enterprise DB 200+ tables không fit vào context window. Hallucinated
  column names là lỗi phổ biến nhất trong production NL2SQL.

  Áp dụng: Dùng pgvector (đã có PostgreSQL) để index schema descriptions. Node mới schema_linker chạy
  trước leader_agent.

  Feasibility: Medium — pgvector + simple HNSW index + embed schema at startup.

  ---
  3. Verified Query Repository — "Trusted Assets" pattern

  Định nghĩa: Cache SQL queries đã được human verify. Khi query mới đủ similar (cosine similarity >
  threshold), trả về verified SQL thay vì generate mới, gắn nhãn "Trusted".

  Databricks Genie gọi là "Trusted Assets", Snowflake Cortex gọi là "Verified Query Repository". Đây là
  bypass hallucination hoàn toàn cho known query patterns.

  CREATE TABLE agent.verified_queries (
      id SERIAL PRIMARY KEY,
      query_text TEXT,
      query_embedding VECTOR(1536),
      verified_sql TEXT,
      description TEXT,
      created_at TIMESTAMPTZ DEFAULT NOW()
  );

  Feasibility: Medium — pgvector đã có, chỉ cần thêm table + similarity lookup trong leader_agent.

  ---
  4. Multi-Stage SQL Validation + Self-Correction Loop

  Định nghĩa: Thay vì validate một lần (AST check), production systems validate 3 stages và có retry loop
  với error context.

  Áp dụng (extend validate_sql_query hiện tại):
  - Stage 1 (đã có): AST parse, SELECT-only check
  - Stage 2 (mới): Table/column existence check against actual schema
  - Stage 3 (mới): EXPLAIN ANALYZE (không fetch data, chỉ validate execution plan)
  - Retry loop: nếu fail → re-invoke với error message + failing SQL (max 3x)

  Research finding: "Most initially incorrect SQL is fixed in a single retry when provided error message +
   failing SQL."

  Feasibility: Easy-Medium — LangGraph loop đã có (artifact_evaluator → leader_agent), chỉ cần extend
  validation stages.

  ---
  5. Row-Level Security (RLS) — PostgreSQL native

  Định nghĩa: Database-enforced filtering — user chỉ thấy rows thuộc scope của họ. Enforce ở DB layer,
  không phải app layer.

  Implementation:
  -- FastAPI middleware inject session context
  SET app.tenant_id = $tenant_id;
  SET app.user_id = $user_id;

  -- Policy enforce tại query time
  ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
  CREATE POLICY tenant_isolation ON orders
    FOR ALL TO app_user
    USING (tenant_id = current_setting('app.tenant_id')::int);

  Feasibility: Medium — native PostgreSQL, không cần extension. Cần FastAPI middleware inject session
  context trước mỗi query.

  Portfolio value: Rất cao — "Shifted security from fragile app code to database kernel."

  ---
  6. Data Quality Pipeline — Pandera + pre/post validation

  Định nghĩa: Validate data trước khi agent generate insight — prevent garbage-in-garbage-out.

  Áp dụng (thêm node mới trong LangGraph):
  # Pre-SQL: check data freshness, schema validity, row count anomalies
  # Post-SQL: validate result schema với Pandera, outlier detection
  import pandera as pa
  result_schema = pa.DataFrameSchema({
      "metric_value": pa.Column(float, pa.Check.greater_than(0)),
  })

  Library stack:
  - Pandera (Easy): schema validation 2 dòng code
  - ydata-profiling (Easy): data profiling 1 dòng
  - Custom SQL checks (Easy): freshness, cardinality, null ratio

  Feasibility: Easy — 30 phút cho basic checks, 2 giờ cho full pipeline.

  ---
  7. Data Storytelling — SCR Format (không phải mô tả chart)

  Định nghĩa: Structured narrative với 4 phần bắt buộc:
  1. OBSERVATION   → Con số thay đổi gì (cụ thể, có delta)
  2. CONTEXT       → So với gì (baseline, mục tiêu, prior period)
  3. INTERPRETATION → Tại sao (hypothesis có căn cứ)
  4. RECOMMENDATION → Làm gì (cụ thể, có owner, có deadline, có KPI đo lường)

  Ví dụ transformation:
  - ❌ Chart description: "D30 retention giảm từ 42% xuống 34%"
  - ✅ Data Story: "Retention đang gãy — redesign mobile checkout là likely cause. D30 retention ổn định ở
   42% trong 6 tháng, giảm xuống 34% trong 3 tuần sau khi mobile checkout redesign ngày 18/3. Control
  group (old flow) giữ ở 41%. Khuyến nghị: revert về version 17/3 và A/B test trước release tiếp theo.
  Owner: Product team. Timeline: 48 giờ."

  Safety rule cho LLM (đã có một phần trong report_subgraph, cần enforce mạnh hơn):
  ▎ "Every numeric claim must come from computed_stats.json. Do not calculate or invent numbers."

  Feasibility: Easy — prompt engineering trong report_subgraph insight nodes. Không cần code mới, chỉ cần
  update prompts.

  ---
  8. What-If Analysis — Parametric scenario modeling

  Định nghĩa: User thay đổi 1+ input variables (churn rate, price, conversion), agent tính cascade effect
  lên output metrics. Không phải LLM tự "sáng tác" scenarios — LLM chỉ interpret kết quả từ parameterized
  SQL.

  Implementation scoped cho portfolio:
  # User: "What happens to revenue if churn drops by 1%?"
  # → task_grounder extracts: base_metric="revenue", variable="churn_rate", delta=-0.01
  # → leader_agent runs 2-3 parameterized SQL variants
  # → LLM generates comparison narrative từ results (không tự tính số)

  Feasibility: High — scoped là "parameterize existing SQL queries" + narrative generation.

  ---
  9. Query Folding / Incremental Refresh — PostgreSQL equivalents

  Query Folding (push computation to DB): DA Agent Lab đã làm đúng — ask_sql_analyst luôn filter/aggregate
   trong SQL, không load full table vào Python.

  Incremental Refresh — PostgreSQL options:

  ┌────────────────────────────────────────┬────────────┬──────────────────────────────────┐
  │                Approach                │ Complexity │             Phù hợp              │
  ├────────────────────────────────────────┼────────────┼──────────────────────────────────┤
  │ REFRESH MATERIALIZED VIEW CONCURRENTLY │ Low        │ Batch refresh, đủ cho portfolio  │
  ├────────────────────────────────────────┼────────────┼──────────────────────────────────┤
  │ Incremental append với watermark       │ Low-Medium │ Fact tables append-only          │
  ├────────────────────────────────────────┼────────────┼──────────────────────────────────┤
  │ pg_ivm extension                       │ Medium     │ Self-managed PostgreSQL (Docker) │
  └────────────────────────────────────────┴────────────┴──────────────────────────────────┘

  Feasibility: Easy — dùng REFRESH MATERIALIZED VIEW CONCURRENTLY + pg_cron hoặc APScheduler.

  ---
  Contested Areas

  - Semantic layer: build vs buy: Dùng Cube.dev (setup nhanh) vs tự build YAML file (more portable, less
  dependencies). Cho portfolio: YAML file custom đơn giản hơn và demonstrate thinking rõ ràng hơn.
  - Multi-agent pipeline latency: 5-stage pipeline có thể 10–20s cho complex queries. Single LLM với good
  prompting trả về 2–4s. Trade-off rõ ràng.
  - pg_ivm vs manual incremental: pg_ivm impressive nhưng không chạy trên managed PostgreSQL. Manual
  watermark pattern safer cho portfolio.

  ---
  Recommendations — Prioritized Roadmap cho DA Agent Lab

  Tier 1: High Impact, Low Effort (làm ngay)

  ┌─────┬───────────────────────────────────────────────────────────────┬─────────┬───────────────────┐
  │  #  │                            Feature                            │ Effort  │      Impact       │
  ├─────┼───────────────────────────────────────────────────────────────┼─────────┼───────────────────┤
  │ 1   │ Semantic Model YAML (10–15 metrics, synonyms, business rules) │ 1–2     │ +15–20% SQL       │
  │     │                                                               │ ngày    │ accuracy          │
  ├─────┼───────────────────────────────────────────────────────────────┼─────────┼───────────────────┤
  │ 2   │ Data Storytelling prompt upgrade (enforce SCR format,         │ 2–3 giờ │ Insight quality   │
  │     │ no-hallucination rule)                                        │         │ ↑↑                │
  ├─────┼───────────────────────────────────────────────────────────────┼─────────┼───────────────────┤
  │ 3   │ Multi-stage SQL validation (extend validate_sql_query, add    │ 4–6 giờ │ Reliability ↑     │
  │     │ column existence check)                                       │         │                   │
  ├─────┼───────────────────────────────────────────────────────────────┼─────────┼───────────────────┤
  │ 4   │ Basic Data Quality node (Pandera + freshness check + null     │ 3–4 giờ │ Trust ↑           │
  │     │ ratio)                                                        │         │                   │
  └─────┴───────────────────────────────────────────────────────────────┴─────────┴───────────────────┘

  Tier 2: Medium Impact, Medium Effort (next sprint)

  ┌─────┬──────────────────────────────────────────────────────┬─────────┬────────────────────────────┐
  │  #  │                       Feature                        │ Effort  │           Impact           │
  ├─────┼──────────────────────────────────────────────────────┼─────────┼────────────────────────────┤
  │ 5   │ Schema Linker node (pgvector + embed schema          │ 2–3     │ Scale to large schemas     │
  │     │ descriptions)                                        │ ngày    │                            │
  ├─────┼──────────────────────────────────────────────────────┼─────────┼────────────────────────────┤
  │ 6   │ Verified Query Repository (agent.verified_queries    │ 2–3     │ "Trusted" label, bypass    │
  │     │ table + similarity lookup)                           │ ngày    │ hallucination              │
  ├─────┼──────────────────────────────────────────────────────┼─────────┼────────────────────────────┤
  │ 7   │ What-If Analysis mode (parameterized SQL + scenario  │ 3–4     │ C-level decision making    │
  │     │ comparison)                                          │ ngày    │ feature                    │
  ├─────┼──────────────────────────────────────────────────────┼─────────┼────────────────────────────┤
  │ 8   │ PostgreSQL RLS (FastAPI middleware + tenant          │ 2–3     │ Security architecture      │
  │     │ policies)                                            │ ngày    │                            │
  └─────┴──────────────────────────────────────────────────────┴─────────┴────────────────────────────┘

  Tier 3: Portfolio Polish (sau khi Tier 1+2 xong)

  ┌─────┬────────────────────────────────────────────┬──────────┐
  │  #  │                  Feature                   │  Effort  │
  ├─────┼────────────────────────────────────────────┼──────────┤
  │ 9   │ KPI Tree (metric DAG + drill-down node)    │ 1 tuần   │
  ├─────┼────────────────────────────────────────────┼──────────┤
  │ 10  │ Materialized Views với incremental refresh │ 1–2 ngày │
  ├─────┼────────────────────────────────────────────┼──────────┤
  │ 11  │ PII column exclusion từ schema sent to LLM │ 1 ngày   │
  └─────┴────────────────────────────────────────────┴──────────┘

  ---
  Confidence Assessment

  High confidence (multiple independent sources xác nhận):
  - Semantic layer là #1 ROI change cho NL2SQL accuracy
  - "The competitive advantage is not which model you use — the moat is your metadata." — Annmol
  Hattikudur, Medium
  - SCR format là professional DA standard cho insight presentation
  - PostgreSQL RLS là implementation pattern đúng cho multi-user analytics

  Medium confidence (feasibility depends on scope):
  - What-If Analysis feasible nếu scoped là parameterized SQL (không phải open-ended LLM modeling)
  - pg_ivm chỉ viable trên self-managed PostgreSQL

  Cần validate thêm:
  - Cube.dev vs custom YAML: trade-off cụ thể cho PostgreSQL setup
  - KPI Tree automatic drill-down: cần schema design phù hợp trước

  ---
  Kết luận: Positioning DA Agent Lab

  Honest claim (interview-ready):
  ▎ "Built a production-pattern Agentic Analytics system với semantic layer, multi-stage SQL validation,
  verified query repository, và structured data storytelling — aligned với kiến trúc của Snowflake Cortex
  Analyst và Databricks Genie."