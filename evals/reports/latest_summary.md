# Eval Report

- Total cases: 44
- Routing accuracy: 0.9773
- Tool-path accuracy: 0.7955
- SQL validity rate: 0.8182
- Answer format validity: 1.0
- Average latency (ms): 2225.26
- Spider execution match: 0.0

## By Suite
### domain
- count: 36
- routing_accuracy: 1.0
- tool_path_accuracy: 0.9722
- sql_validity_rate: 1.0
- answer_format_validity: 1.0
- avg_latency_ms: 2226.56

### spider
- count: 8
- routing_accuracy: 0.875
- tool_path_accuracy: 0.0
- sql_validity_rate: 0.0
- answer_format_validity: 1.0
- avg_latency_ms: 2219.46

## Failure Buckets
- TOOL_PATH_MISMATCH: 1
- SQL_VALIDATION_ERROR: 7
- ROUTING_ERROR: 1

Per-case JSONL: `evals\reports\per_case.jsonl`
