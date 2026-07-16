# Dhara Cache-Adapter Oneiric Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-07-15
**Status:** draft, blocked-on-external
**Owner:** Bodai maintainers
**Scope:** Dhara-side consolidation of cache-adapter wiring. Replace `dhara.storage.redis_cache` with Oneiric's `RedisCacheAdapter` via a registry-mediated helper; add an unprefixed `dhara/mcp/adapter_lookup.py:resolve_cache_adapter`; move `_async_adapter_registry` initialization above the cache_backend block in `server_core.py`; delete deprecated config fields and the redundant `dhara/storage/redis_cache.py` module. **Does NOT touch `dhara/storage/memory.py` / `AsyncMemoryStorage`** (a generic storage backend unrelated to cache consolidation). Direct merge to `main` per Bodai pre-1.0 policy, no PR. Manual `crackerjack` version bump performed by operator after merge.
**Purpose:** Eliminate the duplicated cache-adapter code that exists to fill the slot `diskcache` was once considered for, replacing it with Oneiric's already-supported, already-ecosystem-discovered adapters.

**Spec:** `/Users/les/Projects/dhara/docs/superpowers/specs/2026-07-15-dhara-cache-adapter-oneiric-consolidation-design.md` (revised post-review; commit 3131ef3)

**Companion plan (executable now, in Oneiric):** `/Users/les/Projects/dhara/docs/superpowers/plans/2026-07-15-oneiric-cache-factory-and-settings-plan.md` (`active, implementation`)

**Architecture:** New `dhara/mcp/adapter_lookup.py:resolve_cache_adapter` reads `entry["factory_path"]` from the registry dict (real shape per `dhara/mcp/adapter_tools.py:894-924`); `server_core.py` rewired with the registry init moved ahead of the cache block; deprecated config fields deleted; `dhara/storage/redis_cache.py` removed. `Connection.Cache` is explicitly out of scope. The plan depends on the companion Oneiric PR being merged first.

**Tech Stack:** Python 3.13; pytest (asyncio_mode = auto); Pydantic v2; coredis; Oneiric's adapter framework (`oneiric.adapters.cache.*`, `oneiric.core.lifecycle.LifecycleError`, `OneiricSettings.adapters.provider_settings`); Dhara's `AsyncAdapterRegistry`.

## Global Constraints

Project-wide rules; every task inherits them.

1. **Bodai pre-1.0 merge policy** — direct merge to `main`, **no PR**. Each phase ends in a direct `git push` to `main`.
2. **Sequencing** — Phase 1 (companion verification) must pass before Phase 2 (main Dhara PR) begins. The companion plan must be merged to Oneiric's `main` first. The in-flight Dhara async-migration must be merged to Dhara's `main` first. Phase 2 references undefined `ttl_seconds` / `stampede_jitter_ms` and a moved registry-init if the companion isn't in place.
3. **Start-gate** — `docs/2026-07-15-async-migration-cleanup.md` must already have landed on Dhara's `main` before Phase 0 begins.
4. **No back-compat aliases** — `cache_redis_url`, `cache_redis_token`, `cache_ttl`, `cache_stampede_jitter_ms` are *deleted* from `dhara/core/config.py`, not deprecated. (Note: `cache_key_prefix` was never a real field; an earlier draft hallucinated it.)
5. **`dhara/storage/memory.py` is OUT OF SCOPE.** It defines `AsyncMemoryStorage` (a generic in-memory **storage** backend used by `tests/test_async_connection.py`, `tests/test_async_kv_timeseries.py`, and 6+ other tests). It is NOT a cache adapter and must not be deleted.
6. **`Connection.Cache` is OUT OF SCOPE.** `dhara/core/connection.py:841 class Cache` is a domain-specific Persistent-object LRU. Do NOT edit it. Tests `test_connection_cache_injection.py`, `test_connection_abort.py`, and the full `tests/test_connection.py` suite are regression guards — run unchanged.
7. **Manual `crackerjack` version bump** — `dhara` goes from 0.12.1 → 0.13.0 after Phase 2 merges, performed outside this plan (operator-driven per Bodai pre-1.0 manual-publish workflow).
8. **From `docs/plans/TEMPLATE.md`** — every phase deliverable carries an **Integration Contract** block.
9. **From `dhara/CLAUDE.md` + `mahavishnu/CLAUDE.md`** — `from __future__ import annotations` as first non-comment line of every source file; `X | None = None`, never bare `= None`; no `assert` in production code; `logger.exception(...)` not `logger.error(..., exc_info=True)`; typed protocols over `Any` in production signatures; per-test timeout 300s ceiling.
10. **Plan discipline** — every step shows complete code or a complete command. No "fill in details", no "TBD".
11. **No `scripts/audit_orphans.py` in Dhara or Oneiric.** That script exists only in `mahavishnu/scripts/`. Phase 2's "exit criteria" do not require it.

---

## 1. Outcome

**User-observable change:** After this plan ships, Dhara's MCP server uses Oneiric's `RedisCacheAdapter` and `MemoryCacheAdapter` exclusively; the duplicated `dhara/storage/redis_cache.py` module no longer exists; `dhara/storage/memory.py` is left untouched; operators configure cache via the canonical `OneiricSettings.adapters.provider_settings["cache.redis"]` path; the new `ttl_seconds` and `stampede_jitter_ms` knobs work end-to-end (verified by the companion plan's tests).

**Success criteria:**
- `pytest dhara/tests/` is green (with no edits to out-of-scope regression-guard tests).
- `pytest oneiric/tests/` is green (verified by Phase 1 / Task 1.0; ensure the companion plan has already executed and shipped).
- `benchmarks/test_cache.py` perf result is within 2× the Phase 0 baseline. Note: actual file path is `dhara/benchmarks/test_cache.py`, NOT `tests/benchmarks/`.
- Manual smoke (`dhara -s --file /tmp/smoke.dhara` with both `cache_backend=memory` and `cache_backend=redis`) runs cleanly, emits `cache-adapter-resolved` structured log line, and serves a `get/set` round-trip.

## 2. Goals

1. Confirm the companion Oneiric PR has landed (Phase 1 verification).
2. Main Dhara PR merged with: new `dhara/mcp/adapter_lookup.py` helper, `_async_adapter_registry` init moved ahead of the cache block in `server_core.py`, deprecated config fields deleted, `dhara/storage/redis_cache.py` removed.
3. Tests green in both repos; regression guards for `Connection.Cache` unchanged and within 2×.
4. Manual `crackerjack` version bump (`dhara` 0.12.1 → 0.13.0) performed by operator post-merge.

## 3. Non-Goals

1. **`dhara/core/connection.py:841 class Cache` consolidation.** Deferred.
2. **`dhara/storage/memory.py` deletion.** It's `AsyncMemoryStorage`, not a cache adapter. Out of scope entirely.
3. **A Dhara-native cache adapter backed by Dhara's own SQLite storage.** Deferred.
4. **TrackingCache-degrade-graceful behavior.** Earlier drafts proposed this against fictional coredis APIs. Deferred.
5. **MultiTier composition (`memory` L1 + `redis` L2).**
6. **Hot-reload of cache config.**
7. **Automated publish.** Operator performs the `crackerjack` ceremony.

## 4. Current Findings

| Finding | Evidence |
|---|---|
| `dhara.storage.redis_cache` exists as a parallel cache adapter | `/Users/les/Projects/dhara/dhara/storage/redis_cache.py` |
| `dhara.storage.memory` exists as `AsyncMemoryStorage` (NOT a cache adapter) | `/Users/les/Projects/dhara/dhara/storage/memory.py` (1-110); re-exported from `dhara/storage/__init__.py:21` |
| Oneiric's canonical cache adapters | `/Users/les/Projects/oneiric/oneiric/adapters/cache/{redis,memory,multitier}.py` |
| `AsyncAdapterRegistry.get_adapter_async` returns a `dict[str, Any] \| None` with `factory_path` key (NOT `.factory`) | `/Users/les/Projects/dhara/dhara/mcp/adapter_tools.py:894-924` |
| `OneiricMCPConfig` has no `adapters` field; correct path is `OneiricSettings.adapters.provider_settings` | `/Users/les/Projects/oneiric/oneiric/core/config.py:213-225` |
| `_async_adapter_registry` initialized at line 224, after the cache_backend block at line 199 — would pass `None` at the right point | `/Users/les/Projects/dhara/dhara/mcp/server_core.py` |
| `dhruva-compat-20260217_043710` compat layer explicitly removed `diskcache` support to dodge CVE-2025-69872; Dhara built its own to fill that gap | `/Users/les/Projects/ARCHIVED/dhruva-compat-20260217_043710/dhruva/compat/__init__.py:8` |
| `scripts/audit_orphans.py` exists only in `/Users/les/Projects/mahavishnu/scripts/` — NOT in Dhara or Oneiric | (filesystem fact) |
| Active async migration plan; verify before Phase 0 | `/Users/les/Projects/dhara/docs/2026-07-15-async-migration-cleanup.md` |
| Benchmark file path: `dhara/benchmarks/test_cache.py` (NOT `tests/benchmarks/`) | (filesystem fact) |

---

## 5. Implementation Phases

This plan has three phases: Phase 0 baseline capture, Phase 1 companion verification, Phase 2 main Dhara work.

### Phase 0: Baseline Benchmark Capture

**Goal:** Record a numeric baseline for `Connection.Cache` performance before any code lands, so Phase 2's regression guard has a comparator.
**Tasks:** Task 0.1.
**Exit criteria:** Baseline numbers saved to `benchmarks-baseline.txt` (executor-side scratch, NEVER committed).

This phase produces no functional deliverable; per `docs/plans/TEMPLATE.md`, no Integration Contract is required for measurement-only phases.

#### Task 0.1: Record `Connection.Cache` benchmark baseline

**Files:**
- Create: `/Users/les/Projects/dhara/benchmarks-baseline.txt` (executor scratch; NEVER committed)

**Interfaces:**
- Consumes: existing benchmark `dhara/benchmarks/test_cache.py` (no edits)
- Produces: baseline numbers; executor holds this file until Phase 2, Task 2.7

- [ ] **Step 1: Verify async-migration-cleanup plan has landed**

```bash
git -C /Users/les/Projects/dhara log --oneline main | grep -i 'async-migration-cleanup'
```

Expected: at least one commit hash. If empty, **stop** and surface to operator.

- [ ] **Step 2: Run the benchmark three times back-to-back**

```bash
cd /Users/les/Projects/dhara && \
  pytest benchmarks/test_cache.py -v --benchmark-columns=mean,stddev,min,max 2>&1 | tail -40
```

Note: actual path is `dhara/benchmarks/test_cache.py`, NOT `tests/benchmarks/`. Exact values depend on host; record whatever prints.

- [ ] **Step 3: Capture numbers to baseline file**

```bash
cd /Users/les/Projects/dhara && \
  pytest benchmarks/test_cache.py 2>&1 | tail -10 > benchmarks-baseline.txt
```

Expected: `benchmarks-baseline.txt` with ~10 lines of pytest summary.

- [ ] **Step 4: Confirm file recorded**

```bash
ls -la /Users/les/Projects/dhara/benchmarks-baseline.txt
wc -l /Users/les/Projects/dhara/benchmarks-baseline.txt
```

Expected: file exists; `wc -l` ≥ 5.

- [ ] **Step 5: Do NOT commit `benchmarks-baseline.txt`** — this is executor scratch.

---

### Phase 1: Confirm Companion Plan Has Shipped

The companion Oneiric plan is executable independently and can ship before the async-migration-cleanup merge. Once it has shipped AND async-migration-cleanup has shipped, this Dhara plan can begin.

**Goal:** Verify the companion Oneiric PR is on `main` of Oneiric.
**Tasks:** Task 1.0.
**Exit criteria:** Both companion commits visible in Oneiric's `main` log, AND `python -c "..."` returns `120 10`.

#### Task 1.0: Confirm companion plan shipped

- [ ] **Step 1: Confirm companion commits are on Oneiric's `main`**

```bash
git -C /Users/les/Projects/oneiric log --oneline main -10 | head -10
```

Expected: at least these four subjects appear:
- `fix(oneiric): strip leading space from AdapterMetadata.factory strings`
- `feat(oneiric): extend RedisCacheSettings with ttl_seconds and stampede_jitter_ms`
- `feat(oneiric): consume ttl_seconds and stampede_jitter_ms in set/get`
- `test(oneiric): cover new fields + factory-string + set/get consumer code`

- [ ] **Step 2: Confirm settings import works end-to-end**

```bash
cd /Users/les/Projects/oneiric && \
  python -c "from oneiric.adapters.cache import RedisCacheSettings; s = RedisCacheSettings(ttl_seconds=120, stampede_jitter_ms=10); print(s.ttl_seconds, s.stampede_jitter_ms)"
```

Expected: `120 10`. If `AttributeError` or unexpected shape, the companion plan is not yet effective.

- [ ] **Step 3: STOP. Phase 2 cannot start until steps 1 and 2 pass.**

---

### Phase 2: Main Dhara PR

**Goal:** Replace Dhara's parallel `dhara.storage.redis_cache` with Oneiric's adapters via a registry-mediated lookup; delete the now-redundant Dhara module; update tests accordingly. **`dhara/storage/memory.py` (AsyncMemoryStorage) is NOT touched.** `Connection.Cache` is explicitly left alone.
**Tasks:** Tasks 2.0–2.7.
**Exit criteria:** Direct merge to `main` on Dhara; `pytest dhara/tests/` is green; `pytest dhara/benchmarks/test_cache.py` within 2× of Phase 0 baseline; the regression-guard Connection-cache tests pass unchanged.

#### Integration Contract

- **Triggered from**: `dhara/mcp/server_core.py:MCPServerCore.__init__` reads `config.cache_backend` (string `memory` or `redis`) and calls `dhara.mcp.adapter_lookup.resolve_cache_adapter(backend, settings, registry)`. The endpoint symbol is `dhara.mcp.adapter_lookup.resolve_cache_adapter`. Note: `self._async_adapter_registry = AsyncAdapterRegistry(async_conn)` MUST be initialized BEFORE this call (current code initializes it at line ~224, after the cache block at ~199 — fix order as part of Task 2.2).
- **Returns to / updates**: `dhara/storage/redis_cache.py` (deleted), `dhara/tests/unit/test_redis_cache.py` (deleted), `dhara/core/config.py` fields `cache_redis_url`, `cache_redis_token`, `cache_ttl`, `cache_stampede_jitter_ms` (deleted). New file `dhara/mcp/adapter_lookup.py`. Two new test files `dhara/tests/unit/test_adapter_lookup.py` and `dhara/tests/unit/test_server_core_cache.py`. **NOT deleted: `dhara/storage/memory.py`.** NOT edited: `dhara/core/connection.py:841 class Cache`.
- **Demonstrable by**: `cd /Users/les/Projects/dhara && pytest tests/unit/test_adapter_lookup.py tests/unit/test_server_core_cache.py tests/unit/test_server_core.py tests/unit/test_dhara_settings.py tests/unit/test_connection_cache_injection.py tests/unit/test_connection_abort.py tests/test_connection.py -v` exits 0 with all listed tests PASSED. `pytest benchmarks/test_cache.py` is within 2× baseline.
- **Rollback signal**: `pytest dhara/tests/` shows a regression on any pre-existing test (especially `test_connection_cache_injection.py`, `test_connection_abort.py`, or the benchmark) OR `pytest benchmarks/test_cache.py` shows >2× regression OR `python -c "from dhara.mcp.adapter_lookup import resolve_cache_adapter"` raises `ImportError`. Roll back via `git -C /Users/les/Projects/dhara revert HEAD`. The deleted `redis_cache.py` exists in git history; restore via `git checkout <pre-revert-sha>^ -- dhara/storage/redis_cache.py`.
- **Observability added**: structured log key `cache-adapter-resolved` from `dhara.mcp.server_core` startup path, carrying `(backend, provider, settings_class)`. Inherits `adapter-init` and `adapter-cleanup-complete` from Oneiric's adapters.

#### Task 2.0: Failing tests for `dhara/mcp/adapter_lookup.py:resolve_cache_adapter`

**Files:**
- Create: `/Users/les/Projects/dhara/tests/unit/test_adapter_lookup.py`

**Interfaces:**
- Consumes: `dhara.mcp.adapter_lookup.resolve_cache_adapter` (will exist after Task 2.1); Dhara's `AsyncAdapterRegistry` whose `get_adapter_async(...)` returns `dict[str, Any] | None` with key `factory_path` (NOT `.factory`) per `dhara/mcp/adapter_tools.py:894-924`
- Produces: Test module fails with `ImportError` until the helper lands

- [ ] **Step 1: Write the test file (real-shape registry mock)**

```python
# /Users/les/Projects/dhara/tests/unit/test_adapter_lookup.py
"""Tests for dhara.mcp.adapter_lookup.resolve_cache_adapter.

Mocks AsyncAdapterRegistry with the real-shaped dict return contract:
`{"factory_path": "module:Class", ...}` per
dhara/mcp/adapter_tools.py:894-924.
"""
from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock

import pytest

from oneiric.adapters.cache import MemoryCacheAdapter, RedisCacheAdapter
from oneiric.core.lifecycle import LifecycleError


def _import(name: str) -> Any:
    module_name, _, attr = name.partition(":")
    return getattr(importlib.import_module(module_name), attr)


def _registry_with(payload: dict[tuple[str, str, str], str | None]) -> MagicMock:
    """Build a registry mock whose get_adapter_async returns AdapterEntry-shaped dicts."""
    reg = MagicMock()

    async def get_adapter(domain: str, key: str, provider: str) -> dict[str, Any] | None:
        factory_path = payload.get((domain, key, provider))
        if factory_path is None:
            return None
        return {"factory_path": factory_path}

    reg.get_adapter_async = get_adapter
    return reg


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolves_memory_backend() -> None:
    from dhara.mcp.adapter_lookup import resolve_cache_adapter

    reg = _registry_with(
        {("adapter", "cache", "memory"): "oneiric.adapters.cache.memory:MemoryCacheAdapter"}
    )
    adapter = await resolve_cache_adapter("memory", None, reg, _import)
    assert isinstance(adapter, MemoryCacheAdapter)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolves_redis_backend() -> None:
    from dhara.mcp.adapter_lookup import resolve_cache_adapter
    from oneiric.adapters.cache import RedisCacheSettings

    settings = RedisCacheSettings(url="redis://example:6379/0")
    reg = _registry_with(
        {("adapter", "cache", "redis"): "oneiric.adapters.cache.redis:RedisCacheAdapter"}
    )
    adapter = await resolve_cache_adapter("redis", settings, reg, _import)
    assert isinstance(adapter, RedisCacheAdapter)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unknown_backend_raises_lifecycle_error() -> None:
    from dhara.mcp.adapter_lookup import resolve_cache_adapter

    reg = _registry_with({})
    with pytest.raises(LifecycleError):
        await resolve_cache_adapter("redis", None, reg, _import)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalid_backend_string_raises_lifecycle_error() -> None:
    from dhara.mcp.adapter_lookup import resolve_cache_adapter

    reg = _registry_with({})
    with pytest.raises(LifecycleError):
        await resolve_cache_adapter("redisS", None, reg, _import)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_init_is_awaited_on_resolved_adapter() -> None:
    from dhara.mcp.adapter_lookup import resolve_cache_adapter
    from unittest.mock import AsyncMock

    init = AsyncMock()
    sentinel = MagicMock(spec=MemoryCacheAdapter)
    sentinel.init = init

    reg = MagicMock()

    async def get_adapter(domain: str, key: str, provider: str) -> dict[str, Any] | None:
        return {"factory_path": "oneiric.adapters.cache.memory:MemoryCacheAdapter"}

    reg.get_adapter_async = get_adapter

    def fake_import(name: str) -> Any:
        if name == "oneiric.adapters.cache.memory:MemoryCacheAdapter":
            return lambda settings: sentinel
        return _import(name)

    adapter = await resolve_cache_adapter("memory", None, reg, fake_import)
    init.assert_awaited_once()
    assert adapter is sentinel


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dict_factory_path_field_is_read_not_attr() -> None:
    """Guard against reverting to `getattr(entry, "factory")` — that always returns None on a dict."""
    from dhara.mcp.adapter_lookup import resolve_cache_adapter

    class WrongShape:
        factory = "oneiric.adapters.cache.memory:MemoryCacheAdapter"

    reg = MagicMock()

    async def get_adapter(domain: str, key: str, provider: str) -> Any:
        return WrongShape()

    reg.get_adapter_async = get_adapter

    with pytest.raises(LifecycleError):
        await resolve_cache_adapter("memory", None, reg, _import)
```

- [ ] **Step 2: Run and confirm meaningful failures (not import-level)**

```bash
cd /Users/les/Projects/dhara && pytest tests/unit/test_adapter_lookup.py -v
```

Expected: 4 of 6 tests FAIL with `AttributeError` or `LifecycleError`.

- [ ] **Step 3: Commit the failing tests**

```bash
cd /Users/les/Projects/dhara && \
  git add tests/unit/test_adapter_lookup.py && \
  git commit -m "test(dhara): add failing tests for cache-adapter lookup helper"
```

#### Task 2.1: Implement `dhara/mcp/adapter_lookup.py`

**Files:**
- Create: `/Users/les/Projects/dhara/dhara/mcp/adapter_lookup.py`

**Interfaces:**
- Consumes: existing Dhara `AsyncAdapterRegistry` whose `get_adapter_async(domain, key, provider)` returns a `dict | None` with key `factory_path` (verified at `dhara/mcp/adapter_tools.py:894-924`)
- Produces: `async resolve_cache_adapter(backend, settings, registry, import_fn=_default_import) -> CacheAdapter`

- [ ] **Step 1: Write the helper**

```python
# /Users/les/Projects/dhara/dhara/mcp/adapter_lookup.py
"""Registry-mediated cache-adapter lookup for the Dhara MCP server.

Asks Dhara's AsyncAdapterRegistry for the canonical Oneiric cache-adapter
class (stored as a `factory_path` string in the dict returned by
`registry.get_adapter_async(domain, key, provider)`), imports it via
the factory path, instantiates with caller-supplied settings, awaits
`init()`, and returns the live adapter. Raises `LifecycleError` for any
configuration error (unknown backend, missing factory, failed import).
"""
from __future__ import annotations

import importlib
from typing import Any, Callable, Literal, Union

from oneiric.adapters.cache import (
    MemoryCacheAdapter,
    MemoryCacheSettings,
    RedisCacheAdapter,
    RedisCacheSettings,
)
from oneiric.core.lifecycle import LifecycleError

Backend = Literal["memory", "redis"]

CacheAdapter = Union[RedisCacheAdapter, MemoryCacheAdapter]

ImportFn = Callable[[str], Any]

ALLOWED_BACKENDS: tuple[str, ...] = ("memory", "redis")


def _default_import(name: str) -> Any:
    """Import `module:Class` from `name`. Whitespace-tolerant on either side of the colon."""
    module_name, _, attr = name.partition(":")
    if not module_name or not attr:
        raise LifecycleError(f"malformed factory path: {name!r}")
    module = importlib.import_module(module_name.strip())
    return getattr(module, attr.strip())


async def resolve_cache_adapter(
    backend: Backend,
    settings: RedisCacheSettings | MemoryCacheSettings | None,
    registry: Any,
    import_fn: ImportFn = _default_import,
) -> CacheAdapter:
    if backend not in ALLOWED_BACKENDS:
        raise LifecycleError(
            f"unknown cache backend: {backend!r}; expected one of {ALLOWED_BACKENDS}"
        )
    entry = await registry.get_adapter_async("adapter", "cache", backend)
    if entry is None:
        raise LifecycleError(
            f"cache adapter not registered for backend={backend!r}"
        )
    factory_path = (
        entry["factory_path"]
        if isinstance(entry, dict)
        else getattr(entry, "factory_path", None)
    )
    if not factory_path:
        raise LifecycleError(
            f"registry entry for backend={backend!r} has no factory_path"
        )
    try:
        adapter_cls = import_fn(factory_path)
    except (ImportError, AttributeError) as exc:
        raise LifecycleError(
            f"failed to import cache adapter factory {factory_path!r}"
        ) from exc
    instance = adapter_cls(settings)
    await instance.init()
    return instance
```

- [ ] **Step 2: Run the test file and verify green**

```bash
cd /Users/les/Projects/dhara && pytest tests/unit/test_adapter_lookup.py -v
```

Expected: all 6 tests PASSED.

- [ ] **Step 3: Commit**

```bash
cd /Users/les/Projects/dhara && \
  git add dhara/mcp/adapter_lookup.py && \
  git commit -m "feat(dhara): add registry-mediated cache-adapter lookup helper

Reads entry['factory_path'] from the AsyncAdapterRegistry dict
(real shape per dhara/mcp/adapter_tools.py:894-924), imports the
adapter class via the factory path, instantiates with caller settings,
awaits init(), returns. Backend validation prevents typos."
```

#### Task 2.2: Move `_async_adapter_registry` init ahead of the cache block

**Files:**
- Modify: `/Users/les/Projects/dhara/dhara/mcp/server_core.py:__init__`

**Interfaces:**
- Consumes: existing `DharaMCPServer.__init__` flow. Currently `self._async_adapter_registry = AsyncAdapterRegistry(async_conn)` is at line ~224, but the cache_backend block is at line ~199 — so any code in the cache path sees `None`.
- Produces: registry initialization moves ahead of the cache_backend block.

- [ ] **Step 1: Locate the existing init order**

```bash
grep -n 'cache_backend\|_async_adapter_registry\|adapter_registry =' /Users/les/Projects/dhara/dhara/mcp/server_core.py | head -20
```

- [ ] **Step 2: Read the section around line 199–225**

```bash
sed -n '195,230p' /Users/les/Projects/dhara/dhara/mcp/server_core.py
```

- [ ] **Step 3: Move the `_async_adapter_registry` line above the cache_backend block**

Identify the line `self._async_adapter_registry: AsyncAdapterRegistry | None = None` (placeholder) and the later assignment `self._async_adapter_registry = AsyncAdapterRegistry(async_conn)`. Move the **assignment** to just above the existing cache_backend block.

- [ ] **Step 4: Commit**

```bash
cd /Users/les/Projects/dhara && \
  git add dhara/mcp/server_core.py && \
  git commit -m "refactor(dhara): initialize async_adapter_registry before cache_backend block"
```

#### Task 2.3: Wire `server_core.py` to call `resolve_cache_adapter` via a `_wire_cache` helper

**Files:**
- Modify: `/Users/les/Projects/dhara/dhara/mcp/server_core.py` — replace the inline cache_backend switch with a call to a new module-private `_wire_cache`

- [ ] **Step 1: Read the current cache_backend block**

```bash
sed -n '195,235p' /Users/les/Projects/dhara/dhara/mcp/server_core.py
```

- [ ] **Step 2: Add imports**

Remove (if present):

```python
from dhara.storage.redis_cache import ...
```

Add:

```python
from dhara.mcp.adapter_lookup import resolve_cache_adapter
from oneiric.adapters.cache import MemoryCacheSettings, RedisCacheSettings
```

(`OneiricSettings` may need to be imported from `oneiric.core.settings`; verify with `grep -n "class OneiricSettings" /Users/les/Projects/oneiric/oneiric/core/*.py` before using.)

- [ ] **Step 3: Add `_wire_cache` helper above `MCPServerCore` class definition**

```python
def _wire_cache(config: Any, core_self: Any) -> Any:
    """Resolve and instantiate the cache adapter via the registry helper.

    Settings come from OneiricSettings.adapters.provider_settings (the
    canonical Oneiric path) so Dhara owns no cache-specific config fields.
    """
    from oneiric.core.settings import OneiricSettings  # verify import path

    cache_backend = getattr(config, "cache_backend", "memory")
    if cache_backend == "redis":
        provider_settings = (
            OneiricSettings.load_settings(project_name="dhara")
            .adapters.provider_settings.get("cache.redis", {})
        )
        cache_settings = (
            RedisCacheSettings(**provider_settings)
            if provider_settings
            else RedisCacheSettings()
        )
    else:
        cache_settings = MemoryCacheSettings()

    adapter = __import__(
        "dhara.mcp.adapter_lookup", fromlist=["resolve_cache_adapter"]
    ).resolve_cache_adapter(
        cache_backend, cache_settings, core_self._async_adapter_registry
    )
    core_self._logger.info(
        "cache-adapter-resolved",
        backend=cache_backend,
        provider=cache_backend,
        settings_class=type(cache_settings).__name__,
    )
    return adapter
```

- [ ] **Step 4: Replace the inline cache-backend block in `__init__`**

Find the existing `if cache_backend == "redis": ... else: ...` block and replace with:

```python
            self.cache = await _wire_cache(config, self)
```

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/dhara && \
  git add dhara/mcp/server_core.py && \
  git commit -m "refactor(dhara): wire MCP-server cache through registry helper"
```

#### Task 2.4: Failing tests for the new wiring path

**Files:**
- Create: `/Users/les/Projects/dhara/tests/unit/test_server_core_cache.py`

- [ ] **Step 1: Write the test file**

```python
# /Users/les/Projects/dhara/tests/unit/test_server_core_cache.py
"""End-to-end tests for cache-adapter wiring through dhara.mcp.server_core."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from oneiric.adapters.cache import (
    MemoryCacheAdapter,
    MemoryCacheSettings,
    RedisCacheAdapter,
)


def _make_config(cache_backend: str = "memory") -> Any:
    cfg = MagicMock()
    cfg.cache_backend = cache_backend
    return cfg


def _make_core() -> Any:
    core = MagicMock()
    core._async_adapter_registry = MagicMock()
    core._logger = MagicMock()
    return core


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_backend_wires_memory_cache_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    from dhara.mcp import server_core

    captured: dict[str, Any] = {}

    async def fake_resolve(backend: str, settings: Any, registry: Any) -> Any:
        captured["backend"] = backend
        captured["settings"] = settings
        sentinel = MagicMock(spec=MemoryCacheAdapter)
        return sentinel

    monkeypatch.setattr(server_core, "resolve_cache_adapter", fake_resolve, raising=False)
    cfg = _make_config("memory")
    core = _make_core()
    result = await server_core._wire_cache(cfg, core)
    assert captured["backend"] == "memory"
    assert isinstance(captured["settings"], MemoryCacheSettings)
    assert isinstance(result, MemoryCacheAdapter)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_redis_backend_wires_redis_cache_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    from dhara.mcp import server_core

    sentinel = MagicMock(spec=RedisCacheAdapter)

    async def fake_resolve(backend: str, settings: Any, registry: Any) -> Any:
        return sentinel

    monkeypatch.setattr(server_core, "resolve_cache_adapter", fake_resolve, raising=False)
    cfg = _make_config("redis")
    core = _make_core()
    result = await server_core._wire_cache(cfg, core)
    assert isinstance(result, RedisCacheAdapter)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cache_adapter_resolved_log_fires_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    from dhara.mcp import server_core

    async def fake_resolve(backend: str, settings: Any, registry: Any) -> Any:
        return MagicMock(spec=MemoryCacheAdapter)

    monkeypatch.setattr(server_core, "resolve_cache_adapter", fake_resolve, raising=False)
    cfg = _make_config("memory")
    core = _make_core()
    await server_core._wire_cache(cfg, core)
    core._logger.info.assert_any_call(
        "cache-adapter-resolved",
        backend="memory",
        provider="memory",
        settings_class="MemoryCacheSettings",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_backend_does_not_resolve_redis_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    from dhara.mcp import server_core

    awaited_with: list[str] = []

    async def fake_resolve(backend: str, settings: Any, registry: Any) -> Any:
        awaited_with.append(backend)
        return MagicMock(spec=MemoryCacheAdapter)

    monkeypatch.setattr(server_core, "resolve_cache_adapter", fake_resolve, raising=False)
    cfg = _make_config("memory")
    core = _make_core()
    await server_core._wire_cache(cfg, core)
    assert awaited_with == ["memory"]
```

- [ ] **Step 2: Confirm tests pass**

```bash
cd /Users/les/Projects/dhara && pytest tests/unit/test_server_core_cache.py -v
```

Expected: all 4 tests PASSED.

- [ ] **Step 3: Commit**

```bash
cd /Users/les/Projects/dhara && \
  git add tests/unit/test_server_core_cache.py && \
  git commit -m "test(dhara): cover _wire_cache wiring through server_core"
```

#### Task 2.5: Drop deprecated Dhara config fields

**Files:**
- Modify: `/Users/les/Projects/dhara/dhara/core/config.py`
- Modify: `/Users/les/Projects/dhara/tests/unit/test_dhara_settings.py`

- [ ] **Step 1: Read the current config section**

```bash
sed -n '125,150p' /Users/les/Projects/dhara/dhara/core/config.py
```

- [ ] **Step 2: Delete the four real fields**

Delete lines defining `cache_redis_url`, `cache_redis_token`, `cache_ttl`, `cache_stampede_jitter_ms`. Keep `cache_backend: str = Field(default="memory", description="memory or redis")`.

- [ ] **Step 3: Locate tests in `test_dhara_settings.py` that reference the deleted fields**

```bash
grep -nE 'cache_redis_url|cache_redis_token|cache_ttl|cache_stampede_jitter_ms|cache_key_prefix' \
  /Users/les/Projects/dhara/tests/unit/test_dhara_settings.py
```

- [ ] **Step 4: Delete every line with those substrings**

Open the file and delete each test function or helper line that references those fields. Keep `test_cache_backend_defaults_to_memory` and `test_env_overrides_cache_backend`.

- [ ] **Step 5: Run the settings test module**

```bash
cd /Users/les/Projects/dhara && pytest tests/unit/test_dhara_settings.py -v
```

Expected: surviving tests PASSED.

- [ ] **Step 6: Commit**

```bash
cd /Users/les/Projects/dhara && \
  git add dhara/core/config.py tests/unit/test_dhara_settings.py && \
  git commit -m "refactor(dhara): drop deleted cache config fields, source from OneiricSettings"
```

#### Task 2.6: Rebase `tests/unit/test_server_core.py` patch targets

**Files:**
- Modify: `/Users/les/Projects/dhara/tests/unit/test_server_core.py`

- [ ] **Step 1: Locate patches and field references**

```bash
grep -n 'patch\|dhara.storage.redis_cache\|cache_redis_url\|cache_redis_token\|cache_ttl\|cache_stampede_jitter_ms' \
  /Users/les/Projects/dhara/tests/unit/test_server_core.py
```

- [ ] **Step 2: Rewrite `DharaSettings(...)` constructor calls**

Replace constructions like:
```python
DharaSettings(cache_backend="redis", cache_redis_url=..., cache_redis_token=..., cache_ttl=..., cache_stampede_jitter_ms=...)
```
with:
```python
DharaSettings(cache_backend="redis")
```

- [ ] **Step 3: Rewrite patch targets**

Replace `@patch("dhara.storage.redis_cache.RedisCacheAdapter")` (and similar) with `@patch("dhara.mcp.adapter_lookup.resolve_cache_adapter")`. Adjust assertions: `mock_resolve.assert_awaited_once_with(backend="redis", settings=..., registry=...)`.

- [ ] **Step 4: For `test_memory_cache_backend_no_redis`, preserve the negative assertion**

```python
mock_resolve.assert_not_awaited()  # or "called only with backend='memory'"
```

- [ ] **Step 5: Run the test module**

```bash
cd /Users/les/Projects/dhara && pytest tests/unit/test_server_core.py -v
```

Expected: every test in the file PASSES.

- [ ] **Step 6: Commit**

```bash
cd /Users/les/Projects/dhara && \
  git add tests/unit/test_server_core.py && \
  git commit -m "test(dhara): repoint server_core patches from local adapter to registry helper"
```

#### Task 2.7: Delete the duplicated Dhara module + verify

**Files:**
- Delete: `/Users/les/Projects/dhara/dhara/storage/redis_cache.py`
- Delete: `/Users/les/Projects/dhara/tests/unit/test_redis_cache.py`

- [ ] **Step 1: Delete the production module**

```bash
cd /Users/les/Projects/dhara && git rm dhara/storage/redis_cache.py
```

- [ ] **Step 2: Delete the test module**

```bash
cd /Users/les/Projects/dhara && git rm tests/unit/test_redis_cache.py
```

- [ ] **Step 3: Verify no remaining references to `dhara.storage.redis_cache`**

```bash
cd /Users/les/Projects/dhara && \
  grep -rn 'dhara.storage.redis_cache' dhara/ tests/ \
  || echo "no remaining references"
```

Expected: `no remaining references`.

- [ ] **Step 4: Verify `dhara/storage/memory.py` is NOT touched**

```bash
cd /Users/les/Projects/dhara && \
  grep -rn 'dhara.storage.memory' dhara/storage/memory.py dhara/storage/__init__.py | head
```

Expected: at least one match. If zero, investigate.

- [ ] **Step 5: Run the full Dhara test suite**

```bash
cd /Users/les/Projects/dhara && pytest tests/ -q
```

Expected: all green.

- [ ] **Step 6: Run the regression-guard `Connection.Cache` tests**

```bash
cd /Users/les/Projects/dhara && \
  pytest tests/unit/test_connection_cache_injection.py tests/unit/test_connection_abort.py tests/test_connection.py -v
```

Expected: green.

- [ ] **Step 7: Run the benchmark and compare against Phase 0 baseline**

```bash
cd /Users/les/Projects/dhara && \
  pytest benchmarks/test_cache.py 2>&1 | tail -10
```

Expected: numbers within 2× of `benchmarks-baseline.txt` from Phase 0.

- [ ] **Step 8: Commit the deletions**

```bash
cd /Users/les/Projects/dhara && \
  git commit -m "refactor(dhara): delete dhara.storage.redis_cache (now unused)

The companion Oneiric PR is merged. Dhara's MCP server now resolves
cache adapters through dhara.mcp.adapter_lookup, so the local parallel
implementation in dhara/storage/redis_cache.py is unused.

dhara/storage/memory.py (AsyncMemoryStorage) is intentionally
untouched. Connection.Cache (dhara/core/connection.py:841) is also
intentionally untouched per spec D8."
```

- [ ] **Step 9: Direct-merge to `main` (no PR)**

```bash
cd /Users/les/Projects/dhara && git push origin main
```

Expected: push succeeds.

---

## 6. Required Code Changes

### Oneiric (handled by the companion plan)

This plan does NOT modify Oneiric. See `/Users/les/Projects/dhara/docs/superpowers/plans/2026-07-15-oneiric-cache-factory-and-settings-plan.md`.

### Dhara (Phase 2)

- **Create** `dhara/mcp/adapter_lookup.py` (Task 2.1)
- **Create** `dhara/tests/unit/test_adapter_lookup.py` (Task 2.0)
- **Create** `dhara/tests/unit/test_server_core_cache.py` (Task 2.4)
- **Modify** `dhara/mcp/server_core.py`:
  - Add imports (Task 2.3)
  - Move `self._async_adapter_registry = AsyncAdapterRegistry(...)` above the cache_backend block (Task 2.2)
  - Drop `from dhara.storage.redis_cache import ...` (Task 2.3)
  - Add `_wire_cache(config, core_self)` helper (Task 2.3)
  - Replace the inline cache_backend switch with `await _wire_cache(config, self)` (Task 2.3)
- **Modify** `dhara/core/config.py`: drop `cache_redis_url`, `cache_redis_token`, `cache_ttl`, `cache_stampede_jitter_ms` (Task 2.5)
- **Modify** `dhara/tests/unit/test_dhara_settings.py`: drop tests for removed fields (Task 2.5)
- **Modify** `dhara/tests/unit/test_server_core.py`: repoint patches (Task 2.6)
- **Delete** `dhara/storage/redis_cache.py` (Task 2.7)
- **Delete** `dhara/tests/unit/test_redis_cache.py` (Task 2.7)

### Files explicitly NOT touched

- `dhara/core/connection.py:841 class Cache` — out of scope
- `dhara/storage/memory.py` (`AsyncMemoryStorage`) — storage, not cache
- `dhara/tests/test_connection.py`, `dhara/tests/unit/test_connection_cache_injection.py`, `dhara/tests/unit/test_connection_abort.py` — regression guards
- `dhara/benchmarks/test_cache.py` — regression guard; run as-is
- `dhara/storage/postgres.py`, `dhara/storage/sqlite.py` — storage adapters
- `scripts/audit_orphans.py` (anywhere in Dhara) — does not exist

---

## 7. Validation Matrix

| Command | Expected outcome | Evidence |
|---|---|---|
| `git -C /Users/les/Projects/oneiric log --oneline main \| grep -E '(fix|feat|test)\(oneiric\)'` | Four companion commits visible | `main` head |
| `python -c "from oneiric.adapters.cache import RedisCacheSettings; s = RedisCacheSettings(ttl_seconds=120, stampede_jitter_ms=10); print(s.ttl_seconds, s.stampede_jitter_ms)"` | `120 10` | Shell stdout |
| `git -C /Users/les/Projects/dhara log --oneline main \| grep -i async-migration-cleanup` | At least one commit | `main` head |
| `cd /Users/les/Projects/dhara && pytest tests/unit/test_adapter_lookup.py tests/unit/test_server_core_cache.py tests/unit/test_server_core.py tests/unit/test_dhara_settings.py tests/unit/test_connection_cache_injection.py tests/unit/test_connection_abort.py tests/test_connection.py -v` | All green | Test output |
| `cd /Users/les/Projects/dhara && pytest benchmarks/test_cache.py 2>&1 \| tail -10` | Within 2× of baseline | Bench output |
| `grep -rn 'dhara.storage.redis_cache' dhara/ tests/` | No matches | Grep output |
| Manual smoke: `dhara -s --file /tmp/smoke.dhara` | Server starts; `cache-adapter-resolved` log fires | Dhara log |
| `python -c "from dhara.mcp.adapter_lookup import resolve_cache_adapter"` | No `ImportError` | Shell stdout |

---

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Phase 0 async-migration cleanup has not landed | Medium | Run Task 0.1 Step 1 first; if it fails, surface and stop. |
| Phase 1 companion plan has not shipped | Medium | Run Task 1.0; surface and stop. |
| `_async_adapter_registry` placement fix breaks some other init order | Low | Pure code-motion; no logic changes. |
| `benchmarks/test_cache.py` regresses >2× | Low | `Connection.Cache` untouched; rollback signal applies if regression appears. |
| `OneiricSettings` import path or class name differs | Medium-High | Task 2.3 Step 4 grep + executor verification. |

---

## 9. Decision Rule

This plan is **"done enough"** when Phase 2 main Dhara PR has merged to `main`, `pytest dhara/tests/` is green, `benchmarks/test_cache.py` is within 2× of the Phase 0 baseline, and the regression-guard `Connection.Cache` tests pass.

**Cut order** (when scope pressure forces a cut):
1. Phase 2 Task 2.4 server-core wiring test — non-critical if manual smoke covers it.
2. Phase 2 Task 2.0 adapter_lookup helper tests — non-critical if manual smoke covers it.
3. **Phase 2 Tasks 2.5–2.7** (config cleanup, deletion, full-suite validation) — **never cut**.

---

## References

- Spec (revised): `/Users/les/Projects/dhara/docs/superpowers/specs/2026-07-15-dhara-cache-adapter-oneiric-consolidation-design.md` (commit 3131ef3)
- Companion Oneiric-side plan: `/Users/les/Projects/dhara/docs/superpowers/plans/2026-07-15-oneiric-cache-factory-and-settings-plan.md`
- Plan template: `/Users/les/Projects/mahavishnu/docs/plans/TEMPLATE.md`
- Plan siblings: `/Users/les/Projects/dhara/docs/superpowers/plans/{2026-05-31-btree-redesign-plan.md,2026-05-31-dhara-async-first-plan.md}`
- Active in-flight plan that must land first: `/Users/les/Projects/dhara/docs/2026-07-15-async-migration-cleanup.md`
- Policy root: `/Users/les/Projects/mahavishnu/.claude/decisions/wire-up-contract.md`
