# Manual SQL Smoke Test
Date: 2026-03-29 23:35:18

Total queries: 10

## Case 1
- Query: DAU 7 ngày gần đây như thế nào?
- Intent: sql
- Confidence: high
- Has SQL: True
- Tools: route_intent, get_schema, generate_sql, validate_sql, query_sql, analyze_result
- Answer preview: Latest DAU=13015 vs previous=12780

## Case 2
- Query: Revenue 7 ngày gần đây có giảm không?
- Intent: sql
- Confidence: high
- Has SQL: True
- Tools: route_intent, get_schema, generate_sql, validate_sql, query_sql, analyze_result
- Answer preview: Average revenue over 7 rows is 5346.14

## Case 3
- Query: Top 5 video có retention cao nhất
- Intent: sql
- Confidence: high
- Has SQL: True
- Tools: route_intent, get_schema, generate_sql, validate_sql, query_sql, analyze_result
- Answer preview: Top retention video is 'Beginner Guide' with retention_rate=53.00%

## Case 4
- Query: Cho tôi số DAU mỗi ngày trong 7 ngày qua
- Intent: sql
- Confidence: high
- Has SQL: True
- Tools: route_intent, get_schema, generate_sql, validate_sql, query_sql, analyze_result
- Answer preview: Latest DAU=13015 vs previous=12780

## Case 5
- Query: Trung bình revenue 7 ngày gần đây
- Intent: sql
- Confidence: high
- Has SQL: True
- Tools: route_intent, get_schema, generate_sql, validate_sql, query_sql, analyze_result
- Answer preview: Average revenue over 7 rows is 5346.14

## Case 6
- Query: Video nào retention cao nhất hiện tại?
- Intent: sql
- Confidence: high
- Has SQL: True
- Tools: route_intent, get_schema, generate_sql, validate_sql, query_sql, analyze_result
- Answer preview: Latest DAU=13015 vs previous=12780

## Case 7
- Query: So sánh DAU 2 ngày gần nhất
- Intent: sql
- Confidence: high
- Has SQL: True
- Tools: route_intent, get_schema, generate_sql, validate_sql, query_sql, analyze_result
- Answer preview: Latest DAU=13015 vs previous=12780

## Case 8
- Query: Cho biết trend revenue gần đây
- Intent: sql
- Confidence: high
- Has SQL: True
- Tools: route_intent, get_schema, generate_sql, validate_sql, query_sql, analyze_result
- Answer preview: Latest DAU=13015 vs previous=12780

## Case 9
- Query: Lấy bảng daily_metrics 7 ngày gần nhất
- Intent: sql
- Confidence: high
- Has SQL: True
- Tools: route_intent, get_schema, generate_sql, validate_sql, query_sql, analyze_result
- Answer preview: Latest DAU=13015 vs previous=12780

## Case 10
- Query: Top retention videos từ dữ liệu hiện có
- Intent: sql
- Confidence: high
- Has SQL: True
- Tools: route_intent, get_schema, generate_sql, validate_sql, query_sql, analyze_result
- Answer preview: Top retention video is 'Beginner Guide' with retention_rate=53.00%
