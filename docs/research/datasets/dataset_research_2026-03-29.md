# Dataset Research For DA Agent Lab
Cập nhật: 2026-03-29

## 1) Mục tiêu chọn dataset cho project này
- Dùng để chạy local-first demo (`SQLite`), không phụ thuộc hạ tầng đắt tiền.
- Bao phủ đủ 3 nhóm câu hỏi: `sql`, `rag`, `mixed`.
- Có thể benchmark hành vi agent (routing, SQL validity, tool path), không chỉ benchmark model thuần.
- License rõ ràng để đưa vào portfolio/interview.

## 2) Đánh giá nhanh trạng thái project hiện tại
- Hiện có schema seed nhỏ: `daily_metrics`, `videos`, `metric_definitions`.
- Chưa có `evals/cases.json`.
- SQL path đã chạy end-to-end, nhưng chưa có benchmark dataset chuẩn để đo hồi quy.

=> Nhu cầu thực tế: cần 1 bộ dữ liệu vận hành local + 1 bộ benchmark Text-to-SQL + 1 bộ eval behavior nội bộ.

## 3) Dataset đề xuất (ưu tiên triển khai)

### A. Bộ dữ liệu vận hành local cho agent (khuyến nghị dùng ngay)
1. UCI Online Retail II
- Vai trò: nguồn transaction thực để dựng `daily_metrics` và `campaigns` (nếu thêm bảng).
- Điểm mạnh: dữ liệu bán lẻ chuẩn business, đủ để tạo câu hỏi trend/top-k/compare.
- License: `CC BY 4.0` (dễ dùng cho portfolio).
- Gợi ý mapping:
  - `InvoiceDate` -> `date`
  - doanh thu ngày = `SUM(Quantity * UnitPrice)` -> `revenue`
  - active users ngày = `COUNT(DISTINCT Customer ID)` -> gần tương đương `dau`

2. MovieLens 32M (hoặc `latest-small` cho máy yếu)
- Vai trò: dựng bảng `videos` tương tự content analytics.
- Điểm mạnh: dữ liệu lớn, ổn định cho benchmark truy vấn top-k và retention-like proxy.
- Gợi ý mapping:
  - `movieId` -> `video_id`
  - `title` -> `title`
  - `ratings` aggregate -> proxy `views/watch_time/retention_rate`
- Lưu ý: GroupLens nhấn mạnh đọc kỹ README/license trước khi redistribute.

3. GA4 obfuscated sample ecommerce (BigQuery public)
- Vai trò: nguồn event-level để tạo câu hỏi DAU/session/revenue theo ngày và mixed (SQL + caveat).
- Điểm mạnh: data gần thực tế sản phẩm số, có caveat rõ do obfuscation.
- Lưu ý: cần BigQuery project (Sandbox/free tier đủ để khám phá), sau đó export subset về SQLite.

### B. Bộ benchmark Text-to-SQL (đo năng lực query generation/validation)
1. Spider 1.0
- Baseline bắt buộc để so sánh với paper/cộng đồng.
- Phù hợp để benchmark routing `sql` + SQL generation correctness trên schema lạ.

2. BIRD Mini-Dev (500 samples)
- Phù hợp cho bối cảnh business SQL khó hơn Spider 1.0.
- Có SQLite/MySQL/PostgreSQL, có metric hiệu năng (Soft-F1, R-VES).

3. LiveSQLBench Base-Lite-SQLite
- Hợp với hướng agentic workflow mới (nhiều bước, tài liệu knowledge base đi kèm).
- Dùng để stress-test nhánh `mixed` và khả năng xử lý context dài.

### C. Dữ liệu cho phần RAG/eval behavior
1. Dùng docs nội bộ project (đã có/đang có)
- `docs/research/rag/metric_definitions.md`, `docs/research/rag/retention_rules.md`, `docs/research/rag/revenue_caveats.md`, `docs/research/rag/data_quality_notes.md`.
- Sinh bộ Q&A vàng để đo groundedness + citation.

2. Bổ sung semantic examples từ dbt ecosystem
- `dbt-labs/jaffle_shop_metrics` (ví dụ metric definitions).
- `dbt-labs/jaffle-shop-generator` (synthetic CSV để mở rộng scenario).

## 4) Gói triển khai khuyến nghị cho repo này (thực dụng nhất)
- `Core data (SQLite)`: UCI Online Retail II + MovieLens latest-small.
- `Benchmark SQL`: Spider 1.0 + BIRD Mini-Dev.
- `Benchmark agentic/mixed`: LiveSQLBench Base-Lite-SQLite (giai đoạn sau khi RAG hoàn tất).

Lý do chọn:
- Triển khai nhanh, không khóa vào cloud từ đầu.
- Có cả benchmark "chuẩn học thuật" (Spider/BIRD) và benchmark agentic mới (LiveSQLBench).
- Bao phủ đúng định hướng project: explainable, observable, measurable.

## 5) Kế hoạch dựng evaluation dataset trong `evals/`
1. Tạo `evals/cases.json` với 60 case đầu:
- 24 SQL (40%)
- 18 RAG (30%)
- 18 Mixed (30%)

2. Nguồn sinh case:
- SQL: từ các truy vấn aggregate/trend/top-k trên Retail + MovieLens-derived tables.
- RAG: từ docs metric/caveat/rule nội bộ.
- Mixed: ghép câu hỏi số liệu + định nghĩa/caveat (vd retention giảm + cách tính metric).

3. Mỗi case giữ format:
- `id`, `query`, `expected_intent`, `expected_tools`, `should_have_sql`, `expected_keywords`.

4. Metrics tối thiểu cần log:
- routing accuracy
- SQL validity rate
- tool-path accuracy
- answer format validity
- latency + step count

## 6) Rủi ro và cách xử lý
- Rủi ro 1: dữ liệu thực không có cột giống hệt schema demo.
  - Cách xử lý: tạo lớp chuẩn hóa (`staging`) để map về schema chuẩn project.
- Rủi ro 2: benchmark quá nặng khi chạy local.
  - Cách xử lý: dùng tier dataset (`small`, `medium`, `full`) và mặc định chạy `small`.
- Rủi ro 3: overfit prompt vào 1 schema.
  - Cách xử lý: dùng Spider/BIRD để test cross-schema định kỳ.

## 7) Ưu tiên thực thi đề xuất
1. Ngay bây giờ:
- ingest UCI Retail + generate `daily_metrics` thật.
- tạo `evals/cases.json` v1 (60 cases) theo tỉ lệ 40/30/30.

2. Ngắn hạn:
- ingest MovieLens latest-small để mở rộng câu hỏi top-k/ranking.
- chạy benchmark Spider 1.0 dev subset cho SQL generation.

3. Sau khi hoàn tất RAG path:
- thêm BIRD Mini-Dev và LiveSQLBench Base-Lite-SQLite cho regression benchmark.

## 8) Nguồn tham khảo
- UCI Online Retail II: https://archive.ics.uci.edu/dataset/502/online+retail+ii
- Spider 1.0: https://yale-lily.github.io/spider
- Spider repo: https://github.com/taoyds/spider
- BIRD benchmark: https://bird-bench.github.io/
- LiveSQLBench: https://livesqlbench.ai/
- MovieLens datasets: https://grouplens.org/datasets/movielens/
- MovieLens 32M: https://grouplens.org/datasets/movielens/32m/
- GA4 ecommerce sample (BigQuery): https://developers.google.com/analytics/bigquery/web-ecommerce-demo-dataset
- dbt jaffle-shop: https://github.com/dbt-labs/jaffle-shop
- dbt jaffle_shop_metrics: https://github.com/dbt-labs/jaffle_shop_metrics
- dbt jaffle-shop-generator: https://github.com/dbt-labs/jaffle-shop-generator
