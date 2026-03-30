# Data Quality Notes

## Scope
- Dataset in this project is local demo data, not production-grade telemetry.
- Tables are refreshed by seed script, so backfills and late-arriving records are not represented.

## Known caveats
- `daily_metrics` is daily-level aggregate only, no user-level granularity.
- `retention_d1` in demo data is a simplified ratio and may differ from real product definitions.
- `revenue` is synthetic and does not separate gross/net or channel attribution.
- `videos.retention_rate` is a single summary metric, not a full retention curve.

## Query interpretation guidance
- Trend results should be read as directional signals, not causal proof.
- Sudden day-to-day spikes may come from seed data shape, not real-world events.
- For mixed questions, SQL outputs should be combined with business caveats before decision-making.

## Usage in agent
- This document is part of RAG corpus.
- Retrieval should surface caveats when user asks "why", "do đâu", "có thể do gì", or asks for reliability/definition context.
