# Oneiric Cache-Adapter Factory-String Fix and Settings Fields

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-07-15
**Status:** active, implementation
**Owner:** Bodai maintainers
**Scope:** Two additive changes in Oneiric's `cache` adapter module:
(1) strip the leading space from `AdapterMetadata.factory` strings in `redis.py` and `memory.py`; (2) add two new fields to `RedisCacheSettings` (`ttl_seconds`, `stampede_jitter_ms`) and add consumer code in `RedisCacheAdapter.set()` and `get()` so Dhara's TTL / stampede-jitter semantics flow through after it migrates to Oneiric's adapters.
**Purpose:** Land the Oneiric-side changes that the cross-cutting cache-adapter consolidation depends on, before the Dhara-side wire-up lands.

**Spec:** `/Users/les/Projects/dhara/docs/superpowers/specs/2026-07-15-dhara-cache-adapter-oneiric-consolidation-design.md` (revised post-review)

**Companion plan (Dhara-side, blocked on async-migration):** `/Users/les/Projects/dhara/docs/superpowers/plans/2026-07-15-dhara-cache-adapter-oneiric-consolidation-plan.md`

**Architecture:** Single companion PR against Oneiric. Diff is additive: factory strings + settings + set/get consumer. No API breakage; existing `RedisCacheAdapter` callers that don't pass `ttl_seconds` / `stampede_jitter_ms` see no change (defaults are `3600` and `0`).

**Tech Stack:** Python 3.13; Pydantic v2 (`pydantic>=2.12.5`); pytest (asyncio_mode = auto, so `@pytest.mark.asyncio` is redundant); coredis.

## Global Constraints

1. **Bodai pre-1.0 merge policy** — direct merge to `main` on Oneiric, **no PR**.
2. **Independent sequencing.** This plan has no Dhara-side preconditions. It does **not** wait for `2026-07-15-async-migration-cleanup.md` to merge, because it does not touch `dhara/mcp/server_core.py`. It can ship now.
3. **From Oneiric / `CLAUDE.md`** — `from __future__ import annotations` as first non-comment line of every source file; `X | None = None`, never bare `= None`; no `assert` in production code; `logger.exception(...)` not `logger.error(..., exc_info=True)`; per-test timeout 300s ceiling.
4. **From `docs/plans/TEMPLATE.md`** — every phase deliverable carries an **Integration Contract** block.
5. **Plan discipline** — every step shows complete code or a complete command. No "fill in details", no "TBD".

---

## 1. Outcome

**User-observable change:** After this plan ships, `python -c "from oneiric.adapters.cache import RedisCacheAdapter, MemoryCacheAdapter"` succeeds with `AttributeError` ruled out; `RedisCacheSettings()` exposes `ttl_seconds` (default 3600) and `stampede_jitter_ms` (default 0); `await adapter.set("k", "v")` honors `ttl_seconds` (passed as `px` ms to coredis); `await adapter.get("k")` honors `stampede_jitter_ms` only on cache miss. Per-call `ttl=-1`/`0` still raises `LifecycleError` (existing behavior preserved).

**Success criteria:**
- `pytest tests/adapters/cache/test_redis_mock.py tests/adapters/test_redis_cache.py tests/unit/test_redis_cache_settings.py -v` is green.
- `python -c "from oneiric.adapters.cache import RedisCacheAdapter, MemoryCacheAdapter"` succeeds.
- `python -c "from oneiric.adapters.cache import RedisCacheSettings; RedisCacheSettings(ttl_seconds=-1)"` raises `ValidationError`.
- `python -c "from oneiric.adapters.cache import RedisCacheSettings; RedisCacheSettings(stampede_jitter_ms=-1)"` raises `ValidationError`.
- Existing tests at `tests/adapters/test_redis_cache.py:181-195` (`test_set_negative_ttl_raises`, `test_set_zero_ttl_raises`) still pass — the consumer code does NOT silently swallow the per-call guard.

## 2. Goals

1. Oneiric PR landed with factory-string fix in `redis.py` and `memory.py`.
2. Oneiric PR landed with `RedisCacheSettings.ttl_seconds` (default 3600, ge=0) and `RedisCacheSettings.stampede_jitter_ms` (default 0, ge=0).
3. **D7 explicit doc-comment** added next to existing `enable_client_cache: bool = Field(default=True, ...)` clarifying the default is intentional per spec D7; **do NOT re-declare the field.**
4. Consumer code in `RedisCacheAdapter.set()` honors `ttl_seconds` (when no per-call kwarg), preserves explicit `LifecycleError` on per-call `ttl <= 0`, and uses `max(1, ms)` sub-ms clamp.
5. Consumer code in `RedisCacheAdapter.get()` honors `stampede_jitter_ms` only on cache miss (returns `None`), no sleep on cache hit, no sleep when `jitter == 0`.
6. Companion tests covering the new fields, factory-string leading-space guards, set/get consumer behavior.
7. Companion Oneiric PR merged direct-to-`main` per Bodai pre-1.0 policy.

## 3. Non-Goals

1. **`dhara.storage.redis_cache` deletion** — that's the Dhara plan's work, not this one.
2. **TrackingCache-degrade-graceful behavior** — dropped from scope (earlier drafts built it against fictional coredis APIs).
3. **MultiTier composition.**
4. **Hot-reload of cache config.**

## 4. Current Findings

| Finding | Evidence |
|---|---|
| Oneiric's `AdapterMetadata.factory` strings have a leading space — `getattr(module, " RedisCacheAdapter")` fails. | `/Users/les/Projects/oneiric/oneiric/adapters/cache/redis.py` and `memory.py`. |
| `RedisCacheSettings` has no TTL / stampede-jitter fields. Dhara's redundant `dhara.storage.redis_cache` had them. | `redis.py:33-90`. |
| `enable_client_cache` already exists at `redis.py:69-72` with default `True` — per spec D7 the default is intentional; do not re-declare. | Verified by inspection. |
| Existing tests `test_set_negative_ttl_raises` and `test_set_zero_ttl_raises` enforce `LifecycleError("redis-cache-negative-ttl")` on per-call `ttl <= 0`. Consumer code MUST preserve this. | `/Users/les/Projects/oneiric/tests/adapters/test_redis_cache.py:181-195`. |
| `__future__ annotations` first line + `import asyncio` already at `redis.py:3`. Only `random` needs adding. | `redis.py:1-15`. |
| Real test file paths: `tests/adapters/test_redis_cache.py`, `tests/adapters/cache/test_redis_mock.py`, `tests/unit/test_redis_cache_settings.py` (NEW). | verified. |
| `asyncio_mode = "auto"` in pyproject.toml — `@pytest.mark.asyncio` decorators are redundant but harmless. | `/Users/les/Projects/oneiric/pyproject.toml`. |

---

## 5. Implementation Phases

This plan has a single phase (Phase 2 of the cross-cutting consolidation, made standalone for clarity and execution independence).

### Phase 2: Oneiric companion changes

**Goal:** Strip leading space from `factory` strings; add two settings fields with consumer code in `set()`/`get()`; companion tests including the regression guard for the existing per-call `ttl <= 0` validation.
**Tasks:** Tasks 2.0–2.3.
**Exit criteria:** Direct merge to `main` on Oneiric; the four Validation-Matrix checks at the bottom pass; existing `test_set_negative_ttl_raises` and `test_set_zero_ttl_raises` tests still pass.

#### Integration Contract

- **Triggered from**: Companion PR merges to `main` on Oneiric. Triggered-by-content: any external consumer constructs `RedisCacheSettings(ttl_seconds=..., stampede_jitter_ms=...)` and calls `await adapter.set(...)` / `await adapter.get(...)`. Triggered-by-behavior: `python -c "from oneiric.adapters.cache import RedisCacheAdapter, MemoryCacheAdapter"` — without the factory-string fix, raises `AttributeError`.
- **Returns to / updates**:
  - `oneiric/adapters/cache/redis.py:RedisCacheSettings`: `+2` fields (`ttl_seconds`, `stampede_jitter_ms`).
  - `oneiric/adapters/cache/redis.py:RedisCacheAdapter.set`: consumer code: applies `self._settings.ttl_seconds` (converted to `px` ms via `max(1, ...)`) when no per-call `ttl` is supplied; preserves `LifecycleError` on per-call `ttl <= 0`.
  - `oneiric/adapters/cache/redis.py:RedisCacheAdapter.get`: consumer code: when `client.get(...)` returns `None` and `self._settings.stampede_jitter_ms > 0`, sleeps `random.uniform(0, jitter_ms) / 1000`; no sleep on a hit; no sleep when `jitter == 0`.
  - `oneiric/adapters/cache/redis.py:RedisCacheSettings`: explicit doc-comment near existing `enable_client_cache` field noting default `True` per spec D7 (NOT a field addition).
  - `oneiric/adapters/cache/redis.py:AdapterMetadata.factory` (line 94): leading space stripped.
  - `oneiric/adapters/cache/memory.py:AdapterMetadata.factory` (line 33): leading space stripped.
- **Demonstrable by**: `cd /Users/les/Projects/oneiric && pytest tests/adapters/cache/test_redis_mock.py tests/adapters/test_redis_cache.py tests/unit/test_redis_cache_settings.py -v` exits 0 with all listed tests PASSED.
- **Rollback signal**: `pytest tests/adapters/cache/test_redis_mock.py` shows a regression on any pre-existing test (especially `test_set_negative_ttl_raises` / `test_set_zero_ttl_raises`); OR `python -c "from oneiric.adapters.cache import RedisCacheSettings; RedisCacheSettings(ttl_seconds=-1)"` does NOT raise `ValidationError`; OR `python -c "from oneiric.adapters.cache import RedisCacheAdapter"` raises `AttributeError`. Roll back via `git -C /Users/les/Projects/oneiric revert <commit>`.
- **Observability added**: No new structured-log emissions. Existing `adapter-init` and `adapter-cleanup-complete` events unchanged. `LifecycleError("redis-cache-negative-ttl")` continues to log via the existing Oneiric lifecycle hook.

#### Task 2.0: Strip leading spaces from `AdapterMetadata.factory` strings

**Files:**
- Modify: `/Users/les/Projects/oneiric/oneiric/adapters/cache/redis.py:94`
- Modify: `/Users/les/Projects/oneiric/oneiric/adapters/cache/memory.py:33`

**Interfaces:**
- Consumes: existing factory strings `"oneiric.adapters.cache.redis: RedisCacheAdapter"` and `"oneiric.adapters.cache.memory: MemoryCacheAdapter"`
- Produces: factory strings with no leading space

- [ ] **Step 1: Locate factory strings**

```bash
grep -n 'factory=' /Users/les/Projects/oneiric/oneiric/adapters/cache/redis.py
grep -n 'factory=' /Users/les/Projects/oneiric/oneiric/adapters/cache/memory.py
```

Expected: `redis.py:94` and `memory.py:33`.

- [ ] **Step 2: Edit `redis.py:94`**

Replace the line:

```python
        factory="oneiric.adapters.cache.redis: RedisCacheAdapter",
```

with:

```python
        factory="oneiric.adapters.cache.redis:RedisCacheAdapter",
```

- [ ] **Step 3: Edit `memory.py:33`**

Replace the line:

```python
        factory="oneiric.adapters.cache.memory: MemoryCacheAdapter",
```

with:

```python
        factory="oneiric.adapters.cache.memory:MemoryCacheAdapter",
```

- [ ] **Step 4: Sanity-check the import path for both classes**

```bash
cd /Users/les/Projects/oneiric && \
  python -c "
import importlib
for mod_name, cls_name in [('oneiric.adapters.cache.redis', 'RedisCacheAdapter'), ('oneiric.adapters.cache.memory', 'MemoryCacheAdapter')]:
    cls = getattr(importlib.import_module(mod_name), cls_name)
    print(f'{cls.__module__}.{cls.__name__}')
"
```

Expected:
```
oneiric.adapters.cache.redis.RedisCacheAdapter
oneiric.adapters.cache.memory.MemoryCacheAdapter
```

If `AttributeError`, the leading space wasn't fully stripped.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/oneiric && \
  git add oneiric/adapters/cache/redis.py oneiric/adapters/cache/memory.py && \
  git commit -m "fix(oneiric): strip leading space from AdapterMetadata.factory strings

The factory strings contained a leading space after the colon
('oneiric.adapters.cache.redis: RedisCacheAdapter'). Any code
calling import_string(factory) would do getattr(module, ' RedisCacheAdapter')
and fail with AttributeError; the only reason this latent bug went
unnoticed is that nothing ever imported via the factory string —
registry-mediated lookups (like Dhara's resolve_cache_adapter, in
its companion plan) would crash immediately.

This fix is a prerequisite for the Dhara cache-adapter consolidation
and lands in the same companion PR."
```

#### Task 2.1: Add `ttl_seconds` and `stampede_jitter_ms` to `RedisCacheSettings`

**Files:**
- Modify: `/Users/les/Projects/oneiric/oneiric/adapters/cache/redis.py` — `RedisCacheSettings` body

**Interfaces:**
- Consumes: existing `RedisCacheSettings` pydantic model; existing `enable_client_cache` field at lines 69-72
- Produces: `ttl_seconds: int` (default 3600, ge=0); `stampede_jitter_ms: int` (default 0, ge=0); explicit D7 doc-comment near `enable_client_cache`

- [ ] **Step 1: Locate the last field and `enable_client_cache`**

```bash
grep -n 'class RedisCacheSettings\|enable_client_cache' /Users/les/Projects/oneiric/oneiric/adapters/cache/redis.py
sed -n '60,95p' /Users/les/Projects/oneiric/oneiric/adapters/cache/redis.py
```

- [ ] **Step 2: Add fields after the last existing field**

Insert immediately after the line that defines `client_cache_max_idle_seconds` (or whichever is currently last among the existing fields):

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
    # NOTE: `enable_client_cache: bool = Field(default=True, ...)` already
    # exists above (around line 69). Per spec D7 its default `True` is
    # intentional; do NOT re-declare this field. Operator-supplied
    # RedisCacheSettings override the default.
```

- [ ] **Step 3: Add `import random` to the imports (unconditional)**

```bash
grep -n '^import\|^from' /Users/les/Projects/oneiric/oneiric/adapters/cache/redis.py | head -10
```

Add `import random` to the stdlib imports block, alphabetically between `inspect` and `from typing...` to respect the project's ruff `force-sort-within-sections = true` config. (`asyncio` is already imported at line 3.) Example placement:

```python
import asyncio
from __future__ import annotations

import inspect
import random
from typing import TYPE_CHECKING, Any
```

- [ ] **Step 4: Round-trip the defaults**

```bash
cd /Users/les/Projects/oneiric && \
  python -c "from oneiric.adapters.cache import RedisCacheSettings; s = RedisCacheSettings(); print(s.ttl_seconds, s.stampede_jitter_ms)"
```

Expected: `3600 0`.

- [ ] **Step 5: Boundary check (both fields allowed at zero, both rejected at -1)**

```bash
cd /Users/les/Projects/oneiric && \
  python -c "
from oneiric.adapters.cache import RedisCacheSettings
from pydantic import ValidationError
print(RedisCacheSettings(ttl_seconds=0, stampede_jitter_ms=999).ttl_seconds, RedisCacheSettings(ttl_seconds=0, stampede_jitter_ms=999).stampede_jitter_ms)
try: RedisCacheSettings(ttl_seconds=-1)
except ValidationError: print('ttl_seconds=-1 rejected')
try: RedisCacheSettings(stampede_jitter_ms=-1)
except ValidationError: print('stampede_jitter_ms=-1 rejected')
"
```

Expected:
```
0 999
ttl_seconds=-1 rejected
stampede_jitter_ms=-1 rejected
```

- [ ] **Step 6: Commit**

```bash
cd /Users/les/Projects/oneiric && \
  git add oneiric/adapters/cache/redis.py && \
  git commit -m "feat(oneiric): extend RedisCacheSettings with ttl_seconds and stampede_jitter_ms

ttl_seconds (default 3600, ge=0): TTL applied at every set() call
when no per-call override is passed; 0 disables.
stampede_jitter_ms (default 0, ge=0): random sleep applied when
get() returns None, dampens thundering-herd on hot keys.

Per spec D7, the existing enable_client_cache default of True is
intentional; this commit adds an explicit NOTE rather than a
re-declaration. Consumer code lands in the next commit of this
companion PR (set/get consumer logic)."
```

#### Task 2.2: Add consumer code in `set()` and `get()`

This task follows strict TDD: write the failing test first (Step 1), confirm it fails (Step 2), implement (Step 3), confirm it passes (Step 4), commit (Step 5).

**Files:**
- Modify: `/Users/les/Projects/oneiric/oneiric/adapters/cache/redis.py` — `RedisCacheAdapter.set()` and `get()` bodies

**Interfaces:**
- Consumes: existing `set(key, value, *, ttl=None)` and `get(key)` method bodies; `self._settings.ttl_seconds`, `self._settings.stampede_jitter_ms`
- Produces:
  - `set()`: applies `self._settings.ttl_seconds` (with `max(1, ms)` sub-ms clamp) when no per-call `ttl` is supplied AND that value is `> 0`; preserves the existing `LifecycleError("redis-cache-negative-ttl")` for per-call `ttl <= 0`.
  - `get()`: sleeps `random.uniform(0, ms) / 1000` when `client.get(...)` returns `None` AND `self._settings.stampede_jitter_ms > 0`; no sleep on hit; no sleep when `jitter == 0`; just `return value` (no fabricated deserialization).

- [ ] **Step 1: Write the failing tests (extend `tests/adapters/cache/test_redis_mock.py`)**

```bash
tail -20 /Users/les/Projects/oneiric/tests/adapters/cache/test_redis_mock.py
```

Inspect the existing test file's import style and fixture conventions. Then append at the bottom:

```python
"""Tests for ttl_seconds / stampede_jitter_ms consumer behavior in set/get."""
# (top-level imports already include `from unittest.mock import AsyncMock, MagicMock, patch`)
import asyncio


@pytest.fixture(autouse=True)
def _stub_coredis_availability(monkeypatch):
    """Permit constructing RedisCacheAdapter without a real coredis install.

    `RedisCacheAdapter.__init__` raises a `LifecycleError` if
    `_COREDIS_AVAILABLE` is `False`. Autouse-stubbing it to True lets
    the mock-only tests below instantiate the adapter safely.
    Mirrors the fixture pattern in `tests/adapters/cache/test_redis_mock.py:64-73`.
    """
    monkeypatch.setattr(
        "oneiric.adapters.cache.redis._COREDIS_AVAILABLE", True, raising=False
    )


def _build_adapter(mock_client: MagicMock, *, ttl: int = 3600, jitter: int = 0) -> RedisCacheAdapter:
    adapter = RedisCacheAdapter(RedisCacheSettings(ttl_seconds=ttl, stampede_jitter_ms=jitter))
    adapter._client = mock_client
    return adapter


@pytest.mark.unit
@pytest.mark.asyncio
async def test_set_applies_default_ttl_seconds_when_no_kwarg_passed() -> None:
    """Confirms the documented default (3600s) flows through to coredis px."""
    mock_client = MagicMock()
    mock_client.set = AsyncMock(return_value=True)
    adapter = _build_adapter(mock_client)  # NO ttl_seconds override; default applies
    await adapter.set("k", "v")
    _, kwargs = mock_client.set.call_args
    assert kwargs.get("px") == 3600 * 1000
    # also: no spurious ttl kwarg leaks to coredis
    assert "ttl" not in kwargs


@pytest.mark.unit
@pytest.mark.asyncio
async def test_set_uses_configured_ttl_seconds_when_no_kwarg_passed() -> None:
    mock_client = MagicMock()
    mock_client.set = AsyncMock(return_value=True)
    adapter = _build_adapter(mock_client, ttl=120, jitter=0)
    await adapter.set("k", "v")
    _, kwargs = mock_client.set.call_args
    assert kwargs.get("px") == max(1, 120 * 1000)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_set_settings_ttl_zero_omits_px() -> None:
    """`settings.ttl_seconds=0` must disable the settings-derived TTL entirely."""
    mock_client = MagicMock()
    mock_client.set = AsyncMock(return_value=True)
    adapter = _build_adapter(mock_client, ttl=0, jitter=0)
    await adapter.set("k", "v")
    _, kwargs = mock_client.set.call_args
    assert "px" not in kwargs


@pytest.mark.unit
@pytest.mark.asyncio
async def test_set_per_call_ttl_overrides_settings_ttl_seconds() -> None:
    """Per-call `ttl` takes precedence over `settings.ttl_seconds`, even with non-zero setting.

    Records the **exact** call signature to detect any spurious `ttl=...`
    kwarg that would otherwise be silently accepted by the mock's
    catch-all `**_` sink.
    """
    mock_client = MagicMock()
    mock_client.set = AsyncMock(return_value=True)
    adapter = _build_adapter(mock_client, ttl=120, jitter=0)
    await adapter.set("k", "v", ttl=5)
    args, kwargs = mock_client.set.call_args
    assert kwargs == {"px": 5000}
    assert "ttl" not in kwargs
    # positional first arg is the namespaced key
    assert args[0] == adapter._namespaced_key("k")
    assert args[1] == "v"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_set_per_call_ttl_negative_raises_lifecycle_error() -> None:
    """Regression guard: existing test_set_negative_ttl_raises asserts LifecycleError on ttl<0.
    The consumer code must NOT silently swallow it when settings.ttl_seconds also happens to be 0."""
    mock_client = MagicMock()
    mock_client.set = AsyncMock(return_value=True)
    adapter = _build_adapter(mock_client, ttl=0, jitter=0)
    with pytest.raises(LifecycleError):
        await adapter.set("k", "v", ttl=-1)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_set_per_call_ttl_zero_raises_lifecycle_error() -> None:
    """Regression guard: existing test_set_zero_ttl_raises asserts LifecycleError on ttl=0."""
    mock_client = MagicMock()
    mock_client.set = AsyncMock(return_value=True)
    adapter = _build_adapter(mock_client, ttl=120, jitter=0)
    with pytest.raises(LifecycleError):
        await adapter.set("k", "v", ttl=0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_applies_stampede_jitter_on_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic: patch BOTH random.uniform and asyncio.sleep; assert exact values.

    Avoids any timing-window flake and proves the consumer code actually
    wired both calls — it would FAIL if either branch were removed.
    """
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=None)
    adapter = _build_adapter(mock_client, jitter=20)
    uniform_mock = MagicMock(return_value=0.015)  # 15 ms in seconds
    sleep_mock = AsyncMock()
    monkeypatch.setattr(
        "oneiric.adapters.cache.redis.random.uniform", uniform_mock, raising=True
    )
    monkeypatch.setattr(
        "oneiric.adapters.cache.redis.asyncio.sleep", sleep_mock, raising=True
    )
    result = await adapter.get("k")
    uniform_mock.assert_called_once_with(0, 20)
    sleep_mock.assert_awaited_once_with(0.015)
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_skips_stampede_jitter_on_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    """On a hit, neither random.uniform nor asyncio.sleep is reached."""
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=b"v")
    adapter = _build_adapter(mock_client, jitter=20)
    uniform_mock = MagicMock()
    sleep_mock = AsyncMock()
    monkeypatch.setattr(
        "oneiric.adapters.cache.redis.random.uniform", uniform_mock, raising=True
    )
    monkeypatch.setattr(
        "oneiric.adapters.cache.redis.asyncio.sleep", sleep_mock, raising=True
    )
    result = await adapter.get("k")
    uniform_mock.assert_not_called()
    sleep_mock.assert_not_awaited()
    assert result == b"v"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_skips_stampede_jitter_when_setting_is_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=None)
    adapter = _build_adapter(mock_client, jitter=0)
    uniform_mock = MagicMock()
    sleep_mock = AsyncMock()
    monkeypatch.setattr(
        "oneiric.adapters.cache.redis.random.uniform", uniform_mock, raising=True
    )
    monkeypatch.setattr(
        "oneiric.adapters.cache.redis.asyncio.sleep", sleep_mock, raising=True
    )
    result = await adapter.get("k")
    uniform_mock.assert_not_called()
    sleep_mock.assert_not_awaited()
    assert result is None
```

- [ ] **Step 2: Run the new tests and confirm the consumer-behavior tests fail**

```bash
cd /Users/les/Projects/oneiric && pytest tests/adapters/cache/test_redis_mock.py -v -k "ttl_seconds or stampede_jitter or per_call_ttl or default_ttl or settings_ttl or overrides_settings or default-construction"
```

Expected: 9 of the 11 new tests FAIL (`test_set_per_call_ttl_*_raises_lifecycle_error` may pass coincidentally because the existing `set()` already raises). The TTL-default, TTL-settings-zero, settings-override, and jitter tests must fail because the consumer code is not yet in place.

If everything passes: the consumer code is *already* in place — unusual but not impossible; investigate.

- [ ] **Step 3: Implement `set()` and `get()` consumer code**

Find `async def get(self, key):` and the existing `value = await client.get(...)` line in `redis.py`. Modify the body to:

```python
    async def get(self, key):
        client = self._ensure_client("redis-client-not-initialized")
        namespaced = self._namespaced_key(key)
        value = await client.get(namespaced)
        if value is None and self._settings.stampede_jitter_ms > 0:
            await asyncio.sleep(
                random.uniform(0, self._settings.stampede_jitter_ms) / 1000.0
            )
        return value
```

Preserve all surrounding namespace construction and error handling. Do NOT add a `json.loads` or `pickle.loads` deserialization step — the existing `get()` returns raw bytes.

Find `async def set(self, key, value, *, ttl=None):` and the existing kwargs construction. Modify to:

```python
    async def set(self, key, value, *, ttl=None) -> None:
        client = self._ensure_client("redis-client-not-initialized")
        if ttl is not None and ttl <= 0:
            raise LifecycleError("redis-cache-negative-ttl")
        effective_ttl = ttl if ttl is not None else self._settings.ttl_seconds
        namespaced = self._namespaced_key(key)
        kwargs: dict[str, Any] = {}
        if effective_ttl and effective_ttl > 0:
            kwargs["px"] = max(1, int(effective_ttl * 1000))
        await client.set(namespaced, value, **kwargs)
```

Notes:
- The explicit `if ttl is not None and ttl <= 0: raise` MUST come before `effective_ttl` is computed; this preserves the existing `LifecycleError("redis-cache-negative-ttl")` for explicit per-call values while allowing `settings.ttl_seconds=0` (a legitimate "no TTL" choice) to silently disable the `px` kwarg.
- `max(1, int(effective_ttl * 1000))` keeps the sub-ms clamp from the existing code (no `px=0` shipments to coredis).

- [ ] **Step 4: Run the new tests and confirm all 7 pass**

```bash
cd /Users/les/Projects/oneiric && pytest tests/adapters/cache/test_redis_mock.py -v -k "ttl_seconds or stampede_jitter or per_call_ttl"
```

Expected: all 7 tests PASSED.

- [ ] **Step 5: Run the full file**

```bash
cd /Users/les/Projects/oneiric && pytest tests/adapters/cache/test_redis_mock.py -v
```

Expected: existing tests PASSED (including `test_set_negative_ttl_raises` and `test_set_zero_ttl_raises`); new tests PASSED. If either of the two `raise` tests now FAILS, the consumer code accidentally dropped the explicit guard.

- [ ] **Step 6: Quick smoke**

```bash
cd /Users/les/Projects/oneiric && \
  python -c "from oneiric.adapters.cache import RedisCacheAdapter, RedisCacheSettings; a = RedisCacheAdapter(RedisCacheSettings(ttl_seconds=120, stampede_jitter_ms=200)); print(a._settings.ttl_seconds, a._settings.stampede_jitter_ms)"
```

Expected: `120 200`. No `AttributeError`.

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/oneiric && \
  git add tests/adapters/cache/test_redis_mock.py oneiric/adapters/cache/redis.py && \
  git commit -m "feat(oneiric): consume ttl_seconds and stampede_jitter_ms in set/get

set() applies self._settings.ttl_seconds (converted via max(1, ms*1000))
when no per-call ttl is supplied; 0 disables. The per-call guard
(ttl <= 0 raises LifecycleError) is preserved verbatim so the
existing test_set_negative_ttl_raises and test_set_zero_ttl_raises
regression guards stay green.

get() sleeps random.uniform(0, jitter_ms / 1000.0) when client.get
returns None; no sleep on hit; no sleep when jitter is 0. Plain
return — no fabricated deserialization.

Tests (in tests/adapters/cache/test_redis_mock.py) mock asyncio.sleep
to assert deterministic await/not-await, eliminating flaky timing
windows."
```

#### Task 2.3: Companion settings tests

**Files:**
- Create: `/Users/les/Projects/oneiric/tests/unit/test_redis_cache_settings.py`

(Yes — this lives at `tests/unit/`, not next to the existing `tests/adapters/...` redis tests. Pydantic-settings unit tests co-locate with `tests/unit/test_adapter_metadata.py` and similar; adapter-interaction tests live next to the adapter. The Two directories serve different concerns.)

**Interfaces:**
- Consumes: `from oneiric.adapters.cache.redis import RedisCacheSettings`; `import_module` for the factory-string guards
- Produces: 8 tests covering the two new fields plus factory-string leading-space guards

- [ ] **Step 1: Create the settings test file**

```python
# /Users/les/Projects/oneiric/tests/unit/test_redis_cache_settings.py
"""Tests for RedisCacheSettings additions + factory-string leading-space guards."""
from __future__ import annotations

from importlib import import_module

import pytest
from pydantic import ValidationError

from oneiric.adapters.cache import RedisCacheSettings


def test_default_ttl_seconds_is_3600() -> None:
    s = RedisCacheSettings()
    assert s.ttl_seconds == 3600


def test_default_stampede_jitter_ms_is_zero() -> None:
    s = RedisCacheSettings()
    assert s.stampede_jitter_ms == 0


def test_ttl_seconds_zero_is_allowed() -> None:
    """Plan-level addition beyond the spec's seven-test list; coverage for `ge=0` lower bound."""
    s = RedisCacheSettings(ttl_seconds=0)
    assert s.ttl_seconds == 0


def test_negative_ttl_seconds_rejected() -> None:
    with pytest.raises(ValidationError):
        RedisCacheSettings(ttl_seconds=-1)


def test_negative_stampede_jitter_ms_rejected() -> None:
    with pytest.raises(ValidationError):
        RedisCacheSettings(stampede_jitter_ms=-1)


def test_factory_string_redis_has_no_leading_space() -> None:
    """Regression guard for D11 (the prerequisite Task 2.0 fix).

    Reads `AdapterMetadata.factory` *raw* and exercises the same
    `getattr(module, attr)` path that Dhara's `resolve_cache_adapter`
    uses via `import_string`. A leading space would make the `getattr`
    raise `AttributeError`.
    """
    from oneiric.adapters.cache.redis import RedisCacheAdapter

    factory = RedisCacheAdapter.metadata.factory
    assert factory == "oneiric.adapters.cache.redis:RedisCacheAdapter", (
        f"factory string has leading/trailing whitespace: {factory!r}"
    )
    module_name, _, attr = factory.partition(":")
    resolved = getattr(import_module(module_name), attr)
    assert resolved is RedisCacheAdapter


def test_factory_string_memory_has_no_leading_space() -> None:
    from oneiric.adapters.cache.memory import MemoryCacheAdapter

    factory = MemoryCacheAdapter.metadata.factory
    assert factory == "oneiric.adapters.cache.memory:MemoryCacheAdapter", (
        f"factory string has leading/trailing whitespace: {factory!r}"
    )
    module_name, _, attr = factory.partition(":")
    resolved = getattr(import_module(module_name), attr)
    assert resolved is MemoryCacheAdapter


def test_existing_fields_round_trip_unchanged() -> None:
    s = RedisCacheSettings(
        url="redis://example:6379/0",
        username="alice",
        password="secret",
        ttl_seconds=120,
        stampede_jitter_ms=10,
    )
    assert s.host == "localhost"
    assert s.password == "secret"
    assert s.ttl_seconds == 120
    assert s.stampede_jitter_ms == 10
```

- [ ] **Step 2: Run the new settings test file**

```bash
cd /Users/les/Projects/oneiric && pytest tests/unit/test_redis_cache_settings.py -v
```

Expected: all 8 tests PASSED.

- [ ] **Step 3: Run the full Oneiric test suite**

```bash
cd /Users/les/Projects/oneiric && pytest tests/ -q
```

Expected: all green.

- [ ] **Step 4: Commit the test additions**

```bash
cd /Users/les/Projects/oneiric && \
  git add tests/unit/test_redis_cache_settings.py && \
  git commit -m "test(oneiric): cover new fields + factory-string + set/get consumer code"
```

#### Direct merge to `main`

- [ ] **Step 1: Verify all four commits are on `main` on Oneiric**

```bash
git -C /Users/les/Projects/oneiric log --oneline main -10 | head -10
```

Expected: the four commits from Tasks 2.0 / 2.1 / 2.2 / 2.3 are at `HEAD` (or near `HEAD` if other work has landed since).

- [ ] **Step 2: Push direct to `main` (no PR)**

```bash
cd /Users/les/Projects/oneiric && git push origin main
```

Expected: push succeeds. Per Bodai pre-1.0 policy, no PR review.

> **Note on the project "branch-then-ff" recipe:** `/.claude/decisions/` references a `branch + squash/ff-merge into main` flow. The user's project policy is direct merge to `main` with no PR. The pre-1.0 carve-out applies here; if a future maintainer prefers branching, the four commits can be cherry-picked onto a `feature/oneiric-cache-factory-and-settings` branch first and then ff-merged with no functional difference.

---

## 6. Required Code Changes

All in `oneiric/`:

- **Modify** `oneiric/adapters/cache/redis.py`:
  - `AdapterMetadata.factory` (line 94) — leading space stripped (Task 2.0)
  - `RedisCacheSettings` — `+2` fields `ttl_seconds`, `stampede_jitter_ms`; explicit NOTE comment near existing `enable_client_cache` clarifying D7 default (Task 2.1)
  - `import random` added to imports (Task 2.1 Step 3)
  - `RedisCacheAdapter.set` — consumer code that applies `ttl_seconds` (with `max(1, ms)` clamp) AND preserves the explicit per-call `ttl <= 0` guard (Task 2.2)
  - `RedisCacheAdapter.get` — consumer code that sleeps on `None` returns when `stampede_jitter_ms > 0`, no fabricated deserialization (Task 2.2)
- **Modify** `oneiric/adapters/cache/memory.py`:
  - `AdapterMetadata.factory` (line 33) — leading space stripped (Task 2.0)
- **Create** `oneiric/tests/unit/test_redis_cache_settings.py` (Task 2.3) — 8 tests
- **Modify** `oneiric/tests/adapters/cache/test_redis_mock.py` — append 7 consumer-behavior tests (Task 2.2 Step 1)

### Files explicitly NOT touched

- `oneiric/adapters/dhara_pusher.py` — already pushes Oneiric → Dhara; works as-is once the factory-string spaces are stripped.
- `oneiric/core/config.py`, `oneiric/core/resolution.py`, `oneiric/core/client_mixins.py` — touched only by the Dhara plan, not this one.
- Anything under `/Users/les/Projects/dhara/` — separate repo; out of scope here.

---

## 7. Validation Matrix

| Command | Expected outcome |
|---|---|
| `grep -n 'factory=' /Users/les/Projects/oneiric/oneiric/adapters/cache/{redis,memory}.py` | No leading space in factory strings (`factory="oneiric.…:X"`, not `": X"`) |
| `python -c "from oneiric.adapters.cache import RedisCacheAdapter, MemoryCacheAdapter; print(RedisCacheAdapter, MemoryCacheAdapter)"` | `<class …RedisCacheAdapter…> <class …MemoryCacheAdapter…>` (no `AttributeError`) |
| `python -c "from oneiric.adapters.cache import RedisCacheSettings; RedisCacheSettings(ttl_seconds=-1)"` | `pydantic.ValidationError` raised |
| `cd /Users/les/Projects/oneiric && pytest tests/adapters/cache/test_redis_mock.py tests/adapters/test_redis_cache.py tests/unit/test_redis_cache_settings.py -v` | All tests PASSED, including `test_set_negative_ttl_raises` and `test_set_zero_ttl_raises` (regression guards) |
| `cd /Users/les/Projects/oneiric && pytest tests/ -q` | All green |
| `git -C /Users/les/Projects/oneiric log --oneline main -5 \| head -5` | Last 4 commits: factory fix, settings fields, set/get consumer, tests |

---

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Step 3 in Task 2.2 places the explicit `raise LifecycleError` AFTER `effective_ttl` is computed (instead of before) and silently passes per-call `ttl=-1` | Low | Task 2.2 Step 3 specifies the exact ordering: explicit guard first, then `effective_ttl`. The two existing tests at `tests/adapters/test_redis_cache.py:181-195` (`test_set_negative_ttl_raises`, `test_set_zero_ttl_raises`) act as regression guards; Task 2.2 Step 5 confirms they pass. |
| `monkeypatch.setattr("oneiric.adapters.cache.redis.asyncio.sleep", ...)` fails because `asyncio` was imported as a module rather than `from asyncio import sleep` | Low | `redis.py` uses `import asyncio` then `asyncio.sleep(...)` (verified in the import block of the file). The full module path string `"oneiric.adapters.cache.redis.asyncio.sleep"` resolves correctly. |
| Test file path `tests/unit/test_redis_cache_settings.py` collides with hidden tests already there | Very Low | Listing `tests/unit/` shows no `test_redis_cache*` file other than this one. If a collision exists, the new file's 8 tests will surface a `collection error` immediately. |
| Factory-string fix is breaking in some other consumers I missed (e.g. a CLI that does a manual lookup) | Low | `grep -rn 'oneiric.adapters.cache' /Users/les/Projects/oneiric/ --include='*.py'` shows no manual factory-string lookup besides the registry-mediated path. No other consumer. |

---

## 9. Decision Rule

Done when Phase 2 commits (Tasks 2.0 / 2.1 / 2.2 / 2.3) are on `main` of `/Users/les/Projects/oneiric`, the four Validation-Matrix smoke checks at the bottom pass, and `pytest tests/adapters/cache/test_redis_mock.py` is green including the existing `test_set_negative_ttl_raises` and `test_set_zero_ttl_raises` regression guards.

**Cut order** (when scope pressure forces a cut — not expected here):
1. **Last to cut:** Task 2.1 settings-field additions — they are the *contract surface*. Removing them invalidates Task 2.2 consumer code and breaks Dhara's downstream migration.
2. **Cut second:** Task 2.0 factory-string fix — deferable to a follow-up companion-PR since it doesn't block Dhara-side correctness (only registry-mediated lookup paths). However, dropping it means Dhara's `resolve_cache_adapter` will hard-crash via `AttributeError` at first run, so leaving it in is strongly preferred.
3. **Cut third:** Task 2.2 `get()` stampede-jitter consumer code — Dhara loses stampede-herd protection on cache misses but the rest still works.
4. **Cut first:** Task 2.2 `set()` ttl_seconds consumer code — the regression guard `test_set_per_call_ttl_negative_raises_lifecycle_error` exercises the existing branch, so behaviour remains correct at per-call time.

---

## References

- Cross-cutting spec: `/Users/les/Projects/dhara/docs/superpowers/specs/2026-07-15-dhara-cache-adapter-oneiric-consolidation-design.md`
- Companion plan (Dhara side, blocked on async-migration): `/Users/les/Projects/dhara/docs/superpowers/plans/2026-07-15-dhara-cache-adapter-oneiric-consolidation-plan.md`
- Plan template: `/Users/les/Projects/mahavishnu/docs/plans/TEMPLATE.md`
- Project policy: `/Users/les/Projects/mahavishnu/.claude/decisions/wire-up-contract.md`
