---
name: time-series-query
description: Use ONLY when the user explicitly types `/dhara:time-series-query` or selects this Skill from the picker to query or aggregate Dhara's time-series records. Do not auto-trigger. Routes through `mcp__dhara__dhara_query_time_series` and `mcp__dhara__dhara_aggregate_patterns` to fetch metric records for a (metric_type, entity_id) tuple and surface aggregation patterns across the time-series corpus.
allowed-tools: mcp__dhara__dhara_query_time_series, mcp__dhara__dhara_aggregate_patterns, mcp__dhara__dhara_record_time_series, Read
---

# time-series-query

## When to use

This Skill is the right entry point when the user wants to read back
metric data Dhara has ingested via `mcp__dhara__dhara_record_time_series`
or analyze repeating shapes in the time-series corpus. Common cases:

- "Show me the last 50 routing-fitness signals for akosha."
- "What patterns repeat in the last 7 days of error_rate records?"
- "How many time-series points are stored for the `akosha` entity?"
- "Aggregate patterns across metric_type=cache_hit for the past week."

The Skill drives `mcp__dhara__dhara_query_time_series` for direct
read-back and `mcp__dhara__dhara_aggregate_patterns` for corpus-wide
shape analysis.

## What `dhara_query_time_series` returns

The tool accepts `(metric_type, entity_id, start_date=None, limit=None)`
and returns a list of records ordered by timestamp descending:

```json
[
  {
    "metric_type": "routing_fitness",
    "entity_id": "akosha",
    "timestamp": "2026-09-08T12:34:56Z",
    "record": {"failure_rate": 0.02, "p99_latency": 0.42, "sample_count": 1024}
  }
]
```

- `start_date`: ISO date string (`"2026-09-01"` or
  `"2026-09-01T00:00:00Z"`). When omitted, the query returns the
  full stored history up to `limit`.
- `limit`: cap on returned rows. Defaults vary by retention window;
  always pass an explicit `limit` for predictable batches.
- `record`: an opaque dict whose schema is up to the producer.
  Different `metric_type` values may carry different keys.

The records are append-only; there is no update-in-place. If the
producer wrote a typo, the right fix is to write a corrective record
and surface both in the read-back.

## Aggregation patterns

For "what shapes repeat in the corpus?" questions, use
`mcp__dhara__dhara_aggregate_patterns(start_date, min_occurrences=2)`.
This tool walks every time-series record from `start_date` onward,
groups records by `(metric_type, sorted(record.keys()))`, and returns
patterns that occur at least `min_occurrences` times.

```json
[
  {
    "metric_type": "routing_fitness",
    "record_keys": ["failure_rate", "p99_latency", "sample_count"],
    "occurrences": 1024,
    "distinct_entity_ids": 5,
    "first_seen": "2026-08-01T00:00:00Z",
    "last_seen": "2026-09-08T12:34:56Z"
  }
]
```

- `record_keys`: the sorted set of keys in `record`. If two producers
  wrote the same metric with different key orderings, the aggregate
  still treats them as the same pattern (sort is canonical).
- `occurrences`: how many records match this `(metric_type,
  record_keys)` shape. Compare against `distinct_entity_ids` to spot
  per-entity noise versus cross-entity systemic shape.
- `first_seen` / `last_seen`: lifecycle timestamps — useful for
  detecting "this shape appeared suddenly last Tuesday".

## When to use which

- **Direct query**: the user wants specific records for one
  `(metric_type, entity_id)`. Reach for `dhara_query_time_series`
  first.
- **Pattern analysis**: the user wants to know what shapes exist
  across the corpus. Reach for `dhara_aggregate_patterns` first.
- **Combined**: surface the top 5 patterns, then drill into the most
  common one with a direct query. This is the standard "give me an
  overview, then narrow" flow.

## When NOT to use

- For raw key/value records (not time-series), use
  `mcp__dhara__dhara_get` / `mcp__dhara__dhara_list_prefix`.
- For routing-fitness analytics with selector-level breakdowns, use
  Akosha's `mcp__akosha__akosha_run_fitness_analysis` (it pulls
  traces directly rather than reading Dhara's pre-aggregated signals).
- For real-time metrics (last 60s, not historical), reach for the
  Prometheus / Grafana surfaces, not Dhara's stored records.

## Failure modes

- **Empty list returned**: either the `(metric_type, entity_id)` pair
  has no records OR `start_date` is in the future. Surface both
  possibilities to the user.
- **Pattern aggregation returns zero patterns**: the corpus has
  fewer than `min_occurrences` records for any consistent shape.
  Lower `min_occurrences` to 1 for a noisy preview.
- **`record` schema drift**: aggregate_patterns reports the same
  `metric_type` with multiple `record_keys` shapes. Surface this as a
  producer-side contract violation; the Skill can't auto-repair.

## Example flow

User: "What patterns repeat in the last 7 days of routing-fitness
records?"

Skill action:

```python
import datetime

seven_days_ago = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()

patterns = await mcp__dhara__dhara_aggregate_patterns(
    start_date=seven_days_ago, min_occurrences=10,
)
# patterns is a list of {metric_type, record_keys, occurrences, ...}
top = sorted(patterns, key=lambda p: p["occurrences"], reverse=True)[:3]

# Drill into the most common pattern with a direct query
if top:
    sample = await mcp__dhara__dhara_query_time_series(
        metric_type=top[0]["metric_type"],
        entity_id="akosha",  # or pick from distinct_entity_ids
        start_date=seven_days_ago,
        limit=10,
    )
```

Synthesize: top-3 pattern summary, then a 10-row sample for the most
common pattern with a one-line interpretation of the `record` keys.