# Dhara Cache-Adapter Oneiric Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-07-15
**Status:** draft, planning
**Owner:** Bodai maintainers (Dhruva + Akosha interfaces)
**Scope:** Remove Dhara's parallel cache-adapter implementations (`dhara.storage.redis_cache`, `dhara.storage.memory`); adopt Oneiric's canonical cache adapters in their place. Lands as two direct-to-`main` merges (companion Oneiric first, then Dhara). Manual `crackerjack` version bump after.
**Purpose:** Eliminate duplicated cache-adapter code that existed to fill the slot `diskcache` was once considered for, replacing it with Oneiric's already-supported, already-ecosystem-discovered adapters.

**Spec:** `/Users/les/Projects/dhara/docs/superpowers/specs/2026-07-15-dhara-cache-adapter-oneiric-consolidation-design.md`

**Architecture:** Two-PR cross-repo change. Companion PR adds three fields to `oneiric.adapters.cache.RedisCacheSettings` (`ttl_seconds`, `stampede_jitter_ms`, `fail_fast_on_tracking_unavailable`) and wraps `TrackingCache` calls with degrade-graceful behavior in `RedisCacheAdapter`. Main PR replaces Dhara's MCP-server `cache_backend` switch with a registry-mediated lookup through a new `dhara/mcp/adapter_lookup.py:resolve_cache_adapter` helper, and deletes the now-redundant `dhara/storage/{redis_cache,memory}.py` modules. `Connection.Cache` is explicitly out of scope.

**Tech Stack:** Python 3.13; pytest (asyncio_mode = auto); Pydantic v2; coredis; Oneiric's adapter framework (`oneiric.adapters.cache.*`, `oneiric.core.resolution.Resolver`, `oneiric.core.lifecycle.LifecycleError`); Dhara's `AsyncAdapterRegistry`.

## Global Constraints

The following are project-wide rules for this plan; every task inherits them.

1. **Bodai pre-1.0 merge policy** — direct merge to `main`, **no PR**. Each phase ends in a direct `git push` to `main`. (Source: `docs/superpowers/specs/2026-07-15-...spec.md`, decision D3.)
2. **Sequencing** — Phase 2 (companion Oneiric PR) must complete before Phase 3 (main Dhara PR) begins; otherwise Phase 3 references undefined `ttl_seconds` / `fail_fast_on_tracking_unavailable` and breaks the build. (Source: spec D12.)
3. **Start-gate** — `docs/2026-07-15-async-migration-cleanup.md` must have already landed on `main` before any code in this plan is pushed. Verify with `git -C /Users/les/Projects/dhara log --oneline main | grep -i async-migration`. (Source: spec D1.)
4. **No back-compat aliases** — `cache_redis_url`, `cache_redis_token`, `cache_ttl`, `cache_stampede_jitter_ms`, `cache_key_prefix` are *deleted* from `dhara/core/config.py`, not deprecated. (Source: spec D11.)
5. **`Connection.Cache` is out of scope** — `dhara/core/connection.py:841 class Cache` is **not** edited. Tests `test_connection_cache_injection.py` and `test_connection_abort.py` and benchmark `tests/benchmarks/test_cache.py` are *regression guards*, not rewrite targets. (Source: spec D8.)
6. **Manual `crackerjack` version bump** — `dhara` goes from 0.12.1 → 0.13.0 after Phase 3 merges, performed outside this plan (operator uses `crackerjack` directly per the project's manual-publish workflow). Phase 4 is a checklist for that ceremony.
7. **From `docs/plans/TEMPLATE.md`** — every phase deliverable carries an **Integration Contract** block (`Triggered from`, `Returns to / updates`, `Demonstrable by`, `Rollback signal`, `Observability added`). Carry these verbatim.
8. **From Mahavishnu's Crackerjack-Compliant Code section** — `from __future__ import annotations` as first non-comment line; `X | None = None` (never bare `= None`); no `assert` in production code; `logger.exception(...)` not `logger.error(..., exc_info=True)`; typed protocol over `Any`; per-test timeout 300s ceiling; per-test markers are project-defined (`unit`, `integration`, `crackerjack`, etc., not invented).
9. **Plan discipline** — every step shows complete code or a complete command. No "fill in details", no "similar to Task N", no "TBD". A reviewer reading task N in isolation must be able to execute it.

---

## 1. Outcome

**User-observable change:** After this plan ships, Dhara's MCP server uses Oneiric's `RedisCacheAdapter` and `MemoryCacheAdapter` exclusively; the duplicated `dhara/storage/{redis_cache,memory}.py` modules no longer exist. Operators configure cache via the canonical `OneiricMCPConfig.adapters.cache.{memory,redis}.settings` path used by every other Bodai component, including the new `ttl_seconds`, `stampede_jitter_ms`, and `fail_fast_on_tracking_unavailable` knobs. TrackingCache on the Redis path degrades gracefully (warn-and-disable) on Redis 5 / restricted providers instead of failing the server.

**Success criteria:**
- `pytest dhara/tests/` is green.
- `pytest oneiric/tests/` is green.
- `python scripts/audit_orphans.py` (in both repos) reports zero recently-added orphan symbols.
- `pytest dhara/tests/benchmarks/test_cache.py` perf result is within 2× the Phase 1 baseline (catches any unintentional `Connection.Cache` regression via adjacent-code changes).
- Manual smoke (`dhara -s --file /tmp/smoke.dhara` with both `cache_backend=memory` and `cache_backend=redis`) runs cleanly, emits `cache-adapter-resolved` structured log line, and serves a `get/set` round-trip.

## 2. Goals

1. Companion Oneiric PR landed with three new `RedisCacheSettings` fields and TrackingCache degrade-graceful behavior.
2. Main Dhara PR landed with the new `dhara/mcp/adapter_lookup.py` helper, `server_core.py` rewired through it, deprecated config fields deleted, and the duplicated storage modules removed.
3. Tests green in both repos; regression guards for `Connection.Cache` unchanged and within 2×.
4. Manual `crackerjack` version bump (`dhara` 0.12.1 → 0.13.0) performed by operator post-merge (tracked in Phase 4 checklist).

## 3. Non-Goals

1. **`dhara/core/connection.py:841 class Cache` consolidation.** Deferred to a separate spec. (Spec D8.)
2. **A Dhara-native cache adapter** that uses Dhara's own SQLite storage as the cache backend. Deferred to a separate spec. The original "diskcache slot" motivation in the spec's Context section was addressed by *removing* duplication, not by inventing new cache flavors.
3. **MultiTier cache composition (`memory` L1 + `redis` L2) in Dhara's MCP server.** Operators can register a higher-priority custom adapter if they want composition; Dhara's `cache_backend` config stays binary (`memory`/`redis`).
4. **Hot-reload of cache config.** Config is loaded once at startup. Live adapter swap is its own feature.
5. **Automated publish.** Operator performs the `crackerjack` version bump and publish manually per project policy.

## 4. Current Findings

Sources cited in the spec; reproduced here for plan-executor reference.

| Finding | Evidence |
|---|---|
| `dhara.storage.redis_cache` and `dhara.storage.memory` exist as parallel implementations. | `/Users/les/Projects/dhara/dhara/storage/redis_cache.py`, `/Users/les/Projects/dhara/dhara/storage/memory.py`. |
| Oneiric already provides the canonical versions. | `/Users/les/Projects/oneiric/oneiric/adapters/cache/{redis,memory,multitier}.py`. |
| Removed modules are not in `dhara/__init__.py` public exports, so deleting is a non-breaking-API change. | `/Users/les/Projects/dhara/dhara/__init__.py` exports `Storage` family but not `RedisCacheAdapter` or the symbol from `dhara.storage.memory`. |
| Dhara's MCP server already has a registry-aware `registry.get_adapter("adapter", "cache", "redis")` test path, so registry-mediated lookup is idiomatic. | `/Users/les/Projects/dhara/tests/test_mcp_adapter_tools.py:317`. |
| Oneiric's push-to-Dhara flow and Mahavishnu's pull-from-Dhara discovery pattern (with `enable_dhara_registry`) are mature and tested. | `/Users/les/Projects/oneiric/oneiric/adapters/dhara_pusher.py`; `/Users/les/Projects/mahavishnu/tests/unit/test_adapter_discovery.py` (`enable_dhara_registry`, `allowlist_patterns`). |
| `dhruva-compat-20260217_043710`'s compat layer explicitly removed `diskcache` support to dodge the pickle-RCE CVE, and Dhara built its own to fill that gap without bringing diskcache in. | `/Users/les/Projects/ARCHIVED/dhruva-compat-20260217_043710/dhruva/compat/__init__.py:8`. |
| `Connection.Cache` (out of scope) is a domain-specific Persistent-object LRU — read after the brainstorming session revealed the surface mismatch. | `/Users/les/Projects/dhara/dhara/core/connection.py:841-955`. |
| Active async migration in flight on the same file our main PR will edit. | `/Users/les/Projects/dhara/docs/2026-07-15-async-migration-cleanup.md`; verify it's landed before Phase 3. |

---

## 5. Implementation Phases

### Phase 1: Baseline Benchmark Capture

**Goal:** Record a numeric baseline for `Connection.Cache` performance before any code lands, so Phase 3 has a regression guard.
**Tasks:** Task 1.1.
**Exit criteria:** Baseline numbers saved to `benchmarks-baseline.txt` in this plan's working directory.

This phase produces no functional deliverable — it captures a measurement for later comparison. Per `docs/plans/TEMPLATE.md`, no Integration Contract is required for measurement-only phases; rationale noted here for explicitness.

#### Task 1.1: Record `Connection.Cache` benchmark baseline

**Files:**
- Create: `/Users/les/Projects/dhara/benchmarks-baseline.txt` (one-line commit; outside git by convention but kept alongside plan)

**Interfaces:**
- Consumes: existing benchmark `dhara/tests/benchmarks/test_cache.py` (no edits)
- Produces: baseline numbers in a text file the executor holds onto until Phase 3, Task 3.8

- [ ] **Step 1: Verify async-cleanup plan has landed**
```bash
git -C /Users/les/Projects/dhara log --oneline main | grep -i 'async-migration-cleanup'
```
Expected: at least one commit hash output. If empty, **stop** and surface to operator; sequencing is broken.

- [ ] **Step 2: Run the benchmark three times back-to-back**

```bash
cd /Users/les/Projects/dhara && \
  pytest tests/benchmarks/test_cache.py -v --benchmark-columns=mean,stddev,min,max 2>&1 | tail -40
```

Expected (approximate, run is best effort):
```
test_cache_hit_performance  ... mean=~X µs
test_cache_shrink_small     ... mean=~Y µs
test_cache_shrink_large     ... mean=~Z µs
```
Exact values depend on host; record whatever prints.

- [ ] **Step 3: Capture numbers**

```bash
cd /Users/les/Projects/dhara && \
  pytest tests/benchmarks/test_cache.py 2>&1 | tail -10 > benchmarks-baseline.txt
```

Expected: a `benchmarks-baseline.txt` file with ~10 lines of pytest summary output.

- [ ] **Step 4: Confirm file recorded**

```bash
ls -la /Users/les/Projects/dhara/benchmarks-baseline.txt
wc -l /Users/les/Projects/dhara/benchmarks-baseline.txt
```

Expected: file exists; `wc -l` ≥ 5.

- [ ] **Step 5: Do NOT commit `benchmarks-baseline.txt`**

This file is executor-side scratch. It is *not* tracked; the Phase 3 regression check compares against it but never reads it from git.

---

### Phase 2: Companion Oneiric PR (lands first)

**Goal:** Add three settings fields to `oneiric.adapters.cache.RedisCacheSettings`, wrap `TrackingCache` calls with degrade-graceful behavior in `RedisCacheAdapter`, with companion unit tests.
**Tasks:** Tasks 2.1–2.5.
**Exit criteria:** Companion PR (single commit) merged to `main` on `/Users/les/Projects/oneiric`; `pytest oneiric/tests/` is green; the new fields are importable and Pydantic-rejected at the documented boundaries; TrackingCache-unsupported path emits a structured warning and continues serving.

#### Integration Contract

- **Triggered from**: Companion PR merges to `main` on `oneiric`. Triggered-by-content: any external consumer (Dhara Phase 3) imports `from oneiric.adapters.cache import RedisCacheSettings` and reads/constructs `ttl_seconds`, `stampede_jitter_ms`, or `fail_fast_on_tracking_unavailable`. Triggered-by-behavior: operator runs `from oneiric.adapters.cache import RedisCacheAdapter; a = RedisCacheAdapter(); await a.get("k")` against a Redis 5 / restricted provider that rejects `CLIENT TRACKING`.
- **Returns to / updates**: `oneiric/adapters/cache/redis.py:RedisCacheSettings` (additive: 3 fields). `oneiric/adapters/cache/redis.py:RedisCacheAdapter.get/set`-family code paths (degrade-graceful branch when TrackingCache is unsupported). Two new files under `oneiric/tests/unit/` covering the additions.
- **Demonstrable by**: `cd /Users/les/Projects/oneiric && pytest tests/unit/test_redis_cache_settings.py tests/unit/test_redis_cache_degrade.py -v` exits 0 with all listed tests PASSED.
- **Rollback signal**: `pytest oneiric/tests/` shows a regression on any pre-existing test, OR `python -c "from oneiric.adapters.cache import RedisCacheSettings; RedisCacheSettings()"` raises `pydantic.ValidationError`. Roll back via `git -C /Users/les/Projects/oneiric revert <commit>`.
- **Observability added**: structured log key `tracking-cache-unsupported` from `get_logger("adapter.cache.redis")` carrying `(backend="cache", provider="redis", error=<message>)` — emitted at most once per adapter lifetime. Existing `adapter-init` and `adapter-cleanup-complete` events continue; no schema changes to those.

#### Task 2.1: Failing tests for the new `RedisCacheSettings` fields

**Files:**
- Create: `/Users/les/Projects/oneiric/tests/unit/test_redis_cache_settings.py`

**Interfaces:**
- Consumes: `from oneiric.adapters.cache.redis import RedisCacheSettings`
- Produces: Test signatures importing the model; tests fail with `ImportError` or `AttributeError` before Task 2.2 lands

- [ ] **Step 1: Write the test file**

```python
# /Users/les/Projects/oneiric/tests/unit/test_redis_cache_settings.py
"""Unit tests for RedisCacheSettings additions."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from oneiric.adapters.cache.redis import RedisCacheSettings


def test_default_ttl_seconds_is_3600() -> None:
    s = RedisCacheSettings()
    assert s.ttl_seconds == 3600


def test_default_stampede_jitter_ms_is_zero() -> None:
    s = RedisCacheSettings()
    assert s.stampede_jitter_ms == 0


def test_default_fail_fast_on_tracking_unavailable_is_false() -> None:
    s = RedisCacheSettings()
    assert s.fail_fast_on_tracking_unavailable is False


def test_negative_ttl_seconds_rejected() -> None:
    with pytest.raises(ValidationError):
        RedisCacheSettings(ttl_seconds=-1)


def test_negative_stampede_jitter_ms_rejected() -> None:
    with pytest.raises(ValidationError):
        RedisCacheSettings(stampede_jitter_ms=-1)


def test_existing_fields_round_trip_unchanged() -> None:
    """Existing fields must keep their documented behavior."""
    s = RedisCacheSettings(
        url="redis://example:6379/0",
        host="example",
        port=6380,
        db=2,
        username="alice",
        password="secret",
        ssl=True,
        socket_timeout=1.5,
        client_name="client-x",
        healthcheck_timeout=0.5,
        decode_responses=False,
        key_prefix="pfx:",
        enable_client_cache=False,
        client_cache_max_keys=128,
        client_cache_max_size_bytes=2048,
        client_cache_max_idle_seconds=60,
        ttl_seconds=120,
        stampede_jitter_ms=10,
        fail_fast_on_tracking_unavailable=True,
    )
    assert s.host == "example"
    assert s.port == 6380
    assert s.password == "secret"
    assert s.enable_client_cache is False
    assert s.ttl_seconds == 120
    assert s.stampede_jitter_ms == 10
    assert s.fail_fast_on_tracking_unavailable is True
```

- [ ] **Step 2: Run the test file and confirm failures are import-level**

```bash
cd /Users/les/Projects/oneiric && pytest tests/unit/test_redis_cache_settings.py -v
```

Expected: error matching `AttributeError: type object 'RedisCacheSettings' has no attribute 'ttl_seconds'` (or `ValidationError` on the negative cases, depending on Pydantic path).

- [ ] **Step 3: Commit the failing tests**

```bash
cd /Users/les/Projects/oneiric && \
  git add tests/unit/test_redis_cache_settings.py && \
  git commit -m "test(oneiric): add failing tests for new RedisCacheSettings fields"
```

#### Task 2.2: Add new fields to `RedisCacheSettings`

**Files:**
- Modify: `/Users/les/Projects/oneiric/oneiric/adapters/cache/redis.py:33 class RedisCacheSettings`

**Interfaces:**
- Consumes: existing `RedisCacheSettings` definition (lines 33-90)
- Produces: `RedisCacheSettings.ttl_seconds: int`, `RedisCacheSettings.stampede_jitter_ms: int`, `RedisCacheSettings.fail_fast_on_tracking_unavailable: bool`

- [ ] **Step 1: Read the existing settings class to confirm shape**

```bash
sed -n '33,90p' /Users/les/Projects/oneiric/oneiric/adapters/cache/redis.py
```

- [ ] **Step 2: Add the three fields after the last `client_cache_max_idle_seconds` field**

In `/Users/les/Projects/oneiric/oneiric/adapters/cache/redis.py`, immediately after the line that defines `client_cache_max_idle_seconds`, insert:

```python
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

- [ ] **Step 3: Run the new test file and confirm green**

```bash
cd /Users/les/Projects/oneiric && pytest tests/unit/test_redis_cache_settings.py -v
```

Expected: all 6 tests PASSED.

- [ ] **Step 4: Run the wider cache test suite to confirm no regression**

```bash
cd /Users/les/Projects/oneiric && pytest tests/unit/ -k cache -v
```

Expected: existing cache tests PASSED; new tests PASSED.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/oneiric && \
  git add oneiric/adapters/cache/redis.py && \
  git commit -m "feat(oneiric): extend RedisCacheSettings with TTL, jitter, fail-fast knobs"
```

#### Task 2.3: Failing tests for TrackingCache degrade-graceful behavior

**Files:**
- Create: `/Users/les/Projects/oneiric/tests/unit/test_redis_cache_degrade.py`

**Interfaces:**
- Consumes: `from oneiric.adapters.cache.redis import RedisCacheAdapter, RedisCacheSettings`
- Produces: Tests with a fake coredis client that raises `RedisError` on TrackingCache calls. Tests fail before Task 2.4 lands.

- [ ] **Step 1: Write the test file with a fake coredis client**

```python
# /Users/les/Projects/oneiric/tests/unit/test_redis_cache_degrade.py
"""TrackingCache degrade-graceful behavior tests."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from coredis.exceptions import RedisError
from pydantic import ValidationError

from oneiric.adapters.cache.redis import RedisCacheAdapter, RedisCacheSettings
from oneiric.core.lifecycle import LifecycleError


class _FakeTrackingUnsupportedClient:
    """Mimics a coredis.Redis whose TrackingCache operations raise."""

    def __init__(self) -> None:
        self.tracking_calls = 0
        self.get_calls = 0

    async def tracking_get(self, *_args: Any, **_kwargs: Any) -> Any:
        self.tracking_calls += 1
        raise RedisError("CLIENT TRACKING is not supported by this server")

    async def get(self, *_args: Any, **_kwargs: Any) -> Any:
        self.get_calls += 1
        return None

    async def set(self, *_args: Any, **_kwargs: Any) -> Any:
        return True

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


def _build_adapter_with(client: _FakeTrackingUnsupportedClient) -> RedisCacheAdapter:
    adapter = RedisCacheAdapter(
        RedisCacheSettings(
            enable_client_cache=True,
            fail_fast_on_tracking_unavailable=False,
        )
    )
    adapter._client = client
    return adapter


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tracking_cache_unsupported_degrades_gracefully(caplog: Any) -> None:
    fake = _FakeTrackingUnsupportedClient()
    adapter = _build_adapter_with(fake)

    with caplog.at_level("WARNING"):
        result = await adapter.get("k")

    assert result is None
    assert fake.tracking_calls == 1
    # Subsequent call should not retry TrackingCache.
    await adapter.get("k")
    assert fake.tracking_calls == 1
    assert fake.get_calls == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tracking_cache_unsupported_fail_fast_when_configured() -> None:
    fake = _FakeTrackingUnsupportedClient()
    adapter = RedisCacheAdapter(
        RedisCacheSettings(
            enable_client_cache=True,
            fail_fast_on_tracking_unavailable=True,
        )
    )
    adapter._client = fake

    with pytest.raises(LifecycleError):
        await adapter.get("k")
```

- [ ] **Step 2: Run the test file and confirm the two tests fail**

```bash
cd /Users/les/Projects/oneiric && pytest tests/unit/test_redis_cache_degrade.py -v
```

Expected: both tests fail. Acceptable messages: `AttributeError: 'RedisCacheAdapter' object has no attribute '_tracking_enabled'` (pre-implementation), or the call simply executes the un-wrapped TrackingCache code and the first call raises `RedisError` instead of degrading.

- [ ] **Step 3: Commit the failing tests**

```bash
cd /Users/les/Projects/oneiric && \
  git add tests/unit/test_redis_cache_degrade.py && \
  git commit -m "test(oneiric): cover TrackingCache degrade-graceful behavior"
```

#### Task 2.4: Implement TrackingCache degrade-graceful behavior in `RedisCacheAdapter`

**Files:**
- Modify: `/Users/les/Projects/oneiric/oneiric/adapters/cache/redis.py` — `RedisCacheAdapter` class methods that issue TrackingCache operations (`get`, `set`, `delete`, `many`, etc. — whatever the file currently calls into `self._client.tracking_*` family)

**Interfaces:**
- Consumes: existing `RedisCacheAdapter` and `_COREDIS_AVAILABLE` import block (lines 1-30); `self._client`, `self._settings`, `self._logger` already on instances
- Produces: `self._tracking_enabled: bool = True` initial state per instance; wrapped TrackingCache call sites that fall back to plain `get`/`set`/`delete` on `RedisError("TRACKING …")`; optional raise on `fail_fast_on_tracking_unavailable=True`

- [ ] **Step 1: Read the current RedisCacheAdapter implementation**

```bash
sed -n '90,250p' /Users/les/Projects/oneiric/oneiric/adapters/cache/redis.py
```

Locate every TrackingCache-style call site (`tracking_get`, `tracking_set`, etc., on `self._client`).

- [ ] **Step 2: Add `self._tracking_enabled` initialization and `self._disable_tracking(...)` helper**

In the `__init__` of `RedisCacheAdapter`, add (after `self._settings = settings or RedisCacheSettings()`):

```python
        self._tracking_enabled: bool = bool(self._settings.enable_client_cache)
```

Add a private helper method on the class:

```python
    def _disable_tracking(self, exc: Exception) -> None:
        """Emit the structured warn-and-disable log; raise if strict mode."""
        self._logger.warning(
            "tracking-cache-unsupported",
            backend="cache",
            provider="redis",
            error=str(exc),
        )
        self._tracking_enabled = False
        if self._settings.fail_fast_on_tracking_unavailable:
            raise LifecycleError("tracking-cache-unsupported") from exc
```

The `LifecycleError` import is `from oneiric.core.lifecycle import LifecycleError`. Confirm with `grep -n "LifecycleError" /Users/les/Projects/oneiric/oneiric/adapters/cache/redis.py` before running this step — if the import has moved, update the helper accordingly.

- [ ] **Step 3: Wrap TrackingCache call sites**

For every `tracking_get`/`tracking_set`/`tracking_delete` (and any other tracking-prefixed coredis method) currently in the file, wrap with the degrade-graceful pattern. Example for `get`:

```python
    async def get(self, key: str) -> Any | None:
        if self._tracking_enabled:
            try:
                return await self._client.tracking_get(key)
            except RedisError as exc:
                if "TRACKING" not in str(exc):
                    raise
                self._disable_tracking(exc)
        return await self._client.get(key)
```

Apply the same pattern to `set`, `delete`, `many`, etc. wherever TrackingCache is used. **Important:** the plain (non-tracking) fallback path (`return await self._client.get(key)`) must be invoked only after `self._tracking_enabled` is `False`. Do not re-attempt TrackingCache once disabled.

- [ ] **Step 4: Run the degrade tests and verify green**

```bash
cd /Users/les/Projects/oneiric && pytest tests/unit/test_redis_cache_degrade.py -v
```

Expected: both tests PASSED.

- [ ] **Step 5: Run the wider cache test suite**

```bash
cd /Users/les/Projects/oneiric && pytest tests/unit/ -k cache -v
```

Expected: previous cache tests still PASSED (no regression); new tests still PASSED.

- [ ] **Step 6: Run the entire Oneiric test suite**

```bash
cd /Users/les/Projects/oneiric && pytest tests/unit/ -q
```

Expected: all green. If a regression appears, fix it before committing this task.

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/oneiric && \
  git add oneiric/adapters/cache/redis.py && \
  git commit -m "feat(oneiric): degrade-graceful TrackingCache failure path

When enable_client_cache=True and the redis server rejects CLIENT TRACKING
(Redis 5 or restricted providers), log a structured warning and disable
TrackingCache for the lifetime of the adapter instead of failing the
call. Operators can set fail_fast_on_tracking_unavailable=True to restore
the strict behavior. Behavior is uniformly available to every consumer
of RedisCacheAdapter, not only Dhara."
```

- [ ] **Step 8: Direct-merge to `main` (no PR)**

```bash
cd /Users/les/Projects/oneiric && git push origin main
```

Expected: direct push to `main` succeeds. The user has authorized this per Bodai pre-1.0 policy.

#### Task 2.5: Verify the companion PR is fully landed

- [ ] **Step 1: Confirm the four commits (Tasks 2.1 / 2.2 / 2.3 / 2.4 / squashable) are on `main`**

```bash
git -C /Users/les/Projects/oneiric log --oneline main -10
```

Expected: the four (or, after squash, two) commits from this phase are at `HEAD`.

- [ ] **Step 2: Sanity-import the new fields from anywhere**

```bash
cd /Users/les/Projects/oneiric && \
  python -c "from oneiric.adapters.cache import RedisCacheSettings; s = RedisCacheSettings(ttl_seconds=120, fail_fast_on_tracking_unavailable=True); print(s.ttl_seconds, s.fail_fast_on_tracking_unavailable, s.stampede_jitter_ms, s.enable_client_cache)"
```

Expected: `120 True 0 True` (the last value being `enable_client_cache` default). If `ValidationError` or `AttributeError` appears, the merge is not yet effective in the target environment.

- [ ] **Step 3: Stop. Phase 3 cannot start until this step is green.**

---

### Phase 3: Main Dhara PR

**Goal:** Replace Dhara's parallel cache-adapter implementations with Oneiric's via a registry-mediated lookup; delete the now-redundant files; update tests accordingly. `Connection.Cache` is explicitly left alone.
**Tasks:** Tasks 3.1–3.8.
**Exit criteria:** Direct merge to `main` on `/Users/les/Projects/dhara`; `pytest dhara/tests/` is green; `audit_orphans.py` shows no new orphans; `benchmarks/test_cache.py` within 2× of Phase 1 baseline.

#### Integration Contract

- **Triggered from**: `dhara/mcp/server_core.py:__init__` reads `config.cache_backend` (string `memory` or `redis`) and calls `dhara.mcp.adapter_lookup.resolve_cache_adapter(backend, settings, registry)`. The endpoint symbol is `dhara.mcp.adapter_lookup.resolve_cache_adapter`. Operator override path: register a higher-priority `("adapter", "cache", backend)` triple through the existing Oneiric resolver and Dhara picks it up.
- **Returns to / updates**: `dhara/storage/redis_cache.py` (deleted), `dhara/storage/memory.py` (deleted), `dhara/tests/unit/test_redis_cache.py` (deleted), `dhara/core/config.py` fields `cache_redis_url`, `cache_redis_token`, `cache_ttl`, `cache_stampede_jitter_ms`, `cache_key_prefix` (deleted). New file `dhara/mcp/adapter_lookup.py` introduced. Two new test files `dhara/tests/unit/test_adapter_lookup.py` and `dhara/tests/unit/test_server_core_cache.py` introduced.
- **Demonstrable by**: `cd /Users/les/Projects/dhara && pytest tests/unit/test_adapter_lookup.py tests/unit/test_server_core_cache.py tests/unit/test_server_core.py tests/unit/test_dhara_settings.py -v` exits 0 with all listed tests PASSED. Manual smoke (Phase 4) further demonstrates end-to-end.
- **Rollback signal**: `pytest dhara/tests/` shows a regression on any pre-existing test (especially `test_connection_cache_injection.py`, `test_connection_abort.py`, or `test_cache.py` benchmark) OR `pytest dhara/tests/benchmarks/test_cache.py` shows >2× regression. Roll back via `git -C /Users/les/Projects/dhara revert HEAD`. The deleted modules exist in git history; `git checkout <pre-revert-sha>^ -- dhara/storage/redis_cache.py dhara/storage/memory.py` restores them; the same revert undoes the registry-mediated wiring.
- **Observability added**: structured log key `cache-adapter-resolved` from `dhara.mcp.server_core` startup path, carrying `(backend, provider, settings_class)`. Inherits `adapter-init` and `adapter-cleanup-complete` from Oneiric's adapters (now actually wired through Dhara's path).

#### Task 3.1: Failing tests for `dhara/mcp/adapter_lookup.py:resolve_cache_adapter`

**Files:**
- Create: `/Users/les/Projects/dhara/tests/unit/test_adapter_lookup.py`

**Interfaces:**
- Consumes: Dhara's `AsyncAdapterRegistry` instance (mocked in tests); the future `resolve_cache_adapter(backend: str, settings, registry) -> CacheAdapter` symbol
- Produces: Test module imports cleanly but fails because the helper does not exist yet

- [ ] **Step 1: Write the test file**

```python
# /Users/les/Projects/dhara/tests/unit/test_adapter_lookup.py
"""Tests for dhara.mcp.adapter_lookup.resolve_cache_adapter."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from dhara.mcp.adapter_lookup import resolve_cache_adapter
from oneiric.adapters.cache import MemoryCacheAdapter, RedisCacheAdapter, RedisCacheSettings
from oneiric.core.lifecycle import LifecycleError


def _make_registry(entries: dict[tuple[str, str, str], Any]) -> MagicMock:
    """entries: (domain, key, provider) -> factory-string."""
    reg = MagicMock()
    async def get_adapter(domain: str, key: str, provider: str) -> Any:
        factory = entries.get((domain, key, provider))
        if factory is None:
            raise LookupError(f"no entry for {(domain, key, provider)}")
        return MagicMock(factory=factory)
    reg.get_adapter = get_adapter
    return reg


def _import(name: str) -> Any:
    module_name, _, attr = name.partition(":")
    import importlib
    module = importlib.import_module(module_name)
    return getattr(module, attr)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolves_memory_backend_to_memory_cache_adapter() -> None:
    reg = _make_registry({
        ("adapter", "cache", "memory"): "oneiric.adapters.cache.memory:MemoryCacheAdapter",
    })
    adapter = await resolve_cache_adapter("memory", None, reg, _import)
    assert isinstance(adapter, MemoryCacheAdapter)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolves_redis_backend_to_redis_cache_adapter() -> None:
    settings = RedisCacheSettings(url="redis://example:6379/0")
    reg = _make_registry({
        ("adapter", "cache", "redis"): "oneiric.adapters.cache.redis:RedisCacheAdapter",
    })
    adapter = await resolve_cache_adapter("redis", settings, reg, _import)
    assert isinstance(adapter, RedisCacheAdapter)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unknown_backend_raises_lifecycle_error() -> None:
    reg = _make_registry({})  # empty
    with pytest.raises(LifecycleError):
        await resolve_cache_adapter("redis", None, reg, _import)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_init_is_awaited_on_resolved_adapter() -> None:
    """resolve_cache_adapter must await adapter.init() before returning."""
    init = AsyncMock()
    sentinel = MagicMock(spec=MemoryCacheAdapter)
    sentinel.init = init
    sentinel.__class__ = MemoryCacheAdapter
    reg = MagicMock()
    async def get_adapter(domain: str, key: str, provider: str) -> Any:
        return MagicMock(factory="oneiric.adapters.cache.memory:MemoryCacheAdapter")
    reg.get_adapter = get_adapter

    def fake_import(name: str) -> Any:
        if name == "oneiric.adapters.cache.memory:MemoryCacheAdapter":
            return lambda settings: sentinel
        return _import(name)
    adapter = await resolve_cache_adapter("memory", None, reg, fake_import)
    init.assert_awaited_once()
    assert adapter is sentinel
```

- [ ] **Step 2: Run and confirm import-level failures**

```bash
cd /Users/les/Projects/dhara && pytest tests/unit/test_adapter_lookup.py -v
```

Expected: `ModuleNotFoundError: No module named 'dhara.mcp.adapter_lookup'`. Tests don't have a chance to run.

- [ ] **Step 3: Commit the failing tests**

```bash
cd /Users/les/Projects/dhara && \
  git add tests/unit/test_adapter_lookup.py && \
  git commit -m "test(dhara): add failing tests for cache-adapter lookup helper"
```

#### Task 3.2: Implement `dhara/mcp/adapter_lookup.py`

**Files:**
- Create: `/Users/les/Projects/dhara/dhara/mcp/adapter_lookup.py`

**Interfaces:**
- Consumes: existing Dhara `AsyncAdapterRegistry` (provides `await registry.get_adapter(domain, key, provider)` returning an object with a `.factory` attribute — the importable path). `oneiric.adapters.cache.{MemoryCacheAdapter, RedisCacheAdapter}` are constructed via `import_string(factory)`. `_import(name)` is an injection seam for tests; default is `lambda n: importlib.import_module(...).attr`.
- Produces: `async resolve_cache_adapter(backend: Literal["memory", "redis"], settings, registry, import_fn=_default_import) -> CacheAdapter`

- [ ] **Step 1: Write the helper**

```python
# /Users/les/Projects/dhara/dhara/mcp/adapter_lookup.py
"""Registry-mediated cache-adapter lookup for the Dhara MCP server.

Centralizes the pattern of asking Oneiric's resolver for the right
adapter class, importing it via the factory string Dhara already
stores in its AsyncAdapterRegistry, instantiating with caller-supplied
settings, and awaiting init() before returning.

The settings argument is forwarded verbatim to whichever adapter class
the registry resolves. MemoryCacheAdapter and RedisCacheAdapter both
accept None for "use defaults".
"""
from __future__ import annotations

import importlib
from typing import Any, Callable, Literal

from oneiric.core.lifecycle import LifecycleError

Backend = Literal["memory", "redis"]

ImportFn = Callable[[str], Any]


def _default_import(name: str) -> Any:
    module_name, _, attr = name.partition(":")
    module = importlib.import_module(module_name)
    return getattr(module, attr)


async def resolve_cache_adapter(
    backend: Backend,
    settings: Any,
    registry: Any,
    import_fn: ImportFn = _default_import,
) -> Any:
    """Resolve and instantiate the cache adapter for `backend` via Dhara's registry.

    Awaits adapter.init() so the caller receives a fully-initialized
    adapter ready to handle requests. Raises LifecycleError if the
    registry has no entry for the (domain="adapter", key="cache",
    provider=backend) triple — a hard failure, not a silent fallback.
    """
    entry = await registry.get_adapter("adapter", "cache", backend)
    factory_string = getattr(entry, "factory", None)
    if not factory_string:
        raise LifecycleError(
            f"registry returned no factory for cache adapter backend={backend}"
        )
    try:
        adapter_cls = import_fn(factory_string)
    except (ImportError, AttributeError) as exc:
        raise LifecycleError(
            f"failed to import cache adapter factory {factory_string!r}"
        ) from exc
    instance = adapter_cls(settings)
    await instance.init()
    return instance
```

- [ ] **Step 2: Run the new tests and verify green**

```bash
cd /Users/les/Projects/dhara && pytest tests/unit/test_adapter_lookup.py -v
```

Expected: all 4 tests PASSED.

- [ ] **Step 3: Run the wider mcp/server_core tests to verify no import-time regression**

```bash
cd /Users/les/Projects/dhara && pytest tests/unit/test_server_core.py -v
```

Expected: existing tests PASSED (or fail because of stale `dhara.storage.redis_cache` imports — those failures are *expected* at this stage and will be addressed in Task 3.6).

- [ ] **Step 4: Commit**

```bash
cd /Users/les/Projects/dhara && \
  git add dhara/mcp/adapter_lookup.py && \
  git commit -m "feat(dhara): add registry-mediated cache-adapter lookup helper"
```

#### Task 3.3: Wire `dhara/mcp/server_core.py` to use the helper

**Files:**
- Modify: `/Users/les/Projects/dhara/dhara/mcp/server_core.py:197-212` (the `cache_backend` switch block)

**Interfaces:**
- Consumes: `dhara.mcp.adapter_lookup.resolve_cache_adapter` (just introduced); `config.cache_backend` (still a `Literal["memory", "redis"]` on Dhara's settings); Oneiric's `RedisCacheSettings` (with the three new fields) and `MemoryCacheSettings` (defaults).
- Produces: `self.cache` is now a Oneiric cache adapter (`MemoryCacheAdapter` or `RedisCacheAdapter`); structured log `cache-adapter-resolved` at startup; `await self.cache.X(...)` paths continue to work.

- [ ] **Step 1: Read the current cache_backend switch block**

```bash
sed -n '190,230p' /Users/les/Projects/dhara/dhara/mcp/server_core.py
```

Capture the existing imports from `dhara.storage.redis_cache` and the existing `if cache_backend == "redis"` / `else` structure.

- [ ] **Step 2: Remove the `dhara.storage.redis_cache` import**

In `/Users/les/Projects/dhara/dhara/mcp/server_core.py`, find the line that imports from `dhara.storage.redis_cache` (top-of-file imports) and delete it.

- [ ] **Step 3: Add the new import**

Add to the top-of-file imports of `/Users/les/Projects/dhara/dhara/mcp/server_core.py`:

```python
from oneiric.adapters.cache import (
    MemoryCacheSettings,
    RedisCacheSettings,
)
```

(Keep the existing `from oneiric.adapters.cache.memory import MemoryCacheAdapter, MemoryCacheSettings` etc. lines that may already be present; if duplicated, keep only the consolidated import.)

- [ ] **Step 4: Replace the cache_backend switch with a call to resolve_cache_adapter**

Replace the existing `if cache_backend == "redis": ... else: ...` block (lines 197-212) with:

```python
            cache_backend = getattr(config, "cache_backend", "memory")
            if cache_backend == "redis":
                cache_settings = RedisCacheSettings(
                    url=getattr(config, "cache_oneiric_url", None),
                    host=getattr(config, "cache_oneiric_host", "localhost"),
                    port=getattr(config, "cache_oneiric_port", 6379),
                    ttl_seconds=getattr(config, "cache_ttl", 3600),
                    stampede_jitter_ms=getattr(
                        config, "cache_stampede_jitter_ms", 0
                    ),
                    key_prefix=getattr(
                        config, "cache_key_prefix", "dhara:cache:"
                    ),
                )
            else:
                cache_settings = MemoryCacheSettings()
            self.cache = await resolve_cache_adapter(
                cache_backend, cache_settings, self._async_adapter_registry
            )
            self._logger.info(
                "cache-adapter-resolved",
                backend=cache_backend,
                provider=cache_backend,
                settings_class=type(cache_settings).__name__,
            )
```

Note: any `dhara-specific` config aliases (`cache_redis_url/token/ttl/stampede_jitter_ms/key_prefix`) are *deleted* in Task 3.5; the `getattr(..., default)` defaults preserve the previous numeric defaults during the transition window until Task 3.5's config cleanup drops them. If the value isn't present (because Task 3.5 ran first), `getattr` returns the default — that's fine.

- [ ] **Step 5: Add the import for resolve_cache_adapter**

Add to top-of-file imports:

```python
from dhara.mcp.adapter_lookup import resolve_cache_adapter
```

- [ ] **Step 6: Run server_core tests (they will fail until Task 3.6 rebases patch targets)**

```bash
cd /Users/les/Projects/dhara && pytest tests/unit/test_server_core.py -v
```

Expected: some failures citing `dhara.storage.redis_cache.RedisCacheAdapter` import paths. That's expected; Task 3.6 fixes the patches.

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/dhara && \
  git add dhara/mcp/server_core.py && \
  git commit -m "refactor(dhara): rewire MCP-server cache through registry helper"
```

#### Task 3.4: Failing tests for the new server-core wiring

**Files:**
- Create: `/Users/les/Projects/dhara/tests/unit/test_server_core_cache.py`

**Interfaces:**
- Consumes: `dhara.mcp.server_core` (now updated); `resolve_cache_adapter` (introduced in Task 3.2); existing test patterns from `tests/unit/test_server_core.py`
- Produces: Tests covering cache_backend=memory wires `MemoryCacheAdapter`, cache_backend=redis wires `RedisCacheAdapter`, structured `cache-adapter-resolved` log line emits at startup

- [ ] **Step 1: Write the test file**

```python
# /Users/les/Projects/dhara/tests/unit/test_server_core_cache.py
"""End-to-end tests for cache-adapter wiring in dhara.mcp.server_core."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oneiric.adapters.cache import (
    MemoryCacheAdapter,
    MemoryCacheSettings,
    RedisCacheAdapter,
    RedisCacheSettings,
)


def _build_config(cache_backend: str = "memory") -> Any:
    cfg = MagicMock()
    cfg.cache_backend = cache_backend
    cfg.cache_oneiric_url = None
    cfg.cache_oneiric_host = "localhost"
    cfg.cache_oneiric_port = 6379
    cfg.cache_ttl = 3600
    cfg.cache_stampede_jitter_ms = 0
    cfg.cache_key_prefix = "dhara:cache:"
    return cfg


def _build_server_core_stub() -> Any:
    core = MagicMock()
    core._async_adapter_registry = MagicMock()
    core._logger = MagicMock()
    return core


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_backend_wires_memory_cache_adapter() -> None:
    from dhara.mcp import server_core

    fake_sentinel = MagicMock(spec=MemoryCacheAdapter)
    fake_sentinel.__class__ = MemoryCacheAdapter

    async def run() -> None:
        with patch(
            "dhara.mcp.adapter_lookup.resolve_cache_adapter",
            AsyncMock(return_value=fake_sentinel),
        ):
            cfg = _build_config("memory")
            core = _build_server_core_stub()
            result = await server_core._wire_cache(cfg, core)
            assert isinstance(result, MemoryCacheAdapter)
            assert result is fake_sentinel

    await run()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_redis_backend_wires_redis_cache_adapter() -> None:
    from dhara.mcp import server_core

    fake_sentinel = MagicMock(spec=RedisCacheAdapter)
    fake_sentinel.__class__ = RedisCacheAdapter

    async def run() -> None:
        with patch(
            "dhara.mcp.adapter_lookup.resolve_cache_adapter",
            AsyncMock(return_value=fake_sentinel),
        ):
            cfg = _build_config("redis")
            core = _build_server_core_stub()
            result = await server_core._wire_cache(cfg, core)
            assert isinstance(result, RedisCacheAdapter)

    await run()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cache_adapter_resolved_log_fires_at_startup() -> None:
    from dhara.mcp import server_core

    fake_sentinel = MagicMock(spec=MemoryCacheAdapter)
    fake_sentinel.__class__ = MemoryCacheAdapter

    async def run() -> None:
        with patch(
            "dhara.mcp.adapter_lookup.resolve_cache_adapter",
            AsyncMock(return_value=fake_sentinel),
        ):
            cfg = _build_config("memory")
            core = _build_server_core_stub()
            await server_core._wire_cache(cfg, core)
            core._logger.info.assert_any_call(
                "cache-adapter-resolved",
                backend="memory",
                provider="memory",
                settings_class="MemoryCacheSettings",
            )

    await run()
```

- [ ] **Step 2: Confirm tests fail (server_core doesn't yet have `_wire_cache`)**

```bash
cd /Users/les/Projects/dhara && pytest tests/unit/test_server_core_cache.py -v
```

Expected: `AttributeError: module 'dhara.mcp.server_core' has no attribute '_wire_cache'`.

- [ ] **Step 3: Commit the failing tests**

```bash
cd /Users/les/Projects/dhara && \
  git add tests/unit/test_server_core_cache.py && \
  git commit -m "test(dhara): cover cache-adapter wiring path through server_core"
```

#### Task 3.5: Extract the wiring path into `_wire_cache` so the helper is testable

**Files:**
- Modify: `/Users/les/Projects/dhara/dhara/mcp/server_core.py` — refactor the block created in Task 3.3 into a private async helper, then call it from `__init__`.

**Interfaces:**
- Consumes: `config` (Dhara settings); `core_self` (the `MCPServerCore` instance); the new `resolve_cache_adapter` helper
- Produces: `async def _wire_cache(config, core_self) -> CacheAdapter` — single-purpose, fully unit-testable

- [ ] **Step 1: Add the private helper above the `MCPServerCore` class definition**

```python
async def _wire_cache(config: Any, core_self: Any) -> Any:
    """Wire Dhara's MCP-server cache through the registry helper.

    Returns the initialized CacheAdapter instance. Emits a structured
    'cache-adapter-resolved' log line on the owning server's logger.
    """
    cache_backend = getattr(config, "cache_backend", "memory")
    if cache_backend == "redis":
        cache_settings = RedisCacheSettings(
            url=getattr(config, "cache_oneiric_url", None),
            host=getattr(config, "cache_oneiric_host", "localhost"),
            port=getattr(config, "cache_oneiric_port", 6379),
            ttl_seconds=getattr(config, "cache_ttl", 3600),
            stampede_jitter_ms=getattr(
                config, "cache_stampede_jitter_ms", 0
            ),
            key_prefix=getattr(
                config, "cache_key_prefix", "dhara:cache:"
            ),
        )
    else:
        cache_settings = MemoryCacheSettings()
    adapter = await resolve_cache_adapter(
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

- [ ] **Step 2: Replace the inline wiring block (from Task 3.3) with a call**

In `MCPServerCore.__init__`, replace the inline block from Task 3.3 with:

```python
            self.cache = await _wire_cache(config, self)
```

- [ ] **Step 3: Run the new tests and verify green**

```bash
cd /Users/les/Projects/dhara && pytest tests/unit/test_server_core_cache.py -v
```

Expected: all 3 tests PASSED.

- [ ] **Step 4: Commit**

```bash
cd /Users/les/Projects/dhara && \
  git add dhara/mcp/server_core.py && \
  git commit -m "refactor(dhara): extract cache wiring into _wire_cache helper"
```

#### Task 3.6: Drop deprecated config fields and remove `cache_redis_url/token/...` aliases

**Files:**
- Modify: `/Users/les/Projects/dhara/dhara/core/config.py`
- Modify: `/Users/les/Projects/dhara/tests/unit/test_dhara_settings.py`

**Interfaces:**
- Consumes: existing `core_config.py`'s `cache_redis_url`, `cache_redis_token`, `cache_ttl`, `cache_stampede_jitter_ms`, `cache_key_prefix` definitions; existing settings tests
- Produces: only `cache_backend: str` remains on Dhara's config model; old fields are *gone*, not deprecated.

- [ ] **Step 1: Read the current cache section of config.py**

```bash
sed -n '130,160p' /Users/les/Projects/dhara/dhara/core/config.py
```

- [ ] **Step 2: Delete the deprecated fields**

In `/Users/les/Projects/dhara/dhara/core/config.py`, delete the lines that define:

```python
    cache_redis_url: str = Field(...)
    cache_redis_token: str = Field(...)
    cache_ttl: int = Field(...)
    cache_stampede_jitter_ms: int = Field(...)
    cache_key_prefix: str = Field(...)
```

Keep only:

```python
    cache_backend: str = Field(default="memory", description="memory or redis")
```

- [ ] **Step 3: Update `_wire_cache` to drop the getattr-and-default dance**

In `/Users/les/Projects/dhara/dhara/mcp/server_core.py`, simplify `_wire_cache` so it no longer reads `cache_oneiric_url/host/port/ttl/stampede_jitter_ms/key_prefix` from `config`. The simplified helper should read its settings from `OneiricMCPConfig` directly:

```python
async def _wire_cache(config: Any, core_self: Any) -> Any:
    """Wire Dhara's MCP-server cache through the registry helper."""
    cache_backend = getattr(config, "cache_backend", "memory")
    if cache_backend == "redis":
        from oneiric.core.config import OneiricMCPConfig

        # Pull the operator's settings from the canonical Oneiric config path.
        oneiric_cfg = OneiricMCPConfig()  # or however Dhara currently constructs it
        cache_settings = oneiric_cfg.adapters.cache.redis.settings
    else:
        cache_settings = MemoryCacheSettings()
    adapter = await resolve_cache_adapter(
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

Exact path: confirm by inspecting how `core_self._async_adapter_registry` is currently constructed in `server_core.py:__init__` and how Dhara currently loads OneiricMCPConfig. **Adjust the oneiric_cfg construction to match existing patterns in the file.** This is one place where Phase-3-task-executor may need to read more of `server_core.py:__init__` than the snippet above; the surrounding code is the source of truth.

- [ ] **Step 4: Update `tests/unit/test_dhara_settings.py`**

Open the file. Delete every test that references `cache_redis_url`, `cache_redis_token`, `cache_ttl`, `cache_stampede_jitter_ms`, or `cache_key_prefix`. Keep:

```python
def test_cache_backend_defaults_to_memory() -> None:
    settings = ... # whatever the existing default-test constructs
    assert settings.cache_backend == "memory"
```

If `test_env_overrides_cache_backend` exists, keep that too. The other tests in this file are untouched.

- [ ] **Step 5: Run the settings tests and verify green**

```bash
cd /Users/les/Projects/dhara && pytest tests/unit/test_dhara_settings.py -v
```

Expected: all kept tests PASSED.

- [ ] **Step 6: Run the cache tests to confirm no regression**

```bash
cd /Users/les/Projects/dhara && pytest tests/unit/test_server_core_cache.py tests/unit/test_adapter_lookup.py -v
```

Expected: green.

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/dhara && \
  git add dhara/core/config.py tests/unit/test_dhara_settings.py dhara/mcp/server_core.py && \
  git commit -m "refactor(dhara): drop deprecated cache config fields, source from OneiricMCPConfig"
```

#### Task 3.7: Rebase `tests/unit/test_server_core.py` patch targets

**Files:**
- Modify: `/Users/les/Projects/dhara/tests/unit/test_server_core.py`

**Interfaces:**
- Consumes: existing tests in `test_server_core.py`; the new `dhara.mcp.adapter_lookup.resolve_cache_adapter` symbol
- Produces: Tests no longer patch `dhara.storage.redis_cache.RedisCacheAdapter` (which is about to be deleted); instead patch `dhara.mcp.adapter_lookup.resolve_cache_adapter`.

- [ ] **Step 1: Locate every patch of the old adapter in `test_server_core.py`**

```bash
grep -n 'dhara.storage.redis_cache\|dhara.storage.memory' /Users/les/Projects/dhara/tests/unit/test_server_core.py
```

- [ ] **Step 2: Replace each occurrence with the helper patch**

For every `@patch("dhara.storage.redis_cache.RedisCacheAdapter")` decorator and similar, change to:

```python
@patch("dhara.mcp.adapter_lookup.resolve_cache_adapter")
```

Adjust the matching `with patch(...)` blocks similarly. Update test bodies that reference `MagicMock(spec=...)` for the old class to be `AsyncMock(return_value=...)` pointing at the helper.

- [ ] **Step 3: Run the test module**

```bash
cd /Users/les/Projects/dhara && pytest tests/unit/test_server_core.py -v
```

Expected: every test in the file PASSES (or, pre-Task 3.8, fails because `dhara.storage.redis_cache` no longer exists — that's expected; Task 3.8 will land the deletion, after which these tests go green).

- [ ] **Step 4: Commit**

```bash
cd /Users/les/Projects/dhara && \
  git add tests/unit/test_server_core.py && \
  git commit -m "test(dhara): repoint server_core patches from local adapter to registry helper"
```

#### Task 3.8: Delete the duplicated Dhara modules and run the full suite

**Files:**
- Delete: `/Users/les/Projects/dhara/dhara/storage/redis_cache.py`
- Delete: `/Users/les/Projects/dhara/dhara/storage/memory.py`
- Delete: `/Users/les/Projects/dhara/tests/unit/test_redis_cache.py`

**Interfaces:**
- Consumes: nothing — purely deletion
- Produces: the three files no longer exist on disk; nothing else imports them

- [ ] **Step 1: Delete the production modules**

```bash
cd /Users/les/Projects/dhara && \
  git rm dhara/storage/redis_cache.py dhara/storage/memory.py
```

Expected: both files staged for deletion.

- [ ] **Step 2: Delete the test module**

```bash
cd /Users/les/Projects/dhara && \
  git rm tests/unit/test_redis_cache.py
```

Expected: file staged for deletion.

- [ ] **Step 3: Search the whole repo for any remaining import of the deleted modules**

```bash
cd /Users/les/Projects/dhara && \
  grep -rn 'dhara.storage.redis_cache\|dhara.storage.memory' dhara/ tests/ \
  || echo "no remaining references"
```

Expected: `no remaining references`. If anything still imports them, fix that importer before proceeding.

- [ ] **Step 4: Run the full Dhara test suite**

```bash
cd /Users/les/Projects/dhara && pytest dhara/tests/ -q
```

Expected: all green. If a regression appears, fix before committing.

- [ ] **Step 5: Run the regression-guard Connection.Cache tests**

```bash
cd /Users/les/Projects/dhara && pytest tests/unit/test_connection_cache_injection.py tests/unit/test_connection_abort.py -v
```

Expected: green.

- [ ] **Step 6: Run the benchmark and compare against Phase 1 baseline**

```bash
cd /Users/les/Projects/dhara && \
  pytest tests/benchmarks/test_cache.py 2>&1 | tail -10
```

Expected: numbers within 2× of `benchmarks-baseline.txt` from Phase 1, Task 1.1. If >2× slower, **stop** and surface; the spec's rollback signal applies.

- [ ] **Step 7: Run audit_orphans.py**

```bash
cd /Users/les/Projects/dhara && python scripts/audit_orphans.py 2>&1 | tail -30
```

Expected: zero recently-added symbols with zero callers. If orphans appear, follow the audit's guidance (the project mandates this per CLAUDE.md Process Discipline).

- [ ] **Step 8: Commit the deletions and run results**

```bash
cd /Users/les/Projects/dhara && \
  git commit -m "refactor(dhara): delete dhara.storage.cache duplicates now unused

The companion Oneiric PR (settings extensions + TrackingCache
degrade-graceful) is merged. Dhara's MCP server now resolves cache
adapters through dhara.mcp.adapter_lookup, so the local parallel
implementations in dhara/storage/{redis_cache,memory}.py are unused.
Removing them eliminates the duplicated code paths.

Connection.Cache (dhara/core/connection.py:841) is intentionally
untouched per spec D8; it's a domain-specific Persistent-object LRU,
not a generic KV cache. A follow-up spec may define a
PersistentObjectCacheAdapter in Oneiric."
```

- [ ] **Step 9: Direct-merge to `main` (no PR)**

```bash
cd /Users/les/Projects/dhara && git push origin main
```

Expected: push succeeds. Per Bodai pre-1.0 policy, no PR review.

---

## 6. Required Code Changes

Grouped by repo, with file role (Create / Modify / Delete).

### Oneiric (Phase 2)

- **Modify** `/Users/les/Projects/oneiric/oneiric/adapters/cache/redis.py`:
  - `+3` fields on `RedisCacheSettings` (Task 2.2)
  - `+1` helper `_disable_tracking` on `RedisCacheAdapter` and wrapped TrackingCache call sites (Task 2.4)
  - `+1` instance attribute `self._tracking_enabled: bool` (Task 2.4)
- **Create** `/Users/les/Projects/oneiric/tests/unit/test_redis_cache_settings.py` (Task 2.1)
- **Create** `/Users/les/Projects/oneiric/tests/unit/test_redis_cache_degrade.py` (Task 2.3)

### Dhara (Phase 3)

- **Create** `/Users/les/Projects/dhara/dhara/mcp/adapter_lookup.py` (Task 3.2)
- **Create** `/Users/les/Projects/dhara/tests/unit/test_adapter_lookup.py` (Task 3.1)
- **Create** `/Users/les/Projects/dhara/tests/unit/test_server_core_cache.py` (Task 3.4)
- **Modify** `/Users/les/Projects/dhara/dhara/mcp/server_core.py`:
  - Remove `dhara.storage.redis_cache` import (Task 3.3)
  - Add `from oneiric.adapters.cache import MemoryCacheSettings, RedisCacheSettings` and `from dhara.mcp.adapter_lookup import resolve_cache_adapter` (Task 3.3)
  - Replace the inline cache_backend switch with a call to `_wire_cache` (Tasks 3.3 + 3.5)
  - Extract `_wire_cache(config, core_self) -> CacheAdapter` as a module-private helper (Task 3.5)
  - Simplify `_wire_cache` to source settings from `OneiricMCPConfig` rather than Dhara-local config (Task 3.6)
- **Modify** `/Users/les/Projects/dhara/dhara/core/config.py`:
  - Drop `cache_redis_url`, `cache_redis_token`, `cache_ttl`, `cache_stampede_jitter_ms`, `cache_key_prefix` (Task 3.6)
  - Keep `cache_backend: str = Field(default="memory", ...)`
- **Modify** `/Users/les/Projects/dhara/tests/unit/test_dhara_settings.py`:
  - Delete tests referencing the dropped fields (Task 3.6)
  - Keep the `cache_backend == "memory"` default test
- **Modify** `/Users/les/Projects/dhara/tests/unit/test_server_core.py`:
  - Replace `@patch("dhara.storage.redis_cache.RedisCacheAdapter")` and similar with `@patch("dhara.mcp.adapter_lookup.resolve_cache_adapter")` (Task 3.7)
- **Delete** `/Users/les/Projects/dhara/dhara/storage/redis_cache.py` (Task 3.8)
- **Delete** `/Users/les/Projects/dhara/dhara/storage/memory.py` (Task 3.8)
- **Delete** `/Users/les/Projects/dhara/tests/unit/test_redis_cache.py` (Task 3.8)

### Files explicitly NOT touched

- `/Users/les/Projects/dhara/dhara/core/connection.py:841 class Cache` — out of scope (spec D8)
- `/Users/les/Projects/dhara/dhara/__init__.py` — public API surface unchanged; no exports deleted
- `/Users/les/Projects/dhara/tests/unit/test_connection_cache_injection.py` — regression guard
- `/Users/les/Projects/dhara/tests/unit/test_connection_abort.py` — regression guard
- `/Users/les/Projects/dhara/tests/benchmarks/test_cache.py` — regression guard; run as-is for baseline comparison
- `/Users/les/Projects/oneiric/oneiric/adapters/dhara_pusher.py` — already pushes Oneiric → Dhara; works as-is once the companion settings fields land

---

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `git -C /Users/les/Projects/oneiric log --oneline main \| head -5` | Last commit is the Companion Oneiric PR (Phase 2.4 squash) | `main` head |
| `python -c "from oneiric.adapters.cache import RedisCacheSettings; s=RedisCacheSettings(ttl_seconds=60); print(s.ttl_seconds)"` | `60` | Shell stdout |
| `cd /Users/les/Projects/oneiric && pytest tests/unit/ -q` | All green | Test output |
| `cd /Users/les/Projects/dhara && pytest tests/unit/test_adapter_lookup.py tests/unit/test_server_core_cache.py tests/unit/test_server_core.py tests/unit/test_dhara_settings.py -v` | All green | Test output |
| `cd /Users/les/Projects/dhara && pytest tests/unit/test_connection_cache_injection.py tests/unit/test_connection_abort.py -v` | All green | Test output |
| `cd /Users/les/Projects/dhara && pytest tests/benchmarks/test_cache.py 2>&1 \| tail -10` | Within 2× of Phase 1 baseline | `benchmarks-baseline.txt` |
| `cd /Users/les/Projects/dhara && python scripts/audit_orphans.py` | Zero recently-added orphans | Audit output |
| `grep -rn 'dhara.storage.redis_cache\|dhara.storage.memory' dhara/ tests/` (in Dhara) | No matches (after Task 3.8) | Grep output |
| Manual smoke: `dhara -s --file /tmp/smoke.dhara` | Server starts; `/health` reports `cache=memory`; `cache-adapter-resolved` log fires | Dhara log + `/health` JSON |

---

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Phase 1 async-migration cleanup has not yet landed, breaking the start-gate | Medium | Run Task 1.1, Step 1 first; if it fails, surface immediately and stop. |
| Oneiric PR's `_tracking_enabled` initialization interferes with existing TrackingCache behavior (e.g., double-disable, races during `init`) | Low–Medium | Task 2.4 wraps every tracking-prefixed call site in the same pattern; tests in Task 2.3 cover both the degrade path and the strict path. Run the entire Oneiric suite in Step 2.4.6 before committing. |
| `dhara.mcp.adapter_lookup.resolve_cache_adapter` defined with slightly different signatures across tasks | Low | Task 3.2 locks the signature; Task 3.1 tests use the same signature; Task 3.5 reuses; consistency is enforced by the tests in `test_adapter_lookup.py`. |
| Dhara-specific `cache_redis_url`-style fields still referenced by `_wire_cache` after Task 3.6 simplifies the helper | Low | Task 3.6 explicitly rewrites `_wire_cache` to source from `OneiricMCPConfig` and deletes the `getattr(..., default)` dance. Tests in `test_server_core_cache.py` continue to pass because they construct settings via `MagicMock`. |
| `benchmarks/test_cache.py` regresses >2× | Low | The benchmark is unaffected by the changes; the only file in the same area is `core/connection.py`, which is *untouched*. If regression >2× appears, the spec's rollback signal applies: revert HEAD; restore the deleted files from git history. |
| `scripts/audit_orphans.py` flags the new helper because it's used only by `server_core.py` in a way the audit can't see | Low | `adapter_lookup.py` is called from `_wire_cache` in `server_core.py`; the audit should follow that. If orphan, the audit will list the symbol — caller follows audit guidance per CLAUDE.md Process Discipline. |
| Operator override path via Oneiric config not exercised in tests | Medium | Tests cover the default-resolve path; operator override is an unstated assumption that Oneiric's existing config-overload machinery already works (per prior usage in `AdapterDiscovery`). Not adding a dedicated override test in this plan; flag for follow-up. |
| `crackerjack` post-merge invocation does not actually exist or has moved | Medium | Phase 4 is a checklist-only phase; operator performs the actual bump. The plan records *what* should happen; the executor does not run it. |

---

## 9. Decision Rule

This plan is **"done enough"** when the Phase 3 main Dhara PR has merged to `main` (commit `git -C /Users/les/Projects/dhara rev-parse HEAD` matches the commit produced by Task 3.8), `pytest dhara/tests/` is green, `audit_orphans.py` shows no orphans, and `benchmarks/test_cache.py` is within 2× of the Phase 1 baseline.

**Cut order** (when scope pressure forces a cut — not expected here):
1. Phase 2 Settings-field tests (Task 2.1) — non-critical for the main Dhara PR if we accept that Oneiric's own Pydantic round-trip tests cover them.
2. Phase 3 Task 3.4 tests (server-core cache wiring) — non-critical if we accept manual smoke as the demonstration.
3. Phase 3 Task 3.1 tests (adapter_lookup helper) — non-critical if we accept manual smoke.
4. **Phase 3 Tasks 3.5–3.8** (helper extraction, config cleanup, deletion, full-suite validation) — **never cut**. These are the only ones that actually deliver consolidation.

Phase 4 (operator `crackerjack` ceremony) is intentionally outside this plan; the operator runs it from the project's `crackerjack` invocations, not from here.

---

## References

- Spec: `/Users/les/Projects/dhara/docs/superpowers/specs/2026-07-15-dhara-cache-adapter-oneiric-consolidation-design.md`
- Spec template: `/Users/les/Projects/mahavishnu/docs/plans/TEMPLATE.md`
- Plan siblings: `/Users/les/Projects/dhara/docs/superpowers/plans/2026-05-31-{btree-redesign,dhara-async-first}-plan.md`
- Active in-flight plan that must land first: `/Users/les/Projects/dhara/docs/2026-07-15-async-migration-cleanup.md`
- Audit gate: `scripts/audit_orphans.py` (per CLAUDE.md Process Discipline)
- Policy root: `/Users/les/Projects/mahavishnu/.claude/decisions/wire-up-contract.md`
