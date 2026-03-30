# Eval Report

- Total cases: 44
- Routing accuracy: 0.9773
- Tool-path accuracy: 0.8636
- SQL validity rate: 0.8864
- Answer format validity: 1.0
- Groundedness pass rate: 0.2045
- Average groundedness score: 0.5235
- Average latency (ms): 4400.65
- Spider execution match: 0.5714

## By Suite
### domain
- count: 36
- routing_accuracy: 1.0
- tool_path_accuracy: 0.8611
- sql_validity_rate: 0.8889
- answer_format_validity: 1.0
- groundedness_pass_rate: 0.0556
- avg_groundedness_score: 0.4204
- avg_latency_ms: 4395.11

### spider
- count: 8
- routing_accuracy: 0.875
- tool_path_accuracy: 0.875
- sql_validity_rate: 0.875
- answer_format_validity: 1.0
- groundedness_pass_rate: 0.875
- avg_groundedness_score: 0.9875
- avg_latency_ms: 4425.58

## Failure Buckets
- HALLUCINATION_RISK: 30
- SQL_VALIDATION_ERROR: 4
- ROUTING_ERROR: 1
- SQL_EXECUTION_ERROR: 3

Per-case JSONL: `evals/reports/per_case.jsonl`
