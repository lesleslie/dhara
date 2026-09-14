---
name: service-list
description: Use ONLY when the user explicitly types `/dhara:service-list` or selects this Skill from the picker to enumerate durable ecosystem service records in Dhara. Do not auto-trigger. Routes through `mcp__dhara__dhara_list_services` to apply service_type / capability / status filters, explains the pagination contract, and pairs with `mcp__dhara__dhara_get_service` for single-record drill-down.
allowed-tools: mcp__dhara__dhara_list_services, mcp__dhara__dhara_get_service, Read
---

# service-list

## When to use

This Skill is the right entry point when the user wants to enumerate
the durable ecosystem service records Dhara has persisted via
`mcp__dhara__dhara_upsert_service`. Common cases:

- "Which Bodai components are reporting a `healthy` status?"
- "List every service that advertises the `mcp-server` capability."
- "Show me all `agent-runtime` services regardless of status."
- "Are there any services whose lease has expired?"
- "Find every service registered by akosha in the last hour."

The Skill drives `mcp__dhara__dhara_list_services` with sensible
default filters and explains the pagination + filter contract so
large fleets stay responsive.

## What `dhara_list_services` returns

The tool accepts `(service_type=None, capability=None, status=None)`
and returns:

```json
{
  "ok": true,
  "count": 12,
  "services": [
    {
      "service_id": "akosha-main",
      "service_type": "intelligence",
      "capabilities": ["search", "fitness_analysis", "anomaly_detection"],
      "metadata": {"version": "0.15.1", "host": "localhost", "port": 8682},
      "status": "healthy",
      "lease_expires_at": "2026-09-08T13:00:00Z",
      "heartbeat_at": "2026-09-08T12:55:00Z",
      "registered_at": "2026-08-15T08:00:00Z",
      "last_updated": "2026-09-08T12:55:00Z"
    }
  ]
}
```

- `service_id`: globally unique. Convention is
  `<component>-<instance>`. The Skill uses this as the primary key
  for drill-down.
- `service_type`: a coarse taxonomy (`intelligence`, `storage`,
  `orchestrator`, `agent-runtime`, `mcp-server`, etc.).
- `capabilities`: free-form list. Producers may advertise anything;
  consumers should treat the list as a set, not a strict enum.
- `status`: `healthy` / `degraded` / `unhealthy` / `unknown`. The
  service updates this field on each heartbeat; stale values indicate
  the producer's heartbeat loop has stalled.
- `lease_expires_at`: wall-clock deadline after which Dhara will
  treat the record as stale. The Skill filters for `lease_expires_at
  < now()` when the user asks about liveness without explicitly
  asking.
- `heartbeat_at`: last producer-side heartbeat timestamp.

## Filter semantics

All three filters are **AND-combined** when supplied:

- `service_type="agent-runtime"`: matches records whose
  `service_type` exactly equals the given string.
- `capability="mcp-server"`: matches records whose `capabilities`
  list contains the given string (set-membership, not substring).
- `status="healthy"`: matches records whose `status` field exactly
  equals the given string.

Each filter accepts `None` (or omission), which disables that
constraint. The Skill always passes `status=None` unless the user
explicitly asked for a status filter — surprising the user with a
status-filtered list is a common foot-gun.

## Pagination

There is no cursor parameter on `dhara_list_services`; the tool
returns the full filtered result in one call. For fleets above a
few hundred records, the Skill recommends:

1. **Apply a filter** to reduce the working set. The combination of
   `service_type` + `capability` is usually enough to keep the
   result under 100 records.
2. **Read the `count` field** to know how big the unfiltered result
   would have been. If `count` is much larger than the filtered
   result, the user almost certainly wants a narrower filter.
3. **For fleet-wide enumeration**, page by `service_type` one at a
   time and aggregate client-side. The Skill does not assume the
   server has cursor support.

## Drill-down with `dhara_get_service`

For single-record questions ("tell me about `akosha-main`"), the
Skill calls `mcp__dhara__dhara_get_service(service_id)` rather than
filtering `list_services`. The `get` call returns:

```json
{
  "ok": true,
  "service": { /* same shape as one element of list_services */ }
}
```

The Skill prefers `get_service` over filtering when the user already
knows the `service_id`; it avoids the cost of materializing the full
list just to find one record.

## When NOT to use

- For OTel traces of service heartbeats, use the OTel ingester's
  `search_traces("service heartbeat")` call.
- For service-discovery via Akosha's intelligence layer, use
  `mcp__akosha__akosha_search_all_systems(query="service
  <name>")` — Akosha's hybrid retrieval is faster for fuzzy
  queries.
- For real-time liveness probes (sub-second freshness), use
  `mcp__dhara__dhara_health_check_service` instead — the lease
  model is heartbeat-driven and may lag reality by up to one
  heartbeat interval.

## Failure modes

- **`count: 0` with non-null filters**: no records match. Confirm
  the filter values with the user; a typo on `service_type` is the
  usual cause.
- **`lease_expires_at` in the past but `status: "healthy"`**: the
  producer's heartbeat loop has stalled. Surface this AND suggest
  the user restart the producer process.
- **`capabilities` field missing on older records**: pre-1.0 schema
  records may omit `capabilities`. The Skill treats the missing
  field as `[]` and reports "no capabilities advertised".

## Example flow

User: "Which MCP servers are healthy right now?"

Skill action:

```python
result = await mcp__dhara__dhara_list_services(
    service_type="mcp-server",
    status="healthy",
)
healthy = result["services"]

# Cross-check leases — a service with status=healthy but an expired
# lease is a stalled heartbeat, not a truly healthy service.
import datetime

now = datetime.datetime.now(datetime.UTC)
live = [
    s
    for s in healthy
    if datetime.datetime.fromisoformat(s["lease_expires_at"].replace("Z", "+00:00"))
    > now
]
```

Synthesize: list of healthy-and-live services with `service_id`,
`service_type`, and `last_updated`. If `live` is a strict subset of
`healthy`, surface the diff as "N services report healthy but have
expired leases — heartbeat stalls."
