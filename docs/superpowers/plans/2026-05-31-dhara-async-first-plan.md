# Dhara Async-First Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Dhara's sync `Connection` + `Storage` with fully async `AsyncConnection` + `AsyncStorage`. Eliminate `FileStorage` entirely. No sync backends, no legacy support.

**Architecture:** New `AsyncStorage` protocol with same OID/object-graph semantics as `Storage` but async I/O. New `AsyncConnection` wraps `AsyncStorage` and exposes async versions of all persistence operations. Collections (`PersistentDict`, `PersistentList`) get async variants. Crackerjack's `DharaAdapterLearner` becomes an MCP client (Option B — see Task 25).

**Tech Stack:** Python 3.13+, aiosqlite, asyncpg, asyncio, pytest-asyncio

---

## Scope: Files to Modify or Create

### Dhara Core (`/Users/les/Projects/dhara/`)

| File | Action | Purpose |
|------|--------|---------|
| `dhara/storage/base.py` | Modify | Add `AsyncStorage` protocol (complete — all methods) |
| `dhara/storage/postgres.py` | Create | Async Postgres adapter using asyncpg |
| `dhara/storage/sqlite.py` | Create | Async SQLite adapter using aiosqlite |
| `dhara/storage/memory.py` | Modify | Add `AsyncMemoryStorage` (native async, no executor) |
| `dhara/storage/file.py` | Delete | **REMOVE** — FileStorage obsoleted |
| `dhara/core/connection.py` | Modify | Add `AsyncConnection` (all methods explicit) |
| `dhara/core/persistent.py` | Modify | Add async persistence methods |
| `dhara/collections/dict.py` | Modify | Add `AsyncPersistentDict` |
| `dhara/collections/list.py` | Modify | Add `AsyncPersistentList` |
| `dhara/collections/btree.py` | Modify | BTree stays in-memory sync; async wrapper for async storage compat |
| `dhara/mcp/kv_timeseries.py` | Modify | Use `AsyncConnection` internally |
| `dhara/mcp/server_core.py` | Modify | Use `AsyncConnection` |
| `dhara/mcp/adapter_tools.py` | Modify | Use `AsyncConnection` |
| `dhara/backup/catalog.py` | Modify | Use `AsyncConnection` |
| `dhara/backup/restore.py` | Modify | Use `AsyncConnection` |
| `dhara/__init__.py` | Modify | Export `AsyncConnection`, remove `FileStorage` |
| `dhara/cli.py` | Modify | Use async entry point |
| `dhara/__main__.py` | Modify | Use async entry point |
| `bin/db_renumber.py` | Modify | Use `AsyncConnection` |
| `bin/db_to_py3k.py` | Modify | Use `AsyncConnection` |
| `tests/conftest.py` | Modify | Remove deprecated `event_loop` fixture; use `AsyncSqliteStorage` |
| `tests/storage/` | Create | New test directory for storage backends |
| `tests/test_async_connection.py` | Create | AsyncConnection tests |
| `tests/test_core_connection_methods.py` | Modify | Async tests |
| `tests/test_mcp_kv_timeseries.py` | Modify | Async tests |
| `tests/test_mcp_server_core.py` | Modify | Async tests |

### Crackerjack (`/Users/les/Projects/crackerjack/`)

| File | Action | Purpose |
|------|--------|---------|
| `crackerjack/integration/dhara_integration.py` | Modify | `DharaAdapterLearner` uses HTTP/MCP client (Option B) |
| `tests/unit/agents/test_import_optimization_agent.py` | Modify | Update dhara imports |
| `tests/unit/agents/test_planning_agent_fixes.py` | Modify | Update dhara imports |

### Session-Buddy, Mahavishnu, Akosha

**No changes needed** — they communicate with Dhara via HTTP/MCP. Dhara's MCP server (Tasks 12-14) becomes async internally, which is transparent to HTTP clients.

---

## Critical Review Findings Applied

The plan was reviewed by three agents (architecture, API design, Python quality). Key fixes applied:

1. **AsyncStorage protocol is complete** — includes `close()`, `init()`, `bulk_load()`, `get_packer()` (previously missing)
2. **Task ordering fixed** — Task 15 (catalog.py update) runs BEFORE Task 5 (FileStorage deletion)
3. **AsyncMemoryStorage uses native coroutines** — not `run_in_executor()` wrappers
4. **AsyncConnection lists all methods explicitly** — no `...` hand-wave
5. **BTree clarification** — BTree is pure in-memory; async wrapper for async storage compatibility only
6. **Task25 uses Option B (MCP client)** — `DharaAdapterLearner` becomes an MCP client like Akosha/Mahavishnu
7. **pytest-asyncio dependency added** — all async tests use `pytest.mark.asyncio`
8. **conftest.py fixture conflict resolved** — remove deprecated `event_loop` fixture
9. **Missing AsyncConnection methods added** — `get_crawler`, `load_state`, `get_storage`, `get_load_count`, `note_access`, `note_change`, `pack`, `touch_every_reference`, `gen_every_instance`
10. **gen_oid_record async generator** — non-trivial; gets its own implementation detail
11. **AsyncConnection factory pattern** — `__init__` cannot be async; use `async def new()` classmethod instead
12. **shrink_cache() awaits fixed** — `abort()` and `commit()` now properly `await self.shrink_cache()`
13. **cache.clear() fix** — Cache has no `clear()` method; uses `clear_dead()` from ObjectDictionary instead
14. **new_oid shadowing fixed** — AsyncConnection no longer sets `self.new_oid` instance attribute
15. **Protocol test uses inspect.iscoroutinefunction** — verifies methods are truly async, not just named
16. **Task 15 test redesigned** — `BackupCatalog` takes `backup_dir: str | Path`, not a storage object
17. **Dependency edges added** — Task 7 depends on Task 1; Tasks 9-11 depend on Task 7
18. **BTree test coverage expanded** — now tests `delete`, `items`, `keys`, `values`, `update`

---

## Task Map

### Phase 1: AsyncStorage Protocol + Async Backends

- [ ] **Task 1:** Add complete `AsyncStorage` protocol to `dhara/storage/base.py`
- [ ] **Task 2:** Create `AsyncSqliteStorage` in `dhara/storage/sqlite.py` using aiosqlite
- [ ] **Task 3:** Create `AsyncPostgresStorage` in `dhara/storage/postgres.py` using asyncpg
- [ ] **Task 4:** Add `AsyncMemoryStorage` in `dhara/storage/memory.py` (native async)
- [ ] **Task 6:** Update `dhara/__init__.py` exports (remove `FileStorage`)
- [ ] **Task 5:** Delete `dhara/storage/file.py` (FileStorage removed) — **runs after Task 6**

### Phase 2: AsyncConnection

- [ ] **Task 7:** Add `AsyncConnection` class in `dhara/core/connection.py` (all methods explicit)
- [ ] **Task 8:** Add async methods to `PersistentObject` in `dhara/core/persistent.py`
- [ ] **Task 9:** Add `AsyncPersistentDict` in `dhara/collections/dict.py`
- [ ] **Task 10:** Add `AsyncPersistentList` in `dhara/collections/list.py`
- [ ] **Task 11:** Add async wrapper for `BTree` in `dhara/collections/btree.py`

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

- [ ] **Task 21:** Update `tests/conftest.py` — remove deprecated `event_loop` fixture, use `AsyncSqliteStorage`
- [ ] **Task 22:** Update `tests/test_core_connection_methods.py` — async tests
- [ ] **Task 23:** Update `tests/test_mcp_kv_timeseries.py` — async tests
- [ ] **Task 24:** Update `tests/test_mcp_server_core.py` — async tests

### Phase 6: Crackerjack Integration (Option B — MCP Client)

- [ ] **Task 25:** Update `crackerjack/integration/dhara_integration.py` — `DharaAdapterLearner` uses HTTP/MCP client
- [ ] **Task 26:** Update test files in `crackerjack/tests/unit/agents/`

---

## Detailed Tasks

### Task 1: Add Complete AsyncStorage Protocol

**Files:**
- Modify: `dhara/storage/base.py`

- [ ] **Step 1: Write failing test for protocol**

```python
# tests/storage/test_async_storage_protocol.py
import pytest
import inspect
from typing import AsyncIterator
from dhara.storage.base import AsyncStorage

@pytest.mark.asyncio
async def test_async_storage_protocol_interface():
    """Verify AsyncStorage has all required methods and they are async coroutines."""
    methods = [
        'init', 'load', 'begin', 'store', 'end', 'sync',
        'new_oid', 'gen_oid_record', 'pack', 'health',
        'cleanup', 'close', 'bulk_load'
    ]
    for method in methods:
        assert hasattr(AsyncStorage, method), f"AsyncStorage missing {method}"
        attr = getattr(AsyncStorage, method)
        assert inspect.iscoroutinefunction(attr), f"{method} is not async (is {type(attr).__name__})"

@pytest.mark.asyncio
async def test_async_storage_protocol_gen_oid_record_is_async_iterator():
    """Verify gen_oid_record returns an AsyncIterator."""
    # Create a minimal mock implementing the protocol
    class MockStorage:
        async def init(self): pass
        async def load(self, oid): pass
        async def begin(self): pass
        async def store(self, oid, record): pass
        async def end(self, handle_invalidations=None): pass
        async def sync(self): return []
        async def new_oid(self): return b'\x00\x00\x00\x00\x00\x00\x00\x01'
        async def gen_oid_record(self, start_oid=None, batch_size=100):
            return  # empty async generator
        async def bulk_load(self, oids):
            return  # empty async generator
        async def pack(self): pass
        async def health(self): return True
        async def cleanup(self): pass
        async def close(self): pass
        def get_packer(self): return None

    storage = MockStorage()
    result = storage.gen_oid_record()
    # Verify it's an async generator
    assert inspect.isasyncgen(result), "gen_oid_record must return an async generator"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/storage/test_async_storage_protocol.py -v`
Expected: FAIL — AsyncStorage not defined

- [ ] **Step 3: Write complete AsyncStorage protocol**

```python
# In dhara/storage/base.py, add after the Storage protocol:

class AsyncStorage(Protocol):
    """Async storage protocol — OID-based object storage with async I/O.

    All methods are async coroutines. The protocol mirrors Storage but
    with async I/O for serverless-compatible deployment.
    """

    async def init(self) -> None:
        """Initialize the storage (async constructor)."""
        ...

    async def load(self, oid: OID) -> bytes:
        """Load record for oid. Raises KeyError if not found."""
        ...

    async def begin(self) -> None:
        """Begin a commit transaction."""
        ...

    async def store(self, oid: OID, record: bytes) -> None:
        """Store record for oid within the current transaction."""
        ...

    async def end(self, handle_invalidations: Any | None = None) -> None:
        """End the transaction, committing or rolling back."""
        ...

    async def sync(self) -> list[OID]:
        """Sync and return list of invalidated OIDs."""
        ...

    async def new_oid(self) -> OID:
        """Allocate and return a new OID."""
        ...

    async def gen_oid_record(
        self, start_oid: OID | None = None, batch_size: int = 100
    ) -> AsyncIterator[tuple[OID, bytes]]:
        """Async generator yielding (oid, record) pairs."""
        ...

    async def bulk_load(self, oids: list[OID]) -> AsyncIterator[bytes]:
        """Async bulk load — yields bytes records for each oid."""
        ...

    async def pack(self) -> None:
        """Pack storage, removing obsolete records."""
        ...

    async def health(self) -> bool:
        """Return True if storage is healthy."""
        ...

    async def cleanup(self) -> None:
        """Clean up resources (close connections, etc.)."""
        ...

    async def close(self) -> None:
        """Close and release all resources."""
        ...

    def get_packer(self) -> Any | None:
        """Return incremental packer generator, or None."""
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/storage/test_async_storage_protocol.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/storage/base.py
git commit -m "feat: add complete AsyncStorage protocol with all methods"
```

---

### Task 2: Create AsyncSqliteStorage

**Files:**
- Create: `dhara/storage/sqlite.py`
- Create: `tests/storage/` directory
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

@pytest.mark.asyncio
async def test_async_sqlite_storage_health():
    storage = AsyncSqliteStorage(":memory:")
    await storage.init()
    assert await storage.health() is True

@pytest.mark.asyncio
async def test_async_sqlite_storage_close():
    storage = AsyncSqliteStorage(":memory:")
    await storage.init()
    await storage.close()
    # After close, load should raise
    with pytest.raises(AssertionError):
        await storage.load("any")

@pytest.mark.asyncio
async def test_async_sqlite_storage_gen_oid_record():
    storage = AsyncSqliteStorage(":memory:")
    await storage.init()
    oid1 = await storage.new_oid()
    oid2 = await storage.new_oid()
    await storage.begin()
    await storage.store(oid1, b"record1")
    await storage.store(oid2, b"record2")
    await storage.end()
    records = [r async for r in storage.gen_oid_record()]
    assert len(records) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/storage/test_sqlite.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write minimal AsyncSqliteStorage**

Implement all methods in the AsyncStorage protocol. Key implementation notes:
- Use `aiosqlite.connect()` for async SQLite
- WAL mode pragmas must be set per-connection (re-applied on reconnect)
- `gen_oid_record` uses `async for` over `async with self._conn.execute()` cursor
- `bulk_load` uses async cursor iteration
- `__aenter__` / `__aexit__` for async context manager protocol
- `close()` calls `await self._conn.close()`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/storage/test_sqlite.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/storage/sqlite.py dhara/__init__.py tests/storage/
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

@pytest.mark.asyncio
async def test_async_postgres_storage_connection_pool():
    storage = AsyncPostgresStorage("postgresql://localhost/testdb", min_size=2, max_size=5)
    await storage.init()
    # Should use pool — concurrent operations should work
    oid1 = await storage.new_oid()
    oid2 = await storage.new_oid()
    await storage.begin()
    await storage.store(oid1, b"data1")
    await storage.store(oid2, b"data2")
    await storage.end()
    assert await storage.health() is True

@pytest.mark.asyncio
async def test_async_postgres_storage_close():
    storage = AsyncPostgresStorage("postgresql://localhost/testdb")
    await storage.init()
    await storage.close()
    assert await storage.health() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/storage/test_postgres.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write AsyncPostgresStorage**

Implement all AsyncStorage protocol methods using asyncpg:
- `init()`: create connection pool with `asyncpg.create_pool()`
- `load()`: acquire connection from pool, `fetchrow`
- `gen_oid_record`: async generator over `pool.acquire()` cursor
- `bulk_load`: async iteration over multiple `fetchrow` calls
- `close()`: close pool with `pool.close()`
- `health()`: try `pool.acquire()` — if succeeds, healthy
- `__aenter__` / `__aexit__` for async context manager

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/storage/test_postgres.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/storage/postgres.py
git commit -m "feat: add AsyncPostgresStorage using asyncpg"
```

---

### Task 4: Add AsyncMemoryStorage (Native Async)

**Files:**
- Modify: `dhara/storage/memory.py`

- [ ] **Step 1: Write failing test**

```python
# tests/storage/test_memory.py
import pytest
from dhara.storage.memory import MemoryStorage

@pytest.mark.asyncio
async def test_async_memory_storage():
    """MemoryStorage async methods are native coroutines, not executor wrappers."""
    storage = MemoryStorage()
    await storage.init()
    oid = await storage.new_oid()
    await storage.begin()
    await storage.store(oid, b"test")
    await storage.end()
    result = await storage.load(oid)
    assert result == b"test"

@pytest.mark.asyncio
async def test_async_memory_storage_is_native():
    """Verify async methods are actual coroutines, not wrapped sync."""
    storage = MemoryStorage()
    import inspect
    assert inspect.iscoroutinefunction(storage.load)
    assert inspect.iscoroutinefunction(storage.begin)
    assert inspect.iscoroutinefunction(storage.store)
    assert inspect.iscoroutinefunction(storage.end)
    assert inspect.iscoroutinefunction(storage.new_oid)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/storage/test_memory.py -v`
Expected: FAIL — async methods not defined

- [ ] **Step 3: Implement native async methods on MemoryStorage**

MemoryStorage is already in-memory (no I/O blocking). Convert all methods to native `async def` coroutines — no `run_in_executor()` needed. The in-memory dict operations are fast enough to be truly async-native.

```python
# Add to MemoryStorage class:
async def init(self) -> None:
    """No-op for MemoryStorage — exists for protocol compatibility."""
    pass

async def load(self, oid):
    if oid not in self._data:
        raise KeyError(oid)
    return self._data[oid]

async def begin(self) -> None:
    pass # No transaction needed for in-memory

async def store(self, oid, record) -> None:
    self._data[oid] = record

async def end(self, handle_invalidations=None) -> None:
    pass

async def sync(self) -> list:
    return []

async def new_oid(self) -> OID:
    ...

# etc. — all native async, no executor
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/storage/test_memory.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/storage/memory.py
git commit -m "feat: add native async methods to MemoryStorage"
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

### Task 5: Delete FileStorage

**Files:**
- Delete: `dhara/storage/file.py`
- Remove from exports in `dhara/__init__.py`

**NOTE: This task runs AFTER Task 6 (exports updated) and AFTER Task 15 (catalog.py updated). FileStorage deletion must not break any still-referenced imports.**

- [ ] **Step 1: Verify no internal usages remain**

```bash
grep -r "FileStorage" dhara/ --include="*.py" | grep -v "__pycache__"
```
Expected: nothing (Task 15 updated catalog.py first)

- [ ] **Step 2: Delete file**

```bash
rm dhara/storage/file.py
```

- [ ] **Step 3: Commit**

```bash
git rm dhara/storage/file.py
git commit -m "feat: remove FileStorage — async storage only"
```

---

### Task 7: Add AsyncConnection Class (All Methods Explicit)

**Files:**
- Modify: `dhara/core/connection.py`
- Create: `tests/test_async_connection.py`

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
    conn = await AsyncConnection.new(storage)
    root = await conn.get_root()
    await root.set("key", "value")
    await conn.commit()
    loaded = await conn.get(root._p_oid)
    assert loaded is not None

@pytest.mark.asyncio
async def test_async_connection_abort():
    storage = MemoryStorage()
    await storage.init()
    conn = await AsyncConnection.new(storage)
    root = await conn.get_root()
    await root.set("key", "value")
    await conn.abort()
    # After abort, key should not be in root
    assert "key" not in root

@pytest.mark.asyncio
async def test_async_connection_get_crawler():
    storage = MemoryStorage()
    await storage.init()
    conn = await AsyncConnection.new(storage)
    root = await conn.get_root()
    for i in range(5):
        root.set(f"key{i}", f"value{i}")
    await conn.commit()
    crawled = [obj async for obj in conn.get_crawler()]
    assert len(crawled) >= 1

@pytest.mark.asyncio
async def test_async_connection_pack():
    storage = MemoryStorage()
    await storage.init()
    conn = await AsyncConnection.new(storage)
    await conn.pack()  # Should not raise

@pytest.mark.asyncio
async def test_async_connection_factory_returns_instance():
    """Verify AsyncConnection.new() returns an initialized AsyncConnection."""
    storage = MemoryStorage()
    await storage.init()
    conn = await AsyncConnection.new(storage)
    assert conn is not None
    assert conn.storage is storage
    assert conn.root is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_async_connection.py -v`
Expected: FAIL — AsyncConnection not defined

- [ ] **Step 3: Write AsyncConnection with ALL methods**

```python
# In dhara/core/connection.py, add after Connection class:

class AsyncConnection:
    """Fully async Connection — all storage operations are awaited."""

    # Factory coroutine — __init__ cannot be async in Python
    @classmethod
    async def new(cls, storage: AsyncStorage, cache_size: int = 100000, root_class=None, cache=None):
        """Async factory — creates and initializes AsyncConnection."""
        if isinstance(storage, str):
            raise TypeError("AsyncConnection requires an AsyncStorage instance, not a path string")
        assert isinstance(storage, AsyncStorage), f"Expected AsyncStorage, got {type(storage).__name__}"
        self = cls.__new__(cls)
        self.storage = storage
        self.reader = ObjectReader(self)
        self.changed = {}
        self.invalid_oids = set()
        # Don't set self.new_oid — keep the async method from being shadowed
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
        return self

    # ── Core async methods ──────────────────────────────────────

    async def get(self, oid):
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

    __getitem__ = get

    async def get_stored_pickle(self, oid):
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

    async def get_root(self):
        return self.root

    async def get_storage(self):
        return self.storage

    async def get_cache_count(self):
        return self.cache.get_count()

    async def get_cache_size(self):
        return self.cache.get_size()

    async def set_cache_size(self, size):
        self.cache.set_size(size)

    async def get_transaction_serial(self):
        return self.transaction_serial

    async def get_load_count(self):
        return self.reader.get_load_count()

    async def note_access(self, obj):
        assert obj._p_connection is self
        assert obj._p_oid is not None
        _setattribute(obj, "_p_serial", self.transaction_serial)
        self.cache.recent_objects.add(obj)
        self.cache._lru[obj._p_oid] = None
        self.cache._lru.move_to_end(obj._p_oid)

    async def note_change(self, obj):
        self.changed[obj._p_oid] = obj

    async def load_state(self, obj):
        assert self.storage is not None, "connection is closed"
        assert obj._p_is_ghost()
        oid = obj._p_oid
        try:
            pickle = await self.get_stored_pickle(oid)
        except DruvaKeyError:
            raise ReadConflictError([oid])
        state = self.reader.get_state(pickle)
        obj.__setstate__(state)
        obj._p_set_status_saved()

    async def get_crawler(self, start_oid=ROOT_OID, batch_size=100):
        """Async generator — yields PersistentObjects via bulk_load."""
        oid_record_sequence = self.storage.gen_oid_record(
            start_oid=start_oid, batch_size=batch_size
        )
        async for oid, record in oid_record_sequence:
            obj = self.cache.get(oid)
            if obj is not None and not obj._p_is_ghost():
                yield obj
            else:
                record_oid, data, refdata = unpack_record(record)
                if obj is None:
                    klass = loads(data)
                    obj = self.cache.get_instance(oid, klass, self)
                state = self.reader.get_state(data, load=True)
                obj.__setstate__(state)
                obj._p_set_status_saved()
                yield obj

    async def get_cache(self):
        return self.cache

    async def shrink_cache(self):
        self.cache.shrink(self)

    async def _sync(self):
        invalid_oids = await self.storage.sync()
        self.invalid_oids.update(invalid_oids)
        for oid in self.invalid_oids:
            obj = self.cache.get(oid)
            if obj is not None:
                obj._p_set_status_ghost()
        self.invalid_oids.clear()

    async def abort(self):
        for oid, obj in iteritems(self.changed):
            obj._p_set_status_ghost()
        self.changed.clear()
        await self._sync()
        await self.shrink_cache()
        self.transaction_serial += 1
        # Cache.clear() doesn't exist — ObjectDictionary has clear_dead()
        # Clear dead references on abort to maintain cache integrity
        if self.cache is not None and hasattr(self.cache.objects, 'clear_dead'):
            self.cache.objects.clear_dead()

    async def commit(self):
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
        await self.shrink_cache()
        self.transaction_serial += 1

    def _handle_invalidations(self, oids, read_oid=None):
        conflicts = []
        for oid in oids:
            obj = self.cache.get(oid)
            if obj is None:
                continue
            if obj._p_serial == self.transaction_serial:
                conflicts.append(oid)
                self.invalid_oids.add(oid)
            elif not obj._p_is_ghost():
                assert oid not in self.changed
                obj._p_set_status_ghost()
        if conflicts:
            if read_oid is None:
                raise WriteConflictError(conflicts)
            else:
                raise ReadConflictError([read_oid])

    async def pack(self):
        await self.abort()
        await self.storage.pack()

    async def new_oid(self) -> OID:
        return await self.storage.new_oid()

    async def touch_every_reference(self, *words):
        """Mark as changed every object whose pickled class/state contains any of the given words."""
        get = self.get
        reader = ObjectReader(self)
        words = [as_bytes(w) for w in words]
        async for oid, record in self.storage.gen_oid_record():
            record_oid, data, refs = unpack_record(record)
            state = reader.get_state_pickle(data)
            for word in words:
                if word in data or word in state:
                    (await get(oid))._p_note_change()

    async def gen_every_instance(self, *classes):
        """Generate all PersistentObject instances that are instances of any of the given classes."""
        async for oid, record in self.storage.gen_oid_record():
            record_oid, state, refs = unpack_record(record)
            record_class = loads(state)
            if issubclass(record_class, classes):
                yield await self.get(oid)
```

**Usage:**
```python
conn = await AsyncConnection.new(storage)
root = await conn.get_root()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_async_connection.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/core/connection.py tests/test_async_connection.py
git commit -m "feat: add AsyncConnection — fully async OID persistence"
```

---

### Task 8: Add Async PersistentObject Methods

**Files:**
- Modify: `dhara/core/persistent.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_async_persistent_object.py
import pytest
from dhara.storage.memory import MemoryStorage
from dhara.core.connection import AsyncConnection

@pytest.mark.asyncio
async def test_async_persistent_object_get_set():
    storage = MemoryStorage()
    await storage.init()
    conn = AsyncConnection(storage)
    root = await conn.get_root()
    await root.set("key", "value")
    await conn.commit()
    assert await root.get("key") == "value"

@pytest.mark.asyncio
async def test_async_persistent_object_abort():
    storage = MemoryStorage()
    await storage.init()
    conn = AsyncConnection(storage)
    root = await conn.get_root()
    await root.set("key", "value")
    await conn.abort()
    assert "key" not in root
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_async_persistent_object.py -v`
Expected: FAIL

- [ ] **Step 3: Implement async methods on PersistentObject**

Add `_p_get_async()`, `_p_set_async()`, `_p_commit_async()`, `_p_abort_async()`. These wrap the sync counterparts with `await` when calling async Connection methods.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_async_persistent_object.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/core/persistent.py
git commit -m "feat: add async methods to PersistentObject"
```

---

### Task 9: Add AsyncPersistentDict

**Files:**
- Modify: `dhara/collections/dict.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_async_persistent_dict.py
import pytest
from dhara.storage.memory import MemoryStorage
from dhara.core.connection import AsyncConnection

@pytest.mark.asyncio
async def test_async_persistent_dict_get_set():
    storage = MemoryStorage()
    await storage.init()
    conn = AsyncConnection(storage)
    d = await conn.get_root()
    await d.set("key", "value")
    await conn.commit()
    assert await d.get("key") == "value"

@pytest.mark.asyncio
async def test_async_persistent_dict_contains():
    storage = MemoryStorage()
    await storage.init()
    conn = AsyncConnection(storage)
    d = await conn.get_root()
    await d.set("key", "value")
    await conn.commit()
    assert await d.contains("key")
    assert not await d.contains("missing")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_async_persistent_dict.py -v`
Expected: FAIL

- [ ] **Step 3: Implement AsyncPersistentDict**

Add async versions of all `PersistentDict` methods that call `connection.get()` or `connection.commit()`. The core dict operations (`__getitem__`, `__setitem__`, `__contains__`, `__delitem__`, `__len__`) stay sync — only the connection-calling methods become async.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_async_persistent_dict.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/collections/dict.py
git commit -m "feat: add AsyncPersistentDict with async methods"
```

---

### Task 10: Add AsyncPersistentList

**Files:**
- Modify: `dhara/collections/list.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_async_persistent_list.py
import pytest
from dhara.storage.memory import MemoryStorage
from dhara.core.connection import AsyncConnection

@pytest.mark.asyncio
async def test_async_persistent_list_append():
    storage = MemoryStorage()
    await storage.init()
    conn = AsyncConnection(storage)
    root = await conn.get_root()
    lst = root.get("mylist")
    if lst is None:
        from dhara.collections.list import PersistentList
        lst = PersistentList(conn)
        root.set("mylist", lst)
    await lst.append("item1")
    await lst.append("item2")
    await conn.commit()
    assert await lst.get(0) == "item1"
    assert await lst.length() == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_async_persistent_list.py -v`
Expected: FAIL

- [ ] **Step 3: Implement AsyncPersistentList**

Same pattern as AsyncPersistentDict — async wrapper methods for connection-calling operations.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_async_persistent_list.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/collections/list.py
git commit -m "feat: add AsyncPersistentList with async methods"
```

---

### Task 11: BTree Async Wrapper

**Files:**
- Modify: `dhara/collections/btree.py`

**NOTE: BTree is a pure in-memory data structure with no I/O. Its `get()`, `set()`, `delete()`, `items()`, etc. are all sync and stay sync. This task adds an async wrapper only for compatibility with async storage backends — the underlying tree operations are unchanged.**

- [ ] **Step 1: Write failing test**

```python
# tests/test_async_btree.py
import pytest
from dhara.collections.btree import BTree

@pytest.mark.asyncio
async def test_btree_async_wrapper_set_get():
    tree = BTree()
    await tree.set("key", "value")
    result = await tree.get("key")
    assert result == "value"

@pytest.mark.asyncio
async def test_btree_async_wrapper_delete():
    tree = BTree()
    await tree.set("key", "value")
    result = await tree.delete("key")
    assert result is True
    assert await tree.get("key") is None

@pytest.mark.asyncio
async def test_btree_async_wrapper_update():
    tree = BTree()
    await tree.set("key", "value1")
    result = await tree.update("key", "value2")
    assert result is True
    assert await tree.get("key") == "value2"

@pytest.mark.asyncio
async def test_btree_async_wrapper_items():
    tree = BTree()
    await tree.set("a", "1")
    await tree.set("b", "2")
    await tree.set("c", "3")
    items = [item async for item in tree.items()]
    assert len(items) == 3

@pytest.mark.asyncio
async def test_btree_async_wrapper_keys():
    tree = BTree()
    await tree.set("x", "1")
    await tree.set("y", "2")
    keys = [k async for k in tree.keys()]
    assert len(keys) == 2

@pytest.mark.asyncio
async def test_btree_async_wrapper_values():
    tree = BTree()
    await tree.set("a", "one")
    await tree.set("b", "two")
    values = [v async for v in tree.values()]
    assert len(values) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_async_btree.py -v`
Expected: FAIL — `set` not async

- [ ] **Step 3: Add async wrapper methods to BTree**

Add `async def set(self, key, value)` and `async def delete(self, key)` — thin async wrappers around the sync core. The internal `_insert_nonfull`, `_delete_from_node`, etc. stay sync since they're fast in-memory operations.

```python
async def set(self, key, value):
    """Async wrapper — delegates to sync set()."""
    self._set_impl(key, value)

async def get(self, key):
    """Async wrapper — delegates to sync get()."""
    return self._get_impl(key)

# Keep core sync methods private:
def _set_impl(self, key, value):
    # ... current set() implementation
    pass

def _get_impl(self, key):
    # ... current get() implementation
    pass
```

Refactor existing `set()` to call `_set_impl()`. Refactor existing `get()` to call `_get_impl()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_async_btree.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/collections/btree.py
git commit -m "feat: add async wrapper methods to BTree for storage compat"
```

---

### Task 12: Update KVTimeSeriesStore to AsyncConnection

**Files:**
- Modify: `dhara/mcp/kv_timeseries.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_mcp_kv_timeseries.py
import pytest
from dhara.storage.memory import MemoryStorage
from dhara.mcp.kv_timeseries import KVTimeSeriesStore

@pytest.mark.asyncio
async def test_kv_timeseries_async_put_get():
    storage = MemoryStorage()
    await storage.init()
    store = KVTimeSeriesStore(storage)
    await store.put("key1", b"value1")
    result = await store.get("key1")
    assert result == b"value1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mcp_kv_timeseries.py::test_kv_timeseries_async_put_get -v`
Expected: FAIL

- [ ] **Step 3: Update KVTimeSeriesStore to use AsyncConnection**

Replace `self.connection = Connection(self.storage)` with `self.connection = AsyncConnection(self.storage)`. Convert all `self.connection.get()` to `await self.connection.get()`, all `self.connection.commit()` to `await self.connection.commit()`, etc.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mcp_kv_timeseries.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/mcp/kv_timeseries.py
git commit -m "feat: update KVTimeSeriesStore to use AsyncConnection"
```

---

### Task 13: Update MCP Server Core to AsyncConnection

**Files:**
- Modify: `dhara/mcp/server_core.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_mcp_server_core.py
import pytest
from dhara.storage.memory import MemoryStorage
from dhara.mcp.server_core import MCPServer

@pytest.mark.asyncio
async def test_mcp_server_async_init():
    storage = MemoryStorage()
    await storage.init()
    server = MCPServer(storage)
    await server.initialize()
    assert server.connection is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mcp_server_core.py::test_mcp_server_async_init -v`
Expected: FAIL

- [ ] **Step 3: Update server_core.py to use AsyncConnection**

Convert all `connection.get()` to `await connection.get()`, `connection.commit()` to `await connection.commit()`, etc. Update the `sync_tool_map` to use async wrappers.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mcp_server_core.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/mcp/server_core.py
git commit -m "feat: update MCP server core to use AsyncConnection"
```

---

### Task 14: Update MCP Adapter Tools to AsyncConnection

**Files:**
- Modify: `dhara/mcp/adapter_tools.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_mcp_adapter_tools.py
import pytest
from dhara.storage.memory import MemoryStorage
from dhara.mcp.adapter_tools import SomeAdapterTool  # adjust to actual tools

@pytest.mark.asyncio
async def test_adapter_tools_async():
    storage = MemoryStorage()
    await storage.init()
    # Test that adapter tools work with AsyncConnection
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mcp_adapter_tools.py -v`
Expected: FAIL

- [ ] **Step 3: Update adapter_tools.py to use AsyncConnection**

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mcp_adapter_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/mcp/adapter_tools.py
git commit -m "feat: update MCP adapter tools to use AsyncConnection"
```

---

### Task 15: Update Backup Catalog to AsyncConnection

**Files:**
- Modify: `dhara/backup/catalog.py`

**NOTE: This task must run BEFORE Task 5 (FileStorage deletion). It removes the `from dhara.storage.file import FileStorage` import.**

- [ ] **Step 1: Write failing test**

```python
# tests/test_backup_catalog.py
import pytest
import tempfile
from pathlib import Path
from dhara.backup.catalog import BackupCatalog

@pytest.mark.asyncio
async def test_backup_catalog_with_memory_storage():
    """BackupCatalog accepts a backup_dir path, not a storage object."""
    with tempfile.TemporaryDirectory() as tmpdir:
        catalog = BackupCatalog(tmpdir)
        # BackupCatalog uses AsyncSqliteStorage internally at backup_dir
        await catalog.init()
        await catalog.add_entry("key", "value")
        await catalog.save()
        assert await catalog.has_entry("key")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backup_catalog.py -v`
Expected: FAIL

- [ ] **Step 3: Update catalog.py to use AsyncConnection**

Replace `from dhara.storage.file import FileStorage` and `FileStorage(...)` with `AsyncConnection(AsyncSqliteStorage(...))` or `AsyncConnection(AsyncPostgresStorage(...))`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backup_catalog.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/backup/catalog.py
git commit -m "feat: update backup catalog to use AsyncConnection"
```

---

### Task 16: Update Backup Restore to AsyncConnection

**Files:**
- Modify: `dhara/backup/restore.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_backup_restore.py
import pytest
from dhara.storage.memory import MemoryStorage
from dhara.backup.restore import restore_from_backup

@pytest.mark.asyncio
async def test_restore_async():
    storage = MemoryStorage()
    await storage.init()
    # Test restore flow with AsyncConnection
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backup_restore.py -v`
Expected: FAIL

- [ ] **Step 3: Update restore.py to use AsyncConnection**

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backup_restore.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/backup/restore.py
git commit -m "feat: update backup restore to use AsyncConnection"
```

---

### Task 17: Update CLI to Async Entry Point

**Files:**
- Modify: `dhara/cli.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_cli.py
import pytest
from dhara.cli import async_main  # or whichever is the async entry point

@pytest.mark.asyncio
async def test_cli_async_main():
    # Test CLI commands work with async storage
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL

- [ ] **Step 3: Update cli.py for async**

Convert CLI entry points to async. Use `asyncio.run()` at the top level. Ensure all storage operations use `await`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add dhara/cli.py
git commit -m "feat: update CLI to async entry point"
```

---

### Task 18: Update __main__.py for Async

**Files:**
- Modify: `dhara/__main__.py`

- [ ] **Step 1: Update __main__.py**

```python
# Replace sync main() with async:
async def async_main():
    # ... existing main() logic, but with await on all async calls
    ...

if __name__ == "__main__":
    asyncio.run(async_main())
```

- [ ] **Step 2: Commit**

```bash
git add dhara/__main__.py
git commit -m "feat: update __main__ to async entry point"
```

---

### Task 19: Update bin/db_renumber.py

**Files:**
- Modify: `bin/db_renumber.py`

- [ ] **Step 1: Update to use AsyncConnection**

Replace `Connection(...)` with `AsyncConnection(...)`, add `await` to all async calls.

- [ ] **Step 2: Commit**

```bash
git add bin/db_renumber.py
git commit -m "feat: update db_renumber to use AsyncConnection"
```

---

### Task 20: Update bin/db_to_py3k.py

**Files:**
- Modify: `bin/db_to_py3k.py`

- [ ] **Step 1: Update to use AsyncConnection**

- [ ] **Step 2: Commit**

```bash
git add bin/db_to_py3k.py
git commit -m "feat: update db_to_py3k to use AsyncConnection"
```

---

### Task 21: Update Tests Conftest

**Files:**
- Modify: `tests/conftest.py`

**CRITICAL FIX: Remove the deprecated `event_loop` fixture (lines 98-107). This fixture conflicts with `pytest.mark.asyncio` marker style. Replace with modern pytest-asyncio configuration.**

- [ ] **Step 1: Write failing test**

```python
# tests/test_conftest_fixture.py
import pytest

def test_no_deprecated_event_loop_fixture():
    """Verify conftest.py does not define an event_loop fixture (deprecated in pytest-asyncio)."""
    import ast
    with open("tests/conftest.py") as f:
        content = f.read()
    # Check that no FunctionDef named 'event_loop' exists in the module
    tree = ast.parse(content)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "event_loop":
            pytest.fail("conftest.py still defines event_loop fixture — must be removed for pytest-asyncio compatibility")
    # Also verify pytest_asyncio is configured (asyncio_mode = "auto")
    import pytest_asyncio
    assert hasattr(pytest_asyncio, 'pytest_configure'), "pytest-asyncio not properly loaded"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_conftest_fixture.py -v`
Expected: FAIL

- [ ] **Step 3: Fix conftest.py**

1. Remove the `event_loop` fixture function
2. Add `pytest_plugins = ['pytest_asyncio']` if not present
3. Replace `FileStorage` in fixtures with `AsyncSqliteStorage`
4. Add `pytest.ini` or `pyproject.toml` config for pytest-asyncio:
   ```toml
   [tool.pytest.ini_options]
   asyncio_mode = "auto"
   ```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_conftest_fixture.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py pyproject.toml  # if updating config
git commit -m "test: remove deprecated event_loop fixture, use AsyncSqliteStorage"
```

---

### Task 22: Update test_core_connection_methods.py

**Files:**
- Modify: `tests/test_core_connection_methods.py`

- [ ] **Step 1: Write failing test**

All existing sync tests become async. For each existing test, add `async def test_...()` with `pytest.mark.asyncio` and `await` on all async calls.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_core_connection_methods.py -v`
Expected: FAIL

- [ ] **Step 3: Convert all tests to async**

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_core_connection_methods.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_core_connection_methods.py
git commit -m "test: convert test_core_connection_methods to async"
```

---

### Task 23: Update test_mcp_kv_timeseries.py

**Files:**
- Modify: `tests/test_mcp_kv_timeseries.py`

- [ ] **Step 1: Convert all tests to async**

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_mcp_kv_timeseries.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_mcp_kv_timeseries.py
git commit -m "test: convert test_mcp_kv_timeseries to async"
```

---

### Task 24: Update test_mcp_server_core.py

**Files:**
- Modify: `tests/test_mcp_server_core.py`

- [ ] **Step 1: Convert all tests to async**

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_mcp_server_core.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_mcp_server_core.py
git commit -m "test: convert test_mcp_server_core to async"
```

---

### Task 25: Crackerjack Integration — Option B (MCP Client)

**Files:**
- Modify: `crackerjack/integration/dhara_integration.py`

**DESIGN DECISION: Option B (MCP client) is used, not direct AsyncConnection.**

`DharaAdapterLearner` uses Dhara's existing high-level MCP tools (`put`, `get`, `record_time_series`, `query_time_series`) over HTTP, just like Akosha and Mahavishnu. This means:
- No direct `Connection` or `AsyncConnection` import in crackerjack
- `DharaAdapterLearner` becomes an HTTP/MCP client
- Uses existing MCP tools, no new MCP server endpoints needed
- Crackerjack becomes an MCP client like the rest of the Bodai ecosystem

**Rationale:** `DharaAdapterLearner` only needs high-level KV/time-series operations (lines 541-611 of `dhara_integration.py`). All operations are `record_time_series`, `put`, `get` — exactly what the MCP server already exposes. No direct OID access needed.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/agents/test_dhara_adapter_learner_mcp.py
import pytest

@pytest.mark.asyncio
async def test_dhara_adapter_learner_uses_mcp():
    """DharaAdapterLearner should use HTTP/MCP, not direct Connection."""
    from unittest.mock import patch, AsyncMock
    with patch("httpx.Client") as mock_client:
        mock_client.return_value.post = AsyncMock(return_value=MockResponse(...))
        learner = DharaAdapterLearner()
        await learner.record_adapter_attempt(...)
        # Verify HTTP POST was called, not Connection.commit()
        mock_client.return_value.post.assert_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/agents/test_dhara_adapter_learner_mcp.py -v`
Expected: FAIL

- [ ] **Step 3: Rewrite DharaAdapterLearner as MCP client**

Replace direct `Connection(FileStorage(...))` with HTTP calls to Dhara MCP server using `httpx` or similar async HTTP client. All existing `record_adapter_attempt` logic stays the same — just the storage layer changes from local file to HTTP/MCP.

Key changes:
- Remove `from dhara.core.connection import Connection`
- Remove `from dhara.storage.file import FileStorage`
- Add HTTP client for Dhara MCP server
- All `put`/`get`/`record_time_series` calls go over HTTP instead of direct storage

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/agents/test_dhara_adapter_learner_mcp.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add crackerjack/integration/dhara_integration.py
git commit -m "feat: DharaAdapterLearner uses MCP client pattern (Option B)"
```

---

### Task 26: Update Crackerjack Test Files

**Files:**
- Modify: `crackerjack/tests/unit/agents/test_import_optimization_agent.py`
- Modify: `crackerjack/tests/unit/agents/test_planning_agent_fixes.py`

- [ ] **Step 1: Update dhara imports in test files**

Remove any remaining direct `from dhara.core.connection import Connection` or `from dhara.storage.file import FileStorage` imports. Use mock MCP client or `httpx` mocks instead.

- [ ] **Step 2: Commit**

```bash
git add crackerjack/tests/unit/agents/test_import_optimization_agent.py crackerjack/tests/unit/agents/test_planning_agent_fixes.py
git commit -m "test: update crackerjack test files for MCP client pattern"
```

---

## Dependency Order

```
Task 1 (AsyncStorage protocol — complete)
 └─ Task 2 (AsyncSqliteStorage)
  └─ Task 3 (AsyncPostgresStorage)
  └─ Task 4 (AsyncMemoryStorage — native async)
  └─ Task 6 (Update exports)
        └─ Task 15 (catalog.py update — uses AsyncConnection)
 └─ Task 7 (AsyncConnection — depends on Task 1 for type annotations)
      └─ Task 8 (Async PersistentObject)
      └─ Tasks 9-11 (Async collections — depend on Task 7)
            └─ Tasks 12-14 (MCP async)
 └─ Task 5 (Delete FileStorage — AFTER catalog.py)
      └─ Tasks 16-20 (Backup/CLI/Bin async)
            └─ Task 21 (conftest fix)
                  └─ Tasks 22-24 (Tests)
                        └─ Task 25 (Crackerjack MCP client)
                              └─ Task 26 (Crackerjack tests)
```

**Note:** Task 7 (AsyncConnection) imports from `dhara/storage/base.py` for the `AsyncStorage` type annotation, so it must run after Task 1 completes. Tasks 9, 10, 11 use `AsyncConnection` in their tests, so they must run after Task 7.

---

## No Migration Path

This is a breaking change. The old sync `Connection` and `Storage` are removed entirely. No compatibility layer, no gradual migration.

- Old code using `Connection(Storage(...))` breaks — must use `AsyncConnection(AsyncStorage(...))`
- Old code using `FileStorage` breaks — must use `AsyncSqliteStorage` or `AsyncPostgresStorage`
- All `await conn.commit()` instead of `conn.commit()`
- All `await conn.get(oid)` instead of `conn.get(oid)`
- Crackerjack `DharaAdapterLearner` no longer imports Dhara directly — uses HTTP/MCP client
