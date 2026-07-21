______________________________________________________________________

## status: shipped role: canonical date: 2026-07-17 last_reviewed: 2026-07-17 superseded_by: null blocks_on: [] topic: adapter-architecture

# Dhara Cache-Adapter Oneiric Consolidation Design

**Date:** 2026-07-15
**Status:** Shipped (merged to Dhara `main`; see the companion implementation plan for commit range) <!-- legacy status — see YAML frontmatter -->
**Author:** Claude (Mahavishnu Orchestrator, brainstorming session)
**Purpose:** Remove Dhara's parallel `dhara.storage.redis_cache` adapter and
consolidate on Oneiric's canonical cache adapters. Ship **post-multi-agent
review** with corrected architectural decisions (the previous version of this
spec incorrectly targeted `dhara.storage.memory` for deletion, and proposed a
TrackingCache degrade-graceful feature against a fictional coredis API).

______________________________________________________________________

## Context

Dhara currently ships one parallel cache-adapter implementation in
`dhara/storage/redis_cache.py` that duplicates what
`oneiric.adapters.cache.RedisCacheAdapter` already provides. The
historical `dhruva`-derived compat layer explicitly removed diskcache support
(`dhruva-compat-20260217_043710/dhruva/compat/__init__.py:8` — *"diskcache
compatibility was removed due to security concerns with the upstream
library's use of unsafe pickle serialization"*), and Dhara built its own
adapter without bringing in diskcache (which now carries the live
CVE-2025-69872 pickle-RCE).

`dhara/storage/memory.py` is **not** a cache adapter — it is the generic
`AsyncMemoryStorage` storage backend, re-exported from
`dhara/storage/__init__.py:21` and used by 8+ tests across the async
storage layer. **It must not be deleted as part of this spec.**

Today the duplication costs:

- **Two unrelated Redis settings models** (Dhara's `RedisCacheSettings.redis_token` vs Oneiric's `username`/`password`/`ssl`).
- **Operational inconsistency** — the rest of the Bodai ecosystem uses Oneiric's adapter; Dhara is the odd one out.
- **Discovery bypass** — Dhara's MCP server already exposes cache adapters through its `registry.get_adapter("adapter", "cache", "redis")` MCP tool (per `tests/test_mcp_adapter_tools.py:317`), but Dhara's own runtime instantiates the local duplicate instead.

Multi-agent review found the following earlier-draft errors, all corrected here:

1. The earlier draft claimed `dhara/storage/memory.py` was a parallel cache adapter. **It is not.**
1. The earlier draft proposed a TrackingCache degrade-graceful feature that wrapped `self._client.tracking_get(...)` etc. **coredis has no such methods** — `TrackingCache` is a client-side LRU passed at `Redis(..., cache=TrackingCache(...))` construction; the proposed wrap targets a fictional API. The TrackingCache-degrade-graceful feature has been **dropped from scope**.
1. The earlier draft sourced cache settings from `OneiricMCPConfig().adapters.cache.redis.settings`. **That path does not exist** — `OneiricMCPConfig` has no `adapters` field. The corrected path is `OneiricSettings.load_settings(...).adapters.provider_settings.get("cache.redis", {})`.
1. The earlier draft's `resolve_cache_adapter` helper read `getattr(entry, "factory", None)` from a `dict`. **Real `AsyncAdapterRegistry.get_adapter_async` returns a `dict` with key `factory_path`**, not an object with `.factory`.
1. Oneiric's existing adapter `factory` strings have a **leading space** (`"…: RedisCacheAdapter"`) which would defeat any attempt to import them via `import_string`. A prerequisite Task 2.0 fixes this in Oneiric.
1. The earlier draft's `_wire_cache` reads `self._async_adapter_registry`, but the registry is initialized after the cache_backend block in `DharaMCPServer.__init__`. **The registry initialization must move ahead of the cache block.**

The Bodai ecosystem already has the discovery/push infrastructure needed for canonical-cache-adapter adoption: `oneiric.adapters.dhara_pusher` writes Oneiric adapters into Dhara via MCP, and Mahavishnu's `AdapterDiscovery` reads them back through `enable_dhara_registry`. The infrastructure is in place; the consolidation just has to use it correctly.

______________________________________________________________________

## Design Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Sequencing: **wait for the in-flight `docs/2026-07-15-async-migration-cleanup.md` plan to merge before implementation starts.** | That plan edits the same `dhara/mcp/server_core.py` file. Parallel edits to the same file would guarantee merge friction. |
| D2 | Scope: **wire + delete `dhara.storage.redis_cache` in the same PR.** | We own all consumers of the Dhara-side adapter; back-compat aliases are not required. **`dhara.storage.memory.py` is excluded** — it is `AsyncMemoryStorage`, a separate concern. |
| D3 | Merge target: **direct merge to `main`** per Bodai pre-1.0 policy. No PR. | Project rule; consistent with the rest of the ecosystem. |
| D4 | Version bump: **minor** (`dhara` 0.12.1 → 0.13.0). Performed manually with `crackerjack`. | The deleted module is not in `dhara/__init__.py` public exports, so the documented public API is unchanged; only internal-path importers break. Minor is correct. |
| D5 | Auth mapping: **pass Oneiric's `RedisCacheSettings` through directly**. No Dhara-side `cache_redis_token` alias. | Operator's settings live where they should — Oneiric's settings model. Avoids a Dhara-specific subset. |
| D6 | TTL / stampede-jitter location: **add `ttl_seconds` and `stampede_jitter_ms` to `oneiric.adapters.cache.RedisCacheSettings` directly, AND add consumer code in `set()` and `get()`**. | Companion to the prior decision: knobs live with the rest of the cache settings; their semantics must actually take effect (otherwise Dhara loses the TTL/stampede-jitter behavior it had before). |
| D7 | TrackingCache default: **on** (`enable_client_cache=True`). Operator-supplied `RedisCacheSettings` win. | Dhara's CLAUDE.md markets read-heavy workloads where TrackingCache is a free win. Default-on matches Oneiric's default. |
| D8 | `Connection.Cache` migration: **out of scope.** Spec is explicit it stays. | After reading `dhara/core/connection.py:841-955`, `Connection.Cache` is a domain-specific Persistent-object LRU with `get_instance(oid, klass, connection)`, transaction-serial-aware eviction, and hard-reference invalidation. Oneiric's generic `MemoryCacheAdapter` does not satisfy those semantics; a swap would change the algorithm, not the implementation. A separate spec may define a `PersistentObjectCacheAdapter` later. |
| D9 | MCP-server cache lookup: **registry-mediated via `dhara/mcp/adapter_lookup.py:resolve_cache_adapter(backend)`**. | Dhara already has `AdapterRegistry` / `AsyncAdapterRegistry` and an MCP `adapter` tool that demonstrates registry lookup is the ecosystem pattern. Operator overrides should work without Dhara code changes. |
| D10 | **`AsyncAdapterRegistry.get_adapter_async` returns `dict | None` with key `factory_path`.** `resolve_cache_adapter` reads `entry["factory_path"]` (not `.factory`). | Verified via `dhara/mcp/adapter_tools.py:894-924`. Earlier draft used `getattr(entry, "factory")` which always returned `None` against a real dict. |
| D11 | **Oneiric's adapter `factory` strings have a leading space** (`"…: RedisCacheAdapter"`). A prerequisite task in the companion Oneiric PR strips the leading space from both `redis.py` and `memory.py` `AdapterMetadata.factory` strings. | Without this, even a correct `resolve_cache_adapter` would fail with `AttributeError` at import time. |
| D12 | **Drop the TrackingCache-degrade-graceful feature from this spec.** TrackingCache stays on by default per D7; operators disable via config if it breaks. | Earlier draft built the feature against a fictional coredis API (no `tracking_get`/`tracking_set` methods exist; TrackingCache is client-side and configured at client construction). The real failure surface is different in shape — wrap-at-construction, not wrap-per-call — and warrants its own spec. |
| D13 | Companion Oneiric PR **lands first**, then the main Dhara PR. | The main Dhara PR's `resolve_cache_adapter` references the new fields; out-of-order landing would break the build. |
| D14 | Back-compat: **none.** No deprecated aliases. | We own all consumers. |

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
│  dhara/mcp/server_core.py (current cache_backend switch)                     │
│   ─ cache_backend="memory" ──► resolve_cache_adapter("memory")                │
│   ─ cache_backend="redis"  ──► resolve_cache_adapter("redis")                 │
│                                                                             │
│  dhara/core/connection.py:841 class Cache  ← UNTOUCHED, out of scope        │
│                                                                             │
│  dhara/mcp/adapter_lookup.py  (NEW)                                          │
│   ─ async resolve_cache_adapter(backend, settings, registry)                  │
│     reads entry["factory_path"] from the registry dict                       │
└────────────────────────┬────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Oneiric (the canonical cache adapter owner)                                  │
│                                                                             │
│  oneiric/adapters/cache/redis.py  (companion PR adds                          │
│     ttl_seconds + stampede_jitter_ms to RedisCacheSettings;                  │
│     set()/get() now consume those fields;                                   │
│     factory-string leading space stripped)                                  │
│  oneiric/adapters/cache/memory.py  (companion PR strips                      │
│     factory-string leading space)                                            │
│  oneiric/adapters/cache/multitier.py                                          │
└────────────────────────────────────────────────────────────────────────────┘
```

Three boundaries, one direction of dependency: `Mahavishnu → Dhara → Oneiric`, same direction the existing `dhara_pusher` already writes in.

______________________________________________________________________

## Companion PR to Oneiric (lands FIRST)

A single additive PR covering three small changes:

### A. Strip leading space from adapter `factory` strings (D11)

In `oneiric/adapters/cache/redis.py`, change line 94:

```python
factory="oneiric.adapters.cache.redis: RedisCacheAdapter",
```

to:

```python
factory="oneiric.adapters.cache.redis:RedisCacheAdapter",
```

In `oneiric/adapters/cache/memory.py`, change line 33:

```python
factory="oneiric.adapters.cache.memory: MemoryCacheAdapter",
```

to:

```python
factory="oneiric.adapters.cache.memory:MemoryCacheAdapter",
```

### B. Add three new `RedisCacheSettings` fields (D6)

In `oneiric/adapters/cache/redis.py`, add to `RedisCacheSettings` (after `client_cache_max_idle_seconds`):

```python
    ttl_seconds: int = Field(
        default=3600,
        ge=0,
        description="Optional TTL in seconds applied at every set() call when no "
                    "per-call ttl override is passed; 0 disables TTL.",
    )
    stampede_jitter_ms: int = Field(
        default=0,
        ge=0,
        description="Optional random sleep (ms) applied when a get() returns None, "
                    "to dampen thundering-herd on hot keys.",
    )
    enable_client_cache: bool = Field(
        default=True,
        description="Enable Redis server-assisted client-side caching via coredis "
                    "TrackingCache. Plan uses this default per D7.",
    )
```

(The `enable_client_cache` field already exists in the existing class; this PR
documents the intent explicitly and locks the default. No behavior change.)

### C. Add consumer code in `set()` and `get()` for the new TTL/jitter fields (D6)

Without these, Dhara loses the TTL/stampede-jitter behavior it had before. The
fields must be honored at call time.

In `oneiric/adapters/cache/redis.py`, modify `get` to read `stampede_jitter_ms`,
and modify `set` to read `ttl_seconds` when no per-call `ttl` is supplied:

```python
    async def get(self, key):
        # ... existing namespace + return-value handling ...
        value = await client.get(self._namespaced_key(key))
        if value is None and self._settings.stampede_jitter_ms > 0:
            await asyncio.sleep(
                random.uniform(0, self._settings.stampede_jitter_ms) / 1000.0
            )
        return value

    async def set(self, key, value, ttl=None):
        effective_ttl = ttl if ttl is not None else self._settings.ttl_seconds
        kwargs = {}
        if effective_ttl and effective_ttl > 0:
            kwargs["px"] = int(effective_ttl * 1000)
        # ... rest of existing set() body passing kwargs to client.set ...
```

Exact placement decided at implementation time against the current line numbers of `redis.py`.

### Companion tests under `oneiric/tests/unit/test_redis_cache_settings.py` (new)

- `test_default_ttl_seconds_is_3600` — round-trip default.
- `test_default_stampede_jitter_ms_is_zero`.
- `test_negative_ttl_seconds_rejected` — Pydantic ValidationError.
- `test_negative_stampede_jitter_ms_rejected`.
- `test_existing_fields_round_trip_unchanged` — sanity round-trip.
- `test_factory_string_has_no_leading_space_in_redis` — guards D11 regression.
- `test_factory_string_has_no_leading_space_in_memory` — same, memory side.

### Companion tests under `oneiric/tests/unit/test_redis_cache.py` (extend existing)

- `test_set_uses_default_ttl_seconds_when_no_kwarg_passed` — `await adapter.set("k", "v")` followed by inspecting the awaited coredis call includes `px=<ttl_seconds * 1000>`.
- `test_get_applies_stampede_jitter_on_miss` — `await adapter.get("k")` against a fake coredis client that returns `None` triggers a sleep of the documented bound.
- `test_get_skips_stampede_jitter_on_hit` — same setup but fake returns bytes; no sleep.
- `test_get_skips_stampede_jitter_when_setting_is_zero` — default config; no sleep.

______________________________________________________________________

## Main PR to Dhara

### Modified

| File | Change |
|---|---|
| `dhara/mcp/adapter_lookup.py` (NEW, ~35 lines) | `async def resolve_cache_adapter(backend: Literal["memory","redis"], settings: RedisCacheSettings | MemoryCacheSettings | None, registry: AsyncAdapterRegistry) -> Any`. Reads `entry["factory_path"]` from the registry dict (D10). Validates backend ∈ `{"memory","redis"}`. |
| `dhara/mcp/server_core.py` | **Move `self._async_adapter_registry = AsyncAdapterRegistry(async_conn)` ahead of the cache_backend block** (D6 fix). Replace `cache_backend` switch block with a call to `resolve_cache_adapter`. Drop imports from `dhara.storage.redis_cache`. Add structured log `cache-adapter-resolved` with `(backend, provider, settings_class)`. Source settings from the module-level `load_settings(...).adapters.provider_settings.get("cache.redis", {})` (D3 fix; **as shipped**: `oneiric.core.config.load_settings` is a module-level function, NOT `OneiricSettings.load_settings` — the classmethod does not exist); fall back to `RedisCacheSettings()` or `MemoryCacheSettings()` defaults. **As shipped**: when `self._async_adapter_registry` is `None`, `_wire_cache` falls back to a local `_BuiltinCacheRegistry()` so cache resolution works during construction before the async registry exists. |
| `dhara/core/config.py` | Drop the `cache_redis_url`, `cache_redis_token`, `cache_ttl`, `cache_stampede_jitter_ms`, `cache_key_prefix` fields (the last is fictitious — never existed). Keep `cache_backend: str = Field(default="memory", description="memory or redis")`. Cache settings now live in `OneiricSettings.adapters.provider_settings` (canonical Oneiric path). |
| `dhara/tests/unit/test_adapter_lookup.py` (NEW) | Tests for `resolve_cache_adapter` covering D10 (registry returns dict, `factory_path` key), backend validation, init() awaited. |
| `dhara/tests/unit/test_server_core_cache.py` (NEW) | End-to-end through `server_core.py`. Mocks the registry with a real-shaped dict; asserts `cache-adapter-resolved` log fires. |
| `dhara/tests/unit/test_server_core.py` | Switch patch target from `dhara.storage.redis_cache.RedisCacheAdapter` to `dhara.mcp.adapter_lookup.resolve_cache_adapter`. Rewrite test bodies that constructed `DharaSettings(...)` with deleted fields to construct the minimal shape the new `_wire_cache` accepts. |
| `dhara/tests/unit/test_dhara_settings.py` | Drop tests for the four real removed config fields; keep `cache_backend` default and `env_override_cache_backend` tests. |

### Deleted

| File | Reason |
|---|---|
| `dhara/storage/redis_cache.py` | Replaced by `oneiric.adapters.cache.RedisCacheAdapter`. Not in `dhara/__init__.py` public exports. |
| `dhara/tests/unit/test_redis_cache.py` | Tests the deleted class. Coverage migrates to `test_server_core_cache.py`. |

**`dhara/storage/memory.py` is NOT deleted.** It defines `AsyncMemoryStorage` (the in-memory storage backend), used by `tests/test_async_connection.py`, `tests/test_async_kv_timeseries.py`, and 6+ other tests. Separate concern; out of scope.

### Explicitly NOT touched

| File / symbol | Why |
|---|---|
| `dhara/core/connection.py:841 class Cache` | Out of scope (D8). |
| `dhara/storage/memory.py` (`AsyncMemoryStorage`) | Storage backend, not cache (corrects the earlier draft). |
| `dhara/tests/benchmarks/test_cache.py` | Regression guard for `Connection.Cache` perf. The actual file path is `dhara/benchmarks/test_cache.py`, NOT `tests/benchmarks/test_cache.py`. |
| `dhara/tests/test_connection.py` (full Connection integration suite) | Spec regression guard; `Connection.Cache` is unchanged, the suite must pass unchanged. |
| `dhara/tests/unit/test_connection_cache_injection.py`, `test_connection_abort.py` | Same. |
| `oneiric/adapters/dhara_pusher.py` | Already pushes Oneiric → Dhara; works as-is once the factory-string spaces are stripped. |
| `dhara/storage/postgres.py`, `dhara/storage/sqlite.py` | Storage adapters. |
| `scripts/audit_orphans.py` | Lives only in `/Users/les/Projects/mahavishnu/scripts/audit_orphans.py` — does NOT exist in Dhara or Oneiric. The plan must NOT require running it in those repos. |

______________________________________________________________________

## Data Flow & Lifecycle

### Startup

```
oneiric.config.load_oneiric_config(...)
    → OneiricSettings
        .adapters.provider_settings["cache.redis"] = {...}     # operator-supplied or absent
        .adapters.provider_settings["cache.memory"] = {...}
                                          │
                                          ▼
              Dhara mcp/server_core.py:__init__
                  │
                  ├─ self._async_adapter_registry = AsyncAdapterRegistry(async_conn)   # MUST be FIRST
                  │
                  ▼
                config.cache_backend == "memory" | "redis"
                                          │
                                          ▼
                dhara/mcp/adapter_lookup.py:resolve_cache_adapter(backend, settings, registry)
                                          │
                            ├── construct MemoryCacheAdapter(MemoryCacheSettings())
                            │      or
                            └── construct RedisCacheAdapter(RedisCacheSettings(**provider_settings["cache.redis"]))
                                          │
                                          ▼
                                    await adapter.init()
                                          │
                  (Redis: coredis ping; Memory: log only)
                                          │
                                          ▼
                                     self.cache
                            (structured log: cache-adapter-resolved)
```

### Steady state (per-MCP-request)

```
some MCP tool: await self.cache.get("key")
  ├─ Redis:  coredis.client.get(key)
  │           └─ TrackingCache may serve local without round-trip
  └─ Memory: async with self._lock: return self._store.get(key)
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
| Invalid `backend` (typo / unsupported) | `LifecycleError("unknown cache backend: {backend!r}; expected one of ('memory', 'redis')")` raised at the top of `resolve_cache_adapter`. | Fix `cache_backend` config value. |
| Missing URL with `cache_backend=redis` | Caught at `await adapter.init()`; bubbles as `coredis.RedisError`; server fails to start. | Set `url` (or `host`/`port`) in operator's `RedisCacheSettings` via `OneiricSettings.adapters.provider_settings["cache.redis"]`. |
| Redis unreachable | Bubbles from `await client.ping()`; server fails to start. | Verify Redis URL/auth/network. |
| `ttl_seconds: -1` or `stampede_jitter_ms: -1` | `pydantic.ValidationError` at config load; server fails to start with the existing Oneiric config loader error format. | Fix the config value. |
| `Connection.Cache` regressions | Should not occur — out of scope. | `dhara/benchmarks/test_cache.py` is the regression guard (see Integration Contract). |

______________________________________________________________________

## Test Strategy

### New tests

- **`dhara/tests/unit/test_adapter_lookup.py`** — `resolve_cache_adapter`:
  resolves `memory` and `redis`; raises `LifecycleError` on empty registry; raises `LifecycleError` on invalid backend string; the constructed instance is the right concrete class; `init()` is awaited; mock `registry.get_adapter` returns a **dict** with `factory_path` key matching real `AsyncAdapterRegistry.get_adapter_async` shape.
- **`dhara/tests/unit/test_server_core_cache.py`** — full-server-core path:
  `cache_backend=memory` wires `MemoryCacheAdapter`; `cache_backend=redis` wires `RedisCacheAdapter`; `cache-adapter-resolved` log line fires with structured fields. Real-shaped registry mock.
- **`oneiric/tests/unit/test_redis_cache_settings.py`** (new) — companion tests for the new `ttl_seconds`/`stampede_jitter_ms` fields, plus factory-string leading-space guards.
- **`oneiric/tests/unit/test_redis_cache.py`** (extend existing) — TTL default-on-read test, stampede-jitter on-miss and on-hit tests.

### Modified tests

- **`dhara/tests/unit/test_server_core.py`** — patch target switches from `dhara.storage.redis_cache.RedisCacheAdapter` to `dhara.mcp.adapter_lookup.resolve_cache_adapter`. Test bodies that constructed `DharaSettings(cache_backend="redis", cache_redis_url=..., cache_redis_token=..., cache_ttl=..., cache_stampede_jitter_ms=...)` are rewritten to construct the minimal config `_wire_cache` accepts (most likely just `cache_backend="redis"` since the URL knobs now live in `OneiricSettings.adapters.provider_settings`).
- **`dhara/tests/unit/test_dhara_settings.py`** — drop tests for removed config fields; keep the `cache_backend` default test and the env-override test.

### Deleted tests

- `dhara/tests/unit/test_redis_cache.py` (covers deleted `dhara.storage.redis_cache`).
- `dhara/tests/unit/test_memory_cache.py` if it exists (covers the non-deleted `AsyncMemoryStorage` — re-check, do NOT delete if it exists).

### Regression guards

- `dhara/benchmarks/test_cache.py` (the `Connection.Cache` benchmark) — must pass with no edits. >2× regression = rollback signal. **Actual file path is `dhara/benchmarks/test_cache.py`, not `tests/benchmarks/`.**
- `dhara/tests/test_connection.py` (the full `Connection` integration suite) — must pass unchanged.
- `dhara/tests/unit/test_connection_cache_injection.py` — must pass unchanged.
- `dhara/tests/unit/test_connection_abort.py` — must pass unchanged.

### Smoke test checklist (run before merge)

1. `dhara -s --file /tmp/smoke.dhara` with no Redis available → `cache_backend=memory` default → server starts, `/health` reports `cache=memory`, healthy. `cache-adapter-resolved` log fires.
1. With Redis available and `cache_backend=redis` → server starts, `/health` reports `cache=redis`. `cache-adapter-resolved` log fires with `settings_class="RedisCacheSettings"`.
1. Interactive `dhara -c --file /tmp/smoke.dhara` performs a get/set that touches cache; structured logs include `cache-adapter-resolved`, `adapter-init`, `adapter-cleanup-complete`.
1. `pytest dhara/tests/ -v` is green.
1. `pytest dhara/benchmarks/test_cache.py` is within 2× of the Phase-1 baseline.

### Orphan audit

`scripts/audit_orphans.py` exists only in the `mahavishnu` repo; it does not exist in Dhara or Oneiric. The plan does NOT require running it in those repos. If the operator wants the audit, run it from `/Users/les/Projects/mahavishnu` against the changed files.

______________________________________________________________________

## Integration Contract

Per CLAUDE.md "Process Discipline" — required for non-trivial features.

```
Triggered from:
  - Dhara MCP server startup (dhara/mcp/server_core.py:__init__)
  - Dhara MCP server tool invocations that read/write cache (existing paths)
  - Prerequisite oneiric fixup: Oneiric's adapter_metadata.factory strings are
    now consumed at import-time by Dhara's resolve_cache_adapter.

Returns to / updates:
  - dhara.storage.redis_cache module: DELETED
  - dhara/storage.memory module: UNTOUCHED (AsyncMemoryStorage is unrelated)
  - dhara.core.config.cache_redis_url: DELETED
  - dhara.core.config.cache_redis_token: DELETED
  - dhara.core.config.cache_ttl: DELETED
  - dhara.core.config.cache_stampede_jitter_ms: DELETED
  - dhara.core.connection.Cache (and shrink / clear / get_instance): UNTOUCHED
  - oneiric.adapters.cache.RedisCacheSettings: +2 fields (ttl_seconds, stampede_jitter_ms)
  - oneiric.adapters.cache.RedisCacheAdapter.set: now consumes ttl_seconds
  - oneiric.adapters.cache.RedisCacheAdapter.get: now consumes stampede_jitter_ms
  - oneiric.adapters.cache.{redis,memory}.AdapterMetadata.factory: leading space stripped (both)

Demonstrable by:
  - `pytest oneiric/tests/unit/test_redis_cache_settings.py oneiric/tests/unit/test_redis_cache.py -v` passes
  - `pytest dhara/tests/unit/test_adapter_lookup.py dhara/tests/unit/test_server_core_cache.py -v` passes
  - `pytest dhara/tests/unit/test_server_core.py` passes with rebased patches
  - `pytest dhara/tests/unit/test_connection_cache_injection.py dhara/tests/unit/test_connection_abort.py -v` passes
  - `pytest dhara/benchmarks/test_cache.py` within 2× of Phase-1 baseline
  - Manual smoke: redis up & down, both modes served, cache-adapter-resolved log fires
  - `python -c "from oneiric.adapters.cache import RedisCacheAdapter, MemoryCacheAdapter"` succeeds
    (regression guard for the factory-string leading-space fix; without it,
    the import falls over as `AttributeError: module 'oneiric.adapters.cache.redis'
    has no attribute ' RedisCacheAdapter'`.)

Rollback signal:
  - dhara -s fails with "cache adapter not registered" → restore oneiric +
    reinstall with [cache] extras
  - Cache reads fail with RedisError on every call → revert companion PR
    and main PR via `git revert`
  - Connection.Cache benchmark regresses by >2× → revert the dhara-side
    migration; re-enable dhara/storage/redis_cache.py from git history
  - `python -c "from oneiric.adapters.cache import RedisCacheAdapter"` raises
    AttributeError → factory-string fix is incomplete; stop and re-fix

Observability added:
  - Structured log `cache-adapter-resolved` at startup with
    (backend, provider, settings_class)
  - Inherits `adapter-init` and `adapter-cleanup-complete` from Oneiric's
    adapters (now actually wired in)
  - Dhara MCP /health endpoint reports cache health (existing path, now
    exercised against the new adapters)
```

______________________________________________________________________

## Preconditions / Start-Gate

Per decisions **D1** and **D13**:

1. `docs/2026-07-15-async-migration-cleanup.md` must be merged to `main`
   before any of our code lands. Verify via `git -C /Users/les/Projects/dhara log --oneline main | grep -i async-migration-cleanup`.
1. The companion Oneiric PR (single PR covering the factory-string-space fix,
   the three new fields, and the consumer code for TTL/jitter) must be
   merged to `main` *before* the main Dhara PR.
1. The main Dhara PR opens only after both (1) and (2) are merged, and
   merges direct to `main` per **D3** (no PR).
1. Version bump `dhara` 0.12.1 → 0.13.0 is performed manually via
   `crackerjack` after merge, per **D4**.

______________________________________________________________________

## Out of Scope

The following were considered and explicitly deferred:

- **`dhara.core.connection.Cache` consolidation.** Needs a
  `PersistentObjectCacheAdapter` in Oneiric first. Deferred to a separate
  spec.
- **A Dhara-native cache adapter** backed by Dhara's own SQLite storage (the
  diskcache-shaped slot). Deferred.
- **TrackingCache degrade-graceful behavior.** Earlier drafts proposed
  wrapping `tracking_get`/`tracking_set` per-call; this targeted a
  fictional coredis API. The real TrackingCache failure surface is at
  client-construction time (`Redis(..., cache=TrackingCache(...))`), which
  is a different feature with different semantics. A future spec can
  handle it correctly.
- **`dhara.storage.memory` / `AsyncMemoryStorage` cleanup.** Unrelated to
  cache consolidation.
- **MultiTier or L1/L2 cache composition.** `MultiTierCacheAdapter` exists;
  Dhara's `cache_backend` config stays binary (`memory`/`redis`) for now.
- **Hot reload of cache config.** Config loaded once at startup.
- **Automated publish.** Operator performs the `crackerjack` version bump
  and publish manually per project policy.

______________________________________________________________________

## Open Questions

None. All design decisions (D1–D14) are closed.

**Tracking question (soft):** is the cache settings source path
(`OneiricSettings.load_settings(...).adapters.provider_settings.get("cache.redis", {})`)
correct, or does Dhara have its own helper that wraps this load? If so,
the helper should be the canonical source — the plan should pin whichever
load Dhara already does, not invent a new one.

______________________________________________________________________

## Notes for the implementation plan

When the implementation plan is written, it should:

- Sequence: baseline → Companion Oneiric PR (lands first) → Main Dhara PR (companion already merged) → operator `crackerjack` ceremony.
- Phase 1: baseline `pytest dhara/benchmarks/test_cache.py` recorded (note: actual path `dhara/benchmarks/test_cache.py`, not `tests/benchmarks/`).
- Phase 2: Oneiric companion PR — factory-string fix + settings fields + set/get consumer code + tests in one PR.
- Phase 3: Dhara main PR — `adapter_lookup.py`, `server_core.py` rewiring **including moving `self._async_adapter_registry = AsyncAdapterRegistry(...)` ahead of the cache_backend block**, `core/config.py` cleanup, new tests, old test deletions. Re-run benchmarks; verify within 2× of baseline.
- Phase 4 (post-merge): manual `crackerjack` version bump (`dhara` 0.12.1 → 0.13.0) and publish. Operator-driven.
