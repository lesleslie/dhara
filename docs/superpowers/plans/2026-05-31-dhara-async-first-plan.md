# Dhara Async-First Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Dhara's sync `Connection` + `Storage` with fully async `AsyncConnection` + `AsyncStorage`. Eliminate `FileStorage` entirely. No sync backends, no legacy support.

**Architecture:** New `AsyncStorage` protocol with same OID/object-graph semantics as `Storage` but async I/O. New `AsyncConnection` wraps `AsyncStorage` and exposes async versions of all persistence operations. All collections (`PersistentDict`, `PersistentList`, `BTree`) get async variants. All Bodai components updating to use async APIs.

**Tech Stack:** Python 3.13+, aiosqlite, asyncpg, asyncio

---

## Scope: Files to Modify or Create

### Dhara Core (`/Users/les/Projects/dhara/`)

| File | Action | Purpose |
|------|--------|---------|
| `dhara/storage/base.py` | Modify | Add `AsyncStorage` protocol alongside `Storage` |
| `dhara/storage/postgres.py` | Create | Async Postgres adapter using asyncpg |
| `dhara/storage/sqlite.py` | Create | Async SQLite adapter using aiosqlite |
| `dhara/storage/memory.py` | Modify | Add `AsyncMemoryStorage` (async variant) |
| `dhara/storage/file.py` | Delete | **REMOVE** — FileStorage is obsoleted |
| `dhara/core/connection.py` | Modify | Add `AsyncConnection` class |
| `dhara/core/persistent.py` | Modify | Add async persistence methods |
| `dhara/collections/dict.py` | Modify | Add `AsyncPersistentDict` |
| `dhara/collections/list.py` | Modify | Add `AsyncPersistentList` |
| `dhara/collections/btree.py` | Modify | Add async BTree methods |
| `dhara/mcp/kv_timeseries.py` | Modify | Use `AsyncConnection` internally |
| `dhara/mcp/server_core.py` | Modify | Use `AsyncConnection` |
| `dhara/mcp/adapter_tools.py` | Modify | Use `AsyncConnection` |
| `dhara/backup/catalog.py` | Modify | Use `AsyncConnection` |
| `dhara/backup/restore.py` | Modify | Use `AsyncConnection` |
| `dhara/__init__.py` | Modify | Export `AsyncConnection`, remove `FileStorage` |
| `dhara/cli.py` | Modify | Use async APIs |
| `dhara/__main__.py` | Modify | Use async entry point |
| `bin/db_renumber.py` | Modify | Use `AsyncConnection` |
| `bin/db_to_py3k.py` | Modify | Use `AsyncConnection` |
| `tests/conftest.py` | Modify | Use `AsyncSqliteStorage` not `FileStorage` |
| `tests/test_core_connection_methods.py` | Modify | Async tests |
| `tests/test_mcp_kv_timeseries.py` | Modify | Async tests |
| `tests/test_mcp_server_core.py` | Modify | Async tests |

### Crackerjack (`/Users/les/Projects/crackerjack/`)

| File | Action | Purpose |
|------|--------|---------|
| `crackerjack/integration/dhara_integration.py` | Modify | `DharaAdapterLearner` use `AsyncConnection` + `AsyncSqliteStorage` |
| `tests/unit/agents/test_import_optimization_agent.py` | Modify | Update dhara imports |
| `tests/unit/agents/test_planning_agent_fixes.py` | Modify | Update dhara imports |

### Session-Buddy, Mahavishnu, Akosha

**No changes needed** — they don't use Dhara `Connection` directly. They communicate via HTTP to Dhara MCP server, which will use `AsyncConnection` internally.

---

## Task Map

### Phase 1: AsyncStorage Protocol + Async Backends

- [ ] **Task 1:** Add `AsyncStorage` protocol to `dhara/storage/base.py`
- [ ] **Task 2:** Create `AsyncSqliteStorage` in `dhara/storage/sqlite.py` using aiosqlite
- [ ] **Task 3:** Create `AsyncPostgresStorage` in `dhara/storage/postgres.py` using asyncpg
- [ ] **Task 4:** Add `AsyncMemoryStorage` in `dhara/storage/memory.py`
- [ ] **Task 5:** Delete `dhara/storage/file.py` (FileStorage removed)
- [ ] **Task 6:** Update `dhara/__init__.py` exports (remove `FileStorage`)

### Phase 2: AsyncConnection

- [ ] **Task 7:** Add `AsyncConnection` class in `dhara/core/connection.py`
- [ ] **Task 8:** Add async methods to `PersistentObject` in `dhara/core/persistent.py`
- [ ] **Task 9:** Add `AsyncPersistentDict` in `dhara/collections/dict.py`
- [ ] **Task 10:** Add `AsyncPersistentList` in `dhara/collections/list.py`
- [ ] **Task 11:** Add async methods to `BTree` in `dhara/collections/btree.py`

### Phase 3: MCP Server Async

- [ ] **Task 12:** Update `dhara/mcp/kv_timeseries.py` to use `AsyncConnection`
- [ ] **Task 13:** Update `dhara/mcp/server_core.py` to use `AsyncConnection`
- [ ] **Task 14:** Update `dhara/mcp/adapter_tools.py` to use `AsyncConnection`

### Phase 4: Backup/CLI/Bin Async

- [ ] **Task 15:** Update `dhara/backup/catalog.py` to use `AsyncConnection`
- [ ] **Task 16:** Update `dhara/backup/restore.py` to use `AsyncConnection`
- [ ] **Task 17:** Update `dhara/cli.py` to use async entry point
- [ ] **Task 18:** Update `dhara/__main__.py` for async
- [ ] **Task 19:** Update `bin/db_renumber.py` to use `AsyncConnection`
- [ ] **Task 20:** Update `bin/db_to_py3k.py` to use `AsyncConnection`

### Phase 5: Tests

- [ ] **Task 21:** Update `tests/conftest.py` — use `AsyncSqliteStorage`
- [ ] **Task 22:** Update `tests/test_core_connection_methods.py` — async tests
- [ ] **Task 23:** Update `tests/test_mcp_kv_timeseries.py` — async tests
- [ ] **Task 24:** Update `tests/test_mcp_server_core.py` — async tests

### Phase 6: Crackerjack Integration

- [ ] **Task 25:** Update `crackerjack/integration/dhara_integration.py` — `DharaAdapterLearner` async
- [ ] **Task 26:** Update test files in `crackerjack/tests/unit/agents/`

---

## Detailed Tasks

### Task 1: Add AsyncStorage Protocol

**Files:**
- Modify: `dhara/storage/base.py`

- [ ] **Step 1: Add AsyncStorage protocol**

```python
# In dhara/storage/base.py, add after the Storage protocol:

class AsyncStorage(Protocol):
    """Async storage protocol — OID-based object storage with async I/O."""

    async def load(self, oid: OID) -> bytes: ...
    async def begin(self) -> None: ...
    async def store(self, oid: OID, record: bytes) -> None: ...
    async def end(self, handle_invalidations: Any | None = None) -> None: ...
    async def sync(self) -> list[OID]: ...
    async def new_oid(self) -> OID: ...
    async def gen_oid_record(
        self, start_oid: OID | None = None, batch_size: int = 100
    ) -> AsyncIterator[tuple[OID, bytes]]: ...
    async def pack(self) -> None: ...
    async def health(self) -> bool: ...
    async def cleanup(self) -> None: ...
```

- [ ] **Step 2: Add marker for async storage**

```python
# Add at bottom of dhara/storage/base.py:
SupportsAsync = typing.TypeVar("SupportsAsync", bound=AsyncStorage)
```

- [ ] **Step 3: Commit**

```bash
git add dhara/storage/base.py
git commit -m "feat: add AsyncStorage protocol for async OID-based storage"
```

---

### Task 2: Create AsyncSqliteStorage

**Files:**
- Create: `dhara/storage/sqlite.py`
- Modify: `dhara/__init__.py`

- [ ] **Step 1: Write failing test**

```python
# tests/storage/test_sqlite.py
import pytest
from dhara.storage.sqlite import AsyncSqliteStorage

@pytest.mark.asyncio
async def test_async_sqlite_storage_load_store():
    storage = AsyncSqliteStorage(":memory:")
    await storage.init()
    oid = await storage.new_oid()
    await storage.begin()
    await storage.store(oid, b"test record data")
    await storage.end()
    result = await storage.load(oid)
    assert result == b"test record data"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/storage/test_sqlite.py::test_async_sqlite_storage_load_store -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write minimal AsyncSqliteStorage**

```python
# dhara/storage/sqlite.py
from __future__ import annotations

import aiosqlite
from typing import TYPE_CHECKING, AsyncIterator, Protocol

if TYPE_CHECKING:
    from dhara.core.oid import OID

class AsyncSqliteStorage:
    """Async SQLite storage using aiosqlite."""

    def __init__(self, path: str, readonly: bool = False):
        self._path = path
        self._readonly = readonly
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute(
            "CREATE TABLE IF NOT EXISTS dhara_oid ("
            "oid TEXT PRIMARY KEY, record BLOB)"
        )

    async def load(self, oid: OID) -> bytes:
        assert self._conn is not None
        async with self._conn.execute(
            "SELECT record FROM dhara_oid WHERE oid = ?", (str(oid),)
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                raise KeyError(oid)
            return bytes(row[0])

    async def begin(self) -> None: ...
    async def store(self, oid: OID, record: bytes) -> None: ...
    async def end(self, handle_invalidations=None) -> None: ...
    async def sync(self) -> list[OID]: ...
    async def new_oid(self) -> OID: ...
    async def gen_oid_record(self, start_oid=None, batch_size=100) -> AsyncIterator: ...
    async def pack(self) -> None: ...
    async def health(self) -> bool: ...
    async def cleanup(self) -> None: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/storage/test_sqlite.py::test_async_sqlite_storage_load_store -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/storage/sqlite.py dhara/__init__.py
git commit -m "feat: add AsyncSqliteStorage using aiosqlite"
```

---

### Task 3: Create AsyncPostgresStorage

**Files:**
- Create: `dhara/storage/postgres.py`

- [ ] **Step 1: Write failing test**

```python
# tests/storage/test_postgres.py
import pytest
from dhara.storage.postgres import AsyncPostgresStorage

@pytest.mark.asyncio
async def test_async_postgres_storage_load_store():
    storage = AsyncPostgresStorage("postgresql://localhost/testdb")
    await storage.init()
    oid = await storage.new_oid()
    await storage.begin()
    await storage.store(oid, b"test record data")
    await storage.end()
    result = await storage.load(oid)
    assert result == b"test record data"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/storage/test_postgres.py::test_async_postgres_storage_load_store -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write AsyncPostgresStorage**

```python
# dhara/storage/postgres.py
from __future__ import annotations

import asyncpg
from typing import TYPE_CHECKING, AsyncIterator, Protocol

if TYPE_CHECKING:
    from dhara.core.oid import OID

class AsyncPostgresStorage:
    """Async Postgres storage using asyncpg."""

    def __init__(
        self,
        dsn: str,
        min_size: int = 5,
        max_size: int = 20,
    ):
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: asyncpg.Pool | None = None

    async def init(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
        )
        async with self._pool.acquire() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS dhara_oid ("
                "oid TEXT PRIMARY KEY, record BYTEA)"
            )

    async def load(self, oid: OID) -> bytes:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT record FROM dhara_oid WHERE oid = $1", str(oid)
            )
            if row is None:
                raise KeyError(oid)
            return bytes(row["record"])

    async def begin(self) -> None: ...
    async def store(self, oid: OID, record: bytes) -> None: ...
    async def end(self, handle_invalidations=None) -> None: ...
    async def sync(self) -> list[OID]: ...
    async def new_oid(self) -> OID: ...
    async def gen_oid_record(self, start_oid=None, batch_size=100) -> AsyncIterator: ...
    async def pack(self) -> None: ...
    async def health(self) -> bool: ...
    async def cleanup(self) -> None: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/storage/test_postgres.py::test_async_postgres_storage_load_store -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/storage/postgres.py
git commit -m "feat: add AsyncPostgresStorage using asyncpg"
```

---

### Task 4: Add AsyncMemoryStorage

**Files:**
- Modify: `dhara/storage/memory.py`

- [ ] **Step 1: Add async methods to MemoryStorage**

Add async versions of all sync methods to `MemoryStorage` class.

- [ ] **Step 2: Write failing test**

```python
# tests/storage/test_memory.py
import pytest
from dhara.storage.memory import MemoryStorage

@pytest.mark.asyncio
async def test_async_memory_storage():
    storage = MemoryStorage()
    await storage.init() # MemoryStorage needs init for async compat
    oid = await storage.new_oid()
    await storage.begin()
    await storage.store(oid, b"test")
    await storage.end()
    result = await storage.load(oid)
    assert result == b"test"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/storage/test_memory.py::test_async_memory_storage -v`
Expected: FAIL — async methods not defined

- [ ] **Step 4: Implement async methods on MemoryStorage**

Add `async def load`, `async def begin`, `async def store`, `async def end`, `async def sync`, `async def new_oid`, `async def gen_oid_record`, `async def pack`, `async def health`, `async def cleanup` — all wrapping the sync versions with `asyncio.get_event_loop().run_in_executor()` or similar.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/storage/test_memory.py::test_async_memory_storage -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add dhara/storage/memory.py
git commit -m "feat: add async methods to MemoryStorage"
```

---

### Task 5: Delete FileStorage

**Files:**
- Delete: `dhara/storage/file.py`
- Remove from exports in `dhara/__init__.py`

- [ ] **Step 1: Verify no internal usages remain**

```bash
grep -r "FileStorage" dhara/ --include="*.py" | grep -v "__pycache__"
```

- [ ] **Step 2: Delete file**

```bash
rm dhara/storage/file.py
```

- [ ] **Step 3: Update exports in dhara/__init__.py**

Remove `FileStorage` from exports.

- [ ] **Step 4: Commit**

```bash
git rm dhara/storage/file.py
git add dhara/__init__.py
git commit -m "feat: remove FileStorage — async storage only"
```

---

### Task 6: Update Dhara Exports

**Files:**
- Modify: `dhara/__init__.py`

- [ ] **Step 1: Update exports**

```python
# Remove: FileStorage
# Add: AsyncConnection, AsyncSqliteStorage, AsyncPostgresStorage, AsyncMemoryStorage
from dhara.core.connection import AsyncConnection
from dhara.storage.sqlite import AsyncSqliteStorage
from dhara.storage.postgres import AsyncPostgresStorage
from dhara.storage.memory import AsyncMemoryStorage
```

- [ ] **Step 2: Commit**

```bash
git add dhara/__init__.py
git commit -m "feat: update exports — async storage only, no FileStorage"
```

---

### Task 7: Add AsyncConnection Class

**Files:**
- Modify: `dhara/core/connection.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_async_connection.py
import pytest
from dhara.storage.memory import MemoryStorage
from dhara.core.connection import AsyncConnection

@pytest.mark.asyncio
async def test_async_connection_get_set():
    storage = MemoryStorage()
    await storage.init()
    conn = AsyncConnection(storage)
    root = await conn.get_root()
    await root.set("key", "value")
    await conn.commit()
    loaded = await conn.get(root._p_oid)
    assert loaded is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_async_connection.py::test_async_connection_get_set -v`
Expected: FAIL — AsyncConnection not defined

- [ ] **Step 3: Write AsyncConnection**

```python
# In dhara/core/connection.py, add after Connection class:

class AsyncConnection:
    """Fully async Connection — all storage operations are awaited."""

    def __init__(self, storage: AsyncStorage, cache_size: int = 100000, root_class=None, cache=None):
        if isinstance(storage, str):
            raise TypeError("AsyncConnection requires an AsyncStorage instance, not a path string")
        assert isinstance(storage, AsyncStorage)
        self.storage = storage
        self.reader = ObjectReader(self)
        self.changed = {}
        self.invalid_oids = set()
        self.new_oid = storage.new_oid
        self.cache = cache if cache is not None else Cache(cache_size)
        self.root = await self.get(ROOT_OID)
        if self.root is None:
            new_oid = await self.new_oid()
            assert ROOT_OID == new_oid
            from dhara.collections.dict import PersistentDict
            self.root = self.get_cache().get_instance(
                ROOT_OID, root_class or PersistentDict, self
            )
            self.root._p_set_status_saved()
            self.root.__class__.__init__(self.root)
            self.root._p_note_change()
            await self.commit()
        assert root_class in (None, self.root.__class__)

    async def get(self, oid):
        """Async get — returns PersistentObject."""
        if not isinstance(oid, byte_string):
            oid = int8_to_str(oid)
        obj = self.cache.get(oid)
        if obj is not None:
            return obj
        try:
            data = await self.get_stored_pickle(oid)
        except KeyError:
            return None
        klass = loads(data)
        obj = self.cache.get_instance(oid, klass, self)
        state = self.reader.get_state(data, load=True)
        obj.__setstate__(state)
        obj._p_set_status_saved()
        return obj

    async def get_stored_pickle(self, oid):
        """Async pickle retrieval."""
        assert oid not in self.invalid_oids, "still conflicted: missing abort()"
        try:
            record = await self.storage.load(oid)
        except ReadConflictError:
            invalid_oids = await self.storage.sync()
            self._handle_invalidations(invalid_oids, read_oid=oid)
            record = await self.storage.load(oid)
        oid2, data, refdata = unpack_record(record)
        assert as_bytes(oid) == oid2, (oid, oid2)
        return data

    async def commit(self):
        """Async commit — store all changed objects."""
        if not self.changed:
            await self._sync()
        else:
            assert not self.invalid_oids, "still conflicted: missing abort()"
            await self.storage.begin()
            new_objects = {}
            for oid, changed_object in iteritems(self.changed):
                writer = ObjectWriter(self)
                try:
                    for obj in writer.gen_new_objects(changed_object):
                        oid = obj._p_oid
                        if oid in new_objects:
                            continue
                        elif oid not in self.changed:
                            new_objects[oid] = obj
                            self.cache[oid] = obj
                        data, refs = writer.get_state(obj)
                        await self.storage.store(oid, pack_record(oid, data, refs))
                        obj._p_set_status_saved()
                finally:
                    writer.close()
            try:
                await self.storage.end(self._handle_invalidations)
            except ConflictError:
                for oid, obj in iteritems(new_objects):
                    obj._p_oid = None
                    del self.cache[oid]
                    obj._p_set_status_unsaved()
                    obj._p_connection = None
                raise
            self.changed.clear()
        self.shrink_cache()
        self.transaction_serial += 1

    async def abort(self):
        """Async abort."""
        for oid, obj in iteritems(self.changed):
            obj._p_set_status_ghost()
        self.changed.clear()
        await self._sync()
        self.shrink_cache()
        self.transaction_serial += 1

    async def _sync(self):
        """Async sync."""
        invalid_oids = await self.storage.sync()
        self.invalid_oids.update(invalid_oids)
        for oid in self.invalid_oids:
            obj = self.cache.get(oid)
            if obj is not None:
                obj._p_set_status_ghost()
        self.invalid_oids.clear()

    async def new_oid(self) -> OID:
        return await self.storage.new_oid()

    # ... all other sync methods converted to async ...
```

- [ ] **Step 3: Run test to verify it passes**

Run: `pytest tests/test_async_connection.py::test_async_connection_get_set -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add dhara/core/connection.py
git commit -m "feat: add AsyncConnection — fully async OID persistence"
```

---

### Task 8: Add Async PersistentObject Methods

**Files:**
- Modify: `dhara/core/persistent.py`

- [ ] **Step 1: Add async methods to PersistentObject**

Add `_p_get_async()`, `_p_set_async()`, `_p_commit_async()`, `_p_abort_async()` etc.

- [ ] **Step 2: Write failing test**

```python
@pytest.mark.asyncio
async def test_async_persistent_object_set():
    storage = MemoryStorage()
    await storage.init()
    conn = AsyncConnection(storage)
    root = await conn.get_root()
    await root.set("key", "value")
    await conn.commit()
```

- [ ] **Step 3: Implement async methods**

- [ ] **Step 4: Commit**

---

### Tasks 9-26: Follow same pattern

Each task follows TDD: write failing test → implement minimal code → verify pass → commit.

---

## Dependency Order

```
Task 1 (AsyncStorage protocol)
 └─ Task 2 (AsyncSqliteStorage)
  └─ Task 3 (AsyncPostgresStorage)
  └─ Task 4 (AsyncMemoryStorage)
  └─ Task 5 (Delete FileStorage)
  └─ Task 6 (Update exports)
        └─ Task 7 (AsyncConnection)
              └─ Task 8 (Async PersistentObject)
 └─ Tasks 9-11 (Async collections)
                          └─ Tasks 12-14 (MCP async)
                                └─ Tasks 15-20 (Backup/CLI/Bin async)
                                      └─ Tasks 21-24 (Tests)
 └─ Tasks 25-26 (Crackerjack)
```

---

## No Migration Path

This is a breaking change. The old sync `Connection` and `Storage` are removed entirely. No compatibility layer, no gradual migration.

- Old code using `Connection(Storage(...))` breaks — must use `AsyncConnection(AsyncStorage(...))`
- Old code using `FileStorage` breaks — must use `AsyncSqliteStorage` or `AsyncPostgresStorage`
- All `await conn.commit()` instead of `conn.commit()`
- All `await conn.get(oid)` instead of `conn.get(oid)`
