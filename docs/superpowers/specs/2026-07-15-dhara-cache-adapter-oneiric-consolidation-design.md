# Dhara Cache-Adapter Oneiric Consolidation Design

**Date:** 2026-07-15
**Status:** Draft (awaiting user review)
**Author:** Claude (Mahavishnu Orchestrator, brainstorming session)
**Purpose:** Remove Dhara's parallel cache-adapter implementations
(`dhara.storage.redis_cache`, `dhara.storage.memory`) and consolidate on Oneiric's
canonical cache adapters. Pin all design decisions so the implementing plan and
PR are unambiguous.

______________________________________________________________________

## Context

Dhara currently ships two cache-adapter implementations in
`dhara/storage/{redis_cache.py, memory.py}` that duplicate what
`oneiric.adapters.cache.{RedisCacheAdapter, MemoryCacheAdapter}` already provide,
and what `oneiric.adapters.cache.MultiTierCacheAdapter` can stack on top of.
The duplicates exist because the historical `dhruva`-derived compat layer
explicitly removed diskcache support (`dhruva-compat-20260217_043710/dhruva/compat/__init__.py`,
line 8: *"diskcache compatibility was removed due to security concerns with the
upstream library's use of unsafe pickle serialization"*), and Dhara built its
own to fill that gap without bringing in `diskcache` (which has the live
CVE-2025-69872 pickle-RCE).

Today the duplication costs:

- **Two unrelated Redis settings models** with overlapping but non-identical
  fields (Dhara's `RedisCacheSettings.redis_token` vs Oneiric's
  `username`/`password`/`ssl`).
- **Operational inconsistency** — the rest of the Bodai ecosystem uses Oneiric's
  adapter; Dhara is the odd one out.
- **Discovery bypass** — Dhara's MCP server already exposes cache adapters
  through its `registry.get_adapter("adapter", "cache", "redis")` MCP tool (per
  `tests/test_mcp_adapter_tools.py:317`), but Dhara's own runtime instantiates
  the local duplicate instead of looking up the canonical Oneiric adapter.

The Bodai ecosystem already has the discovery/push infrastructure needed for
canonical-cache-adapter adoption: `oneiric.adapters.dhara_pusher` writes
Oneiric adapters into Dhara via MCP, and Mahavishnu's `AdapterDiscovery`
reads them back through `enable_dhara_registry`. The infrastructure is in
place; the consolidation just has to use it.

______________________________________________________________________

## Design Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Sequencing: **wait for the in-flight `docs/2026-07-15-async-migration-cleanup.md` plan to merge before implementation starts.** | That plan edits the same `dhara/mcp/server_core.py` file. Parallel edits to the same file would guarantee merge friction. Cosmetic cost: latency. |
| D2 | Scope: **wire + delete the duplicates in the same PR.** | We own all consumers; back-compat aliases are not required. Closes the duplication at once. |
| D3 | Merge target: **direct merge to `main`** per Bodai pre-1.0 policy. No PR. | Project rule; consistent with the rest of the ecosystem. |
| D4 | Version bump: **minor** (`dhara` 0.12.1 → 0.13.0). Performed manually with `crackerjack`. | The deleted modules are not re-exported from `dhara/__init__.py`, so the documented public API is unchanged; only internal-path importers break. Minor is correct. |
| D5 | Auth mapping: **pass Oneiric's `RedisCacheSettings` through directly**. No Dhara-side `cache_redis_token` alias. | Operator's settings live where they should — Oneiric's settings model. Avoids a Dhara-specific subset. |
| D6 | TTL / stampede-jitter location: **add `ttl_seconds` and `stampede_jitter_ms` to `oneiric.adapters.cache.RedisCacheSettings` directly** (companion PR to Oneiric). | Knobs belong with the rest of the cache settings; subclassing would create a parallel-class hierarchy for two fields. |
| D7 | TrackingCache default: **on** (`enable_client_cache=True`). Operator-supplied `RedisCacheSettings` win. | Dhara's CLAUDE.md markets "read-heavy workloads with aggressive caching"; TrackingCache is a free win there. Default-on matches Oneiric's default. |
| D8 | `Connection.Cache` migration: **out of scope.** Spec is explicit it stays. | After reading `dhara/core/connection.py:841-955`, `Connection.Cache` is a domain-specific Persistent-object LRU with `get_instance(oid, klass, connection)`, transaction-serial-aware eviction, and hard-reference invalidation. Oneiric's generic `MemoryCacheAdapter` does not satisfy those semantics; a swap would change the algorithm, not the implementation. A separate spec may define a `PersistentObjectCacheAdapter` later. |
| D9 | MCP-server cache lookup: **registry-mediated via `dhara/mcp/adapter_lookup.py:resolve_cache_adapter(backend)`**. | Dhara already has `AdapterRegistry` / `AsyncAdapterRegistry` and an MCP `adapter` tool that demonstrates registry lookup is the ecosystem pattern. Operator overrides should work without Dhara code changes. |
| D10 | MCP-server cache adapter instantiation: **fail-loud on init failure**; degrade-graceful on TrackingCache-unsupported server. | Cache infra is non-critical for reads — degraded read throughput beats no reads. Operators who want strict can opt in via a config knob. |
| D11 | Back-compat: **none.** No deprecated aliases. | We own all consumers. |
| D12 | Companion Oneiric PR **lands first**, then the main Dhara PR. | The main Dhara PR's `resolve_cache_adapter` references the new fields; out-of-order landing would break the build. |

______________________________________________________________________

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Mahavishnu (and any future Bodai component)                                  │
│   - AdapterDiscovery(config)                                                  │
│     pulls from Dhara registry via enable_dhara_registry                      │
└────────────────────────┬────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Dhara (the consumer; also the ecosystem adapter registrar)                   │
│                                                                             │
│  dhara/mcp/server_core.py:197-212 (current cache_backend switch)             │
│   ─ cache_backend="memory" ──► resolve_cache_adapter("memory")                │
│   ─ cache_backend="redis"  ──► resolve_cache_adapter("redis")                 │
│                                                                             │
│  dhara/core/connection.py:841 class Cache  ← UNTOUCHED, out of scope        │
│                                                                             │
│  dhara/mcp/adapter_lookup.py  (NEW)                                          │
│   ─ async resolve_cache_adapter(backend, settings, registry) -> CacheAdapter │
└────────────────────────┬────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Oneiric (the canonical cache adapter owner)                                  │
│                                                                             │
│  oneiric/adapters/cache/redis.py  (companion PR adds ttl_seconds +           │
│                                    stampede_jitter_ms to RedisCacheSettings)│
│  oneiric/adapters/cache/memory.py                                             │
│  oneiric/adapters/cache/multitier.py                                          │
└────────────────────────────────────────────────────────────────────────────┘
```

Three boundaries, one direction of dependency: `Mahavishnu → Dhara → Oneiric`,
same direction the existing `dhara_pusher` already writes in.

______________________________________________________________________

## Companion PR to Oneiric (lands FIRST)

A single additive PR against `oneiric/adapters/cache/redis.py`. Two changes:

### A. Settings fields

```python
class RedisCacheSettings(BaseModel):
    # ... existing fields ...
    ttl_seconds: int = Field(
        default=3600,
        ge=0,
        description="Optional TTL in seconds applied at every set(); 0 disables.",
    )
    stampede_jitter_ms: int = Field(
        default=0,
        ge=0,
        description="Optional random sleep (ms) applied when a cache miss occurs, "
                    "to dampen thundering-herd on hot keys.",
    )
    fail_fast_on_tracking_unavailable: bool = Field(
        default=False,
        description="If True, raise at first TrackingCache failure. If False, "
                    "log a structured warning, disable TrackingCache for the "
                    "lifetime of the adapter, and continue serving cache reads.",
    )
```

### B. Adapter behavior (TrackingCache degrade-graceful)

Wrap the existing TrackingCache call site inside `RedisCacheAdapter.get()` and
similar reads so that when `coredis.exceptions.RedisError` is raised and the
error message contains "TRACKING" (or analogous marker), the adapter logs via
`get_logger("adapter.cache.redis")` with structured fields and sets
`self._tracking_enabled = False` for subsequent calls. The exact trigger
phrase and call site are implementation details during planning.

```python
# Sketch only — exact placement decided at implementation time.
async def get(self, key: str) -> Any | None:
    if self._settings.enable_client_cache and self._tracking_enabled:
        try:
            return await self._client.tracking_get(key)
        except RedisError as exc:
            if "TRACKING" not in str(exc):
                raise
            self._logger.warning(
                "tracking-cache-unsupported",
                backend="cache",
                provider="redis",
                error=str(exc),
            )
            self._tracking_enabled = False
            if self._settings.fail_fast_on_tracking_unavailable:
                raise LifecycleError("tracking-cache-unsupported") from exc
    return await self._client.get(key)
```

This change belongs in **Oneiric** (not Dhara) because TrackingCache
degrade-graceful should behave the same for every consumer of
`RedisCacheAdapter`, not only Dhara.

### Companion tests under `oneiric/tests/unit/test_redis_cache_settings.py` (new)

- `test_default_ttl_seconds_is_3600` — round-trip default.
- `test_default_stampede_jitter_ms_is_zero`.
- `test_default_fail_fast_on_tracking_unavailable_is_false`.
- `test_negative_ttl_seconds_rejected` — Pydantic ValidationError.
- `test_negative_stampede_jitter_ms_rejected`.
- Sanity: existing fields (`url`, `host`, `port`, `username`, `password`, `ssl`,
  `socket_timeout`, `client_name`, `healthcheck_timeout`, `decode_responses`,
  `key_prefix`, `enable_client_cache`, `client_cache_max_keys`,
  `client_cache_max_size_bytes`, `client_cache_max_idle_seconds`) round-trip
  unchanged.

### Companion tests under `oneiric/tests/unit/test_redis_cache.py` (extend existing)

- `test_tracking_cache_unsupported_degrades_gracefully` — fake coredis client
  that raises `RedisError("CLIENT TRACKING not supported")` on `tracking_get`
  triggers the warn-and-disable branch once; subsequent reads continue.
- `test_tracking_cache_unsupported_fail_fast_when_configured` — same setup,
  but with `fail_fast_on_tracking_unavailable=True` and `enable_client_cache=True`,
  raises `LifecycleError` on first call.

______________________________________________________________________

## Main PR to Dhara

### Modified

| File | Change |
|---|---|
| `dhara/mcp/adapter_lookup.py` (NEW) | A small async helper: `resolve_cache_adapter(backend: Literal["memory","redis"], settings, registry) -> CacheAdapter`. Centralizes the lookup pattern so `server_core.py` stays readable. ~30 lines. |
| `dhara/mcp/server_core.py` (lines 197-212) | Replace `cache_backend` switch with a call to `resolve_cache_adapter`. Drop the imports from `dhara.storage.redis_cache`. Read `OneiricMCPConfig.adapters.cache.{memory,redis}.settings` for operator-supplied settings; fall back to constructed defaults if not set. Add a structured log line `cache-adapter-resolved` with `(backend, provider, settings_class)`. |
| `dhara/core/config.py` | Drop the `cache_redis_url`, `cache_redis_token`, `cache_ttl`, `cache_stampede_jitter_ms`, `cache_key_prefix` fields. Keep `cache_backend: str = Field(default="memory", description="memory or redis")`. Cache settings now live in `OneiricMCPConfig.adapters.cache.{memory,redis}.settings` (canonical Oneiric location). |
| `dhara/tests/unit/test_adapter_lookup.py` (NEW) | See "Test strategy" below. |
| `dhara/tests/unit/test_server_core_cache.py` (NEW) | End-to-end through `server_core.py`. |
| `dhara/tests/unit/test_server_core.py` | Switch patch target from `dhara.storage.redis_cache.RedisCacheAdapter` to the new `dhara.mcp.adapter_lookup.resolve_cache_adapter` helper. |
| `dhara/tests/unit/test_dhara_settings.py` | Drop tests for removed config fields; keep the `cache_backend == "memory"` default test. |

### Deleted

| File | Reason |
|---|---|
| `dhara/storage/redis_cache.py` | Replaced by `oneiric.adapters.cache.RedisCacheAdapter`. Not in `dhara/__init__.py` public exports. |
| `dhara/storage/memory.py` | Replaced by `oneiric.adapters.cache.MemoryCacheAdapter`. |
| `dhara/tests/unit/test_redis_cache.py` | Tests the deleted Dhara class. Coverage moves to `test_server_core_cache.py`. |
| `dhara/tests/unit/test_memory_cache.py` if it exists | Same. |

### Explicitly NOT touched

| File / symbol | Why |
|---|---|
| `dhara/core/connection.py:841 class Cache` | Out of scope (see D8). Documented as domain-specific Persistent-object LRU; if a future spec wants to consolidate, it must define a `PersistentObjectCacheAdapter` in Oneiric first. |
| `dhara/tests/benchmarks/test_cache.py` | The benchmark measures `Connection.get_root()['key']` perf. With `Connection.Cache` unchanged, the bench still validates the same thing. Run unchanged; treat >2× regression as a rollback signal. |
| `oneiric/adapters/dhara_pusher.py` | Already pushes Oneiric → Dhara at startup. Once the companion PR adds the two new fields, this code continues to work without edits. |
| `dhara/storage/postgres.py`, `dhara/storage/sqlite.py` | Storage adapters, not cache. Out of scope. |

______________________________________________________________________

## Data Flow & Lifecycle

### Startup

```
oneiric.config.load_oneiric_config()  →  OneiricMCPConfig
                                          │
                                          ▼
        OneiricMCPConfig.adapters.cache.{memory,redis}.settings
                                          │
                                          ▼
              Dhara mcp/server_core.py:__init__
                                          │
                config.cache_backend == "memory" | "redis"
                                          │
                                          ▼
                dhara/mcp/adapter_lookup.py:resolve_cache_adapter(backend, settings, registry)
                                          │
                            ├── construct MemoryCacheAdapter(MemoryCacheSettings())
                            │      or
                            └── construct RedisCacheAdapter(RedisCacheSettings(ttl_seconds=..., stampede_jitter_ms=...))
                                          │
                                          ▼
                                    await adapter.init()
                                          │
                  (Redis: ping + TrackingCache setup; Memory: log only)
                                          │
                                          ▼
                                     self.cache
```

### Steady state (per-MCP-request)

```
some MCP tool: await self.cache.get("key")
  ├─ Redis:  coredis.client.get(key)
  │           ├─ TrackingCache hit (within window)   →  local, no round-trip
  │           └─ TrackingCache miss (or disabled)    →  round-trip
  └─ Memory: async with self._lock: return self._store.get(key)
                                       └─ TTL purges on access (lazy)
```

### Shutdown

```
server.cleanup()
   └─ await self.cache.cleanup()
        ├─ Redis:  coredis.Redis.aclose()
        └─ Memory: async with self._lock: self._store.clear()
```

______________________________________________________________________

## Error Handling & Failure Modes

| Failure | Surfaced as | Operator action |
|---|---|---|
| No cache adapter registered | `LifecycleError("cache adapter not registered for backend={backend}")` raised by `resolve_cache_adapter`; server fails to start. | Reinstall Oneiric with `[cache]` extras, or register a custom adapter at startup. |
| Missing URL with `cache_backend=redis` | Caught at `await adapter.init()`; bubbles as `coredis.RedisError`; server fails to start. | Set `url` (or `host`/`port`) in operator's `RedisCacheSettings`. |
| Redis unreachable | Bubbles from `await client.ping()`; server fails to start. | Verify Redis URL/auth/network. |
| Redis 5 / restricted provider rejects `CLIENT TRACKING` | Caught at first `await client.get(...)` (lazy, not at init). After **D10** degrade-gracefully: log a structured warning (`tracking-cache-unsupported` with `(provider, backend, redis_version)`), disable TrackingCache for the lifetime of the adapter, continue serving cache reads. Operators who want strict fail-loud set `cache_fail_fast_on_tracking_unavailable=True` in `OneiricMCPConfig`. | Either upgrade Redis, or set the fail-fast knob. |
| `ttl_seconds: -1` or `stampede_jitter_ms: -1` | `pydantic.ValidationError` at config load; server fails to start with the existing Oneiric config loader error format. | Fix the config value. |
| `Connection.Cache` regressions | Should not occur — out of scope. | Bench `dhara/tests/benchmarks/test_cache.py` is the regression guard (see Integration Contract). |

> **D10 implementation sketch.** Oneiric's `RedisCacheAdapter` currently raises on
> TrackingCache failure. Degrade-gracefully will be implemented by wrapping the
> TrackingCache call site in `oneiric/adapters/cache/redis.py` — if the wrapping
> detects `coredis.exceptions.RedisError` with `CLIENT TRACKING` mentioned in
> the message, log via `get_logger("adapter.cache.redis").warning(...)` with
> structured fields, set `self._tracking_enabled = False`, and continue. The
> change belongs in Oneiric (so the behavior is consistent for every consumer,
> not only Dhara).

______________________________________________________________________

## Test Strategy

### New tests

- **`dhara/tests/unit/test_adapter_lookup.py`** — `resolve_cache_adapter`:
  resolves `memory` and `redis`; raises `LifecycleError` on empty registry;
  constructed instances are the correct concrete classes; `init()` is awaited.
- **`dhara/tests/unit/test_server_core_cache.py`** — full-server-core path:
  `cache_backend=memory` wires `MemoryCacheAdapter`; `cache_backend=redis` wires
  `RedisCacheAdapter`; `enable_client_cache=False` propagates; tracking-cache
  degrade-graceful path exercised once via a fake coredis client that rejects
  `CLIENT TRACKING`.
- **`oneiric/tests/unit/test_redis_cache_settings.py`** — companion PR test
  suite covering `ttl_seconds`/`stampede_jitter_ms` defaults, boundary
  rejection, and an unchanged sanity round-trip for existing fields.

### Modified tests

- **`dhara/tests/unit/test_server_core.py`** — patch target switches from
  `dhara.storage.redis_cache.RedisCacheAdapter` to
  `dhara.mcp.adapter_lookup.resolve_cache_adapter`. Existing test bodies
  (assertions about `self.cache.get` etc.) remain valid because the adapter
  instances satisfy the same `CacheAdapter` protocol.
- **`dhara/tests/unit/test_dhara_settings.py`** — drop tests for removed
  fields; keep `cache_backend` default test.

### Deleted tests

- `dhara/tests/unit/test_redis_cache.py` (covers deleted
  `dhara.storage.redis_cache`).
- `dhara/tests/unit/test_memory_cache.py` if it exists.

### Regression guards

- `dhara/tests/benchmarks/test_cache.py` (the `Connection.Cache` benchmark)
  must pass with no edits. >2× regression = rollback signal.
- `dhara/tests/test_connection.py` (the `Connection` integration suite) must
  pass unchanged.

### Smoke test checklist (run before merge)

1. `dhara -s --file /tmp/smoke.dhara` with no Redis available → cache_backend=memory
   default → server starts, `/health` reports `cache=memory`, healthy.
2. With Redis available and `cache_backend=redis` → server starts,
   `/health` reports `cache=redis`.
3. Interactive `dhara -c --file /tmp/smoke.dhara` performs a get/set that
   touches cache. Structured logs emit `cache-adapter-resolved`,
   `adapter-init`, `adapter-cleanup-complete`.
4. `enable_client_cache=False` with a Redis-5-like server that rejects
   `CLIENT TRACKING` → degrade-graceful warning fires once; reads continue.
5. `pytest dhara/tests/ -v` green.
6. `python scripts/audit_orphans.py` reports zero recently-added symbols
   with zero callers.

______________________________________________________________________

## Integration Contract

Per CLAUDE.md "Process Discipline" — required for non-trivial features.

```
Triggered from:
  - Dhara MCP server startup (dhara/mcp/server_core.py:__init__)
  - Dhara MCP server tool invocations that read/write cache (existing paths)

Returns to / updates:
  - dhara.storage.redis_cache module: DELETED
  - dhara.storage.memory module: DELETED
  - dhara.core.config.cache_redis_url: DELETED
  - dhara.core.config.cache_redis_token: DELETED
  - dhara.core.config.cache_ttl: DELETED
  - dhara.core.config.cache_stampede_jitter_ms: DELETED
  - dhara.core.config.cache_key_prefix: DELETED
  - dhara.core.connection.Cache (and shrink / clear / get_instance): UNTOUCHED
  - oneiric.adapters.cache.RedisCacheSettings: +2 fields (companion PR)

Demonstrable by:
  - `pytest dhara/tests/unit/test_adapter_lookup.py dhara/tests/unit/test_server_core_cache.py -v` passes
  - `pytest dhara/tests/unit/test_server_core.py` passes (rebased patches)
  - `pytest dhara/tests/benchmarks/test_cache.py` within 2× baseline
  - Manual smoke: redis up & down, both modes served
  - `python scripts/audit_orphans.py` — no recently-added orphans

Rollback signal:
  - dhara -s fails with "cache adapter not registered" → restore oneiric +
    reinstall with [cache] extras
  - Cache reads fail with RedisError on every call → revert companion PR
    and main PR via `git revert`
  - Connection.Cache benchmark regresses by >2× → revert the dhara-side
    migration; re-enable dhara/storage/redis_cache.py from git history
  - Audit shows orphaned recently-added symbols → either wire them or
    remove them; per CLAUDE.md Process Discipline

Observability added:
  - Structured log `cache-adapter-resolved` at startup with
    (backend, provider, settings_class)
  - Inherits `adapter-init` and `adapter-cleanup-complete` from Oneiric's
    adapters (now actually wired in)
  - Dhara MCP /health endpoint reports cache health (existing path, now
    exercised against the new adapters)
  - TrackingCache-unsupported warning emitted once when degrade-graceful
    path triggers
  - Oneiric `RedisCacheAdapter` now has structured `tracking-cache-unsupported`
    warning that flows through Oneiric's existing `get_logger("adapter.cache.redis")`
    sink, with the same structured-field shape as other adapter events.

  Companion-Oneiric observability:
  - `get_logger("adapter.cache.redis").warning("tracking-cache-unsupported", ...)`
    fires once per adapter lifetime when degrade-graceful triggers.
```

______________________________________________________________________

## Preconditions / Start-Gate

Per decision **D1** and **D12**:

1. `docs/2026-07-15-async-migration-cleanup.md` must be merged to `main`
   before any of our code lands. Verify via `git log --oneline main | head -10`.
2. The companion Oneiric PR (single PR covering **both** the
   `ttl_seconds`/`stampede_jitter_ms`/`fail_fast_on_tracking_unavailable`
   settings additions *and* the TrackingCache degrade-graceful behavior in
   the adapter) must be merged to `main` *before* the main Dhara PR.
3. The main Dhara PR opens only after both (1) and (2) are merged, and
   merges direct to `main` per **D3** (no PR).
4. Version bump `dhara` 0.12.1 → 0.13.0 is performed manually via
   `crackerjack` after merge, per **D4**.

______________________________________________________________________

## Out of Scope

The following were considered and explicitly deferred:

- **`dhara.core.connection.Cache` consolidation.** Needs a
  `PersistentObjectCacheAdapter` in Oneiric first. Deferred to a separate
  spec.
- **A Dhara-native cache adapter backed by Dhara's own SQLite storage.**
  Would fill the "durable local cache" slot that originally motivated the
  diskcache question, but that motivation was a red herring once we mapped
  the cache duplication. Could be a separate spec.
- **MultiTier or L1/L2 cache composition.** `MultiTierCacheAdapter` already
  exists in Oneiric; Dhara's `cache_backend` config stays binary
  (`memory`/`redis`) for now. Operators who want composition can
  register a higher-priority custom adapter.
- **Hot reload of cache config.** Config loaded once at startup; no live
  adapter swap. Adding that is a feature on its own.

______________________________________________________________________

## Open Questions

None. All eight design decisions (D1-D8) plus D9-D12 are closed.

**Tracking question for reviewer (soft):** is the `cache_fail_fast_on_tracking_unavailable`
knob the right escape-hatch ergonomics, or would you prefer TwoState
env vars (`ONEIRIC_CACHE_FAIL_FAST_ON_TRACKING_UNAVAILABLE`) with explicit
matching in Oneiric's config loader?

______________________________________________________________________

## Notes for the implementation plan

When the implementation plan is written (per the brainstorming flow's next
step, invoking `superpowers:writing-plans`), it should:

- Number the steps so `Connection.Cache` benchmarks are run *before* any
  Dhara-side deletions, as a baseline.
- Sequence: Oneiric companion PR (single PR) → Dhara main PR (companion first).
- Phase 1: baseline `pytest dhara/tests/benchmarks/test_cache.py` recorded.
- Phase 2: companion Oneiric PR — settings fields + TrackingCache
  degrade-graceful behavior + companion tests. Land and verify green.
- Phase 3: Dhara main PR — `adapter_lookup.py`, `server_core.py` wiring,
  `core/config.py` cleanup, new tests, old test deletions. Re-run
  benchmarks; verify within 2× of baseline.
- Phase 4: `audit_orphans.py` clean. Manual smoke checklist signed off.
- Phase 5 (post-merge): manual `crackerjack` version bump
  (`dhara` 0.12.1 → 0.13.0) and publish.
