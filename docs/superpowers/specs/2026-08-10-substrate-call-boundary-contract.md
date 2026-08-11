# Substrate Put/Get Boundary Contract

**Status:** Architectural decision (2026-08-10)
**Scope:** Cross-portfolio — applies to mahavishnu + session-buddy + crackerjack consumers of Dhara.

## Decision

The Dhara substrate's `put(key, validated)` and `get(key)` calls are
**synchronous at the call boundary**. They block until the durable record
is queued (put) or fetched (get), then return. Internal async behavior
(MemoryOutbox background flush, PostgresBackendLock conflict resolution)
is the substrate's concern and is invisible to callers.

## Implications for callers

- Producers may be `def` or `async def` per the call site's needs. The
  substrate does not require async.
- The FastMCP server requires `async def` for registered tools; that is
  a server concern, not a substrate concern. Tools that call sync
  `dhara.put`/`dhara.get` can wrap them in `async def` without changing
  the substrate contract.
- A substrate unbound at runtime (`dhara.put` is `None`) causes the
  producer's runtime gate (see substrate-compat pattern in
  `mahavishnu/core/approval/decision_writer.py:32-33`) to skip+warn, never
  raise. The G6 contract — substrate failures never reach the caller —
  remains the floor.
- Bounded-queue overflow on `put` is handled by the substrate
  (`dhara/audit/outbox.py`) as drop-oldest, surfaced via the G6 fallback
  log. Producers do not need to retry.

## Ratifiers

- M-APPROVAL-LOG completion report (`docs/feature-tracking/2026-08-10-m-approval-log.md`)
- M-WORKFLOW-OUTCOME completion report (`docs/feature-tracking/2026-08-10-m-workflow-outcome.md`)
- M-WEBHOOK-DURABLE completion report (`docs/feature-tracking/2026-08-10-m-webhook-durable.md`)
- S-CHANNEL-DURABLE completion report (`docs/feature-tracking/2026-08-10-s-channel-durable.md`)
- Multi-agent review (2026-08-10)
