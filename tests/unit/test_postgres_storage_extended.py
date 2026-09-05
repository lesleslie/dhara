"""Extended coverage for dhara.storage.postgres.AsyncPostgresStorage.

The existing test_postgres_storage.py covers basic init/health/transaction/
load/new_oid. This file pushes the remaining ~42% of the module:

- settings unpacking (PostgresStorageSettings first arg)
- Oneiric config fallback chain
- init() pool creation + schema
- load() success + KeyError
- begin()/store()/end() with pack_extra
- sync() with and without dirty rows
- gen_oid_record() with and without start_oid
- bulk_load() and pack()
- health() success + failure paths
- cleanup(), close(), get_packer()
- async context manager (__aenter__/__aexit__)

Like the lock tests, we don't need a real Postgres — asyncpg is replaced
by a duck-typed FakePool/FakeConnection that satisfies the same shape.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from dhara.serialize.record import pack_record
from dhara.storage.postgres import (
    AsyncPostgresStorage,
    PostgresStorageSettings,
)
from dhara.utils import int8_to_str


# --------------------------- fakes ---------------------------


class FakeTransaction:
    def __init__(self) -> None:
        self.started = False
        self.committed = False
        self.rolled_back = False
        self.commit_should_raise: Exception | None = None

    async def __aenter__(self) -> "FakeTransaction":
        self.started = True
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def start(self) -> None:
        self.started = True

    async def commit(self) -> None:
        if self.commit_should_raise is not None:
            raise self.commit_should_raise
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class FakeConnection:
    """Duck-typed asyncpg.Connection."""

    def __init__(self) -> None:
        self.execute_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetch_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetchrow_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetchval_calls: list[tuple[str, tuple[Any, ...]]] = []
        # Configure return values per method:
        self.execute_returns: list[str] = ["OK"]
        self.fetch_returns: list[list[Any]] = [[]]
        self.fetchrow_returns: list[Any] = [None]
        self.fetchval_returns: list[Any] = [None]
        self.transaction_obj = FakeTransaction()
        self.execute_raises: Exception | None = None

    async def execute(self, query: str, *args: Any) -> str:
        self.execute_calls.append((query, args))
        if self.execute_raises is not None:
            raise self.execute_raises
        idx = min(len(self.execute_calls) - 1, len(self.execute_returns) - 1)
        return self.execute_returns[idx]

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        self.fetch_calls.append((query, args))
        idx = min(len(self.fetch_calls) - 1, len(self.fetch_returns) - 1)
        return self.fetch_returns[idx]

    async def fetchrow(self, query: str, *args: Any) -> Any | None:
        self.fetchrow_calls.append((query, args))
        idx = min(len(self.fetchrow_calls) - 1, len(self.fetchrow_returns) - 1)
        return self.fetchrow_returns[idx]

    async def fetchval(self, query: str, *args: Any) -> Any:
        self.fetchval_calls.append((query, args))
        idx = min(len(self.fetchval_calls) - 1, len(self.fetchval_returns) - 1)
        return self.fetchval_returns[idx]

    def transaction(self) -> FakeTransaction:
        return self.transaction_obj

    async def cursor(self, query: str, *args: Any) -> Any:
        # Used by gen_oid_record start_oid=None path. Return empty async iter.
        async def empty_iter() -> Any:
            if False:
                yield None  # pragma: no cover

        return empty_iter()


class FakePool:
    """Duck-typed asyncpg.Pool."""

    def __init__(self, conn: FakeConnection | None = None) -> None:
        self.conn = conn or FakeConnection()
        self.acquire_calls = 0
        self.release_calls: list[FakeConnection] = []
        self.closed = False
        self.create_pool_called_with: dict[str, Any] | None = None

    def acquire(self) -> Any:
        """Return an awaitable that yields self.conn.

        asyncpg.Pool.acquire() returns a _PoolAcquireContext that's
        awaitable. When produced by an ``async with`` block it acts as
        a context manager. The production code uses ``await acquire()``
        directly so we return an awaitable.

        For the init() test we need a context-manager form. That test
        patches ``asyncpg.create_pool`` directly so this fake is bypassed.
        """
        pool = self

        class _Acquire:
            def __await__(self) -> Any:
                pool.acquire_calls += 1
                async def _yield() -> Any:
                    return pool.conn
                return _yield().__await__()

            async def __aenter__(self) -> Any:
                pool.acquire_calls += 1
                return pool.conn

            async def __aexit__(self, *exc_info: object) -> None:
                return None

        return _Acquire()

    async def release(self, conn: FakeConnection) -> None:
        self.release_calls.append(conn)

    async def close(self) -> None:
        self.closed = True


# --------------------------- helpers ---------------------------


def _make_storage(pool: FakePool | None = None) -> AsyncPostgresStorage:
    """Build a storage adapter with our fake pool injected."""
    storage = AsyncPostgresStorage(
        url="postgresql://test/test", min_size=1, max_size=2
    )
    storage._pool = pool or FakePool()
    return storage


# --------------------------- settings unpacking ---------------------------


class TestSettingsUnpacking:
    """``AsyncPostgresStorage(settings)`` legacy API unpacks the settings."""

    def test_postgres_storage_settings_first_arg(self) -> None:
        settings = PostgresStorageSettings(
            pg_url="postgresql://u:p@h/d", min_size=3, max_size=15
        )
        storage = AsyncPostgresStorage(settings)
        assert storage._url == "postgresql://u:p@h/d"
        assert storage._min_size == 3
        assert storage._max_size == 15

    def test_settings_url_alias(self) -> None:
        """``url=`` is the production alias for ``pg_url=``."""
        settings = PostgresStorageSettings(url="postgresql://x/y", min_size=4)
        storage = AsyncPostgresStorage(settings)
        assert storage._url == "postgresql://x/y"
        assert storage._min_size == 4
        assert storage._max_size == 10  # default

    def test_pg_url_wins_when_both_provided(self) -> None:
        """``pg_url`` takes precedence over ``url`` (legacy compat)."""
        settings = PostgresStorageSettings(
            pg_url="postgresql://legacy/wins", url="postgresql://other/loses"
        )
        assert settings.url == "postgresql://legacy/wins"


# --------------------------- Oneiric config fallback ---------------------------


class TestOneiricConfigFallback:
    """When url/min_size/max_size are None, fall back through Oneiric config."""

    def test_oneiric_core_config_provides_values(self) -> None:
        """``oneiric.core.config.Oneiric.get_config`` is the primary path."""
        fake_oneiric = MagicMock()
        fake_oneiric.get_config.return_value = {
            "url": "postgresql://from-config/db",
            "min_size": 7,
            "max_size": 20,
        }
        with pytest.MonkeyPatch().context() as mp:
            mp.setitem(
                __import__("sys").modules,
                "oneiric.core.config",
                MagicMock(Oneiric=fake_oneiric),
            )
            storage = AsyncPostgresStorage()
        assert storage._url == "postgresql://from-config/db"
        assert storage._min_size == 7
        assert storage._max_size == 20

    def test_legacy_top_level_oneiric_used_when_core_missing(self) -> None:
        """If ``oneiric.core.config`` is missing, try ``oneiric.Oneiric``."""
        import sys

        fake_oneiric = MagicMock()
        fake_oneiric.get_config.return_value = {
            "url": "postgresql://legacy/db",
            "min_size": 3,
            "max_size": 12,
        }
        # Make oneiric.core.config importable but its get_config raise something
        # that's NOT ImportError, to drive the inner fallback. Actually the
        # inner fallback is only on ImportError. Easier: hide oneiric.core.config
        # entirely so the outer ImportError fires, then expose legacy oneiric.
        with pytest.MonkeyPatch().context() as mp:
            mp.delitem(sys.modules, "oneiric.core.config", raising=False)
            mp.setitem(
                sys.modules,
                "oneiric",
                MagicMock(Oneiric=fake_oneiric),
            )
            storage = AsyncPostgresStorage()
        assert storage._url == "postgresql://legacy/db"
        assert storage._min_size == 3
        assert storage._max_size == 12

    def test_hardcoded_defaults_when_oneiric_missing(self) -> None:
        """When Oneiric is entirely missing, hardcoded defaults are used."""
        import sys

        original_import = (
            __builtins__.__import__
            if isinstance(__builtins__, type(__import__("sys")))
            else __builtins__["__import__"]
        )

        def gated_import(name: str, *args: object, **kwargs: object) -> Any:
            if name == "oneiric" or name.startswith("oneiric."):
                raise ImportError(f"oneiric disabled: {name}")
            return original_import(name, *args, **kwargs)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("builtins.__import__", gated_import)
            storage = AsyncPostgresStorage()
        assert storage._url == "postgresql://localhost/dhara"
        assert storage._min_size == 2
        assert storage._max_size == 10


# --------------------------- init() ---------------------------


class TestInit:
    async def test_init_creates_pool_and_schema(self) -> None:
        """``init()`` calls create_pool and runs the schema DDL."""
        storage = AsyncPostgresStorage(
            url="postgresql://t/t", min_size=2, max_size=4
        )

        # Patch asyncpg.create_pool to return our fake.
        fake_pool = FakePool()
        with pytest.MonkeyPatch().context() as mp:

            async def fake_create_pool(*a: Any, **kw: Any) -> FakePool:
                return fake_pool

            mp.setattr(
                "dhara.storage.postgres.asyncpg.create_pool",
                fake_create_pool,
            )
            await storage.init()
        assert storage._pool is fake_pool
        # Schema DDL was executed on a connection from the pool.
        assert any("CREATE" in q.upper() for q, _ in fake_pool.conn.execute_calls)


# --------------------------- load() ---------------------------


class TestLoad:
    def test_load_returns_packed_record(self) -> None:
        storage = _make_storage()
        oid = int8_to_str(42)
        expected = pack_record(oid, b"data-bytes", b"ref-bytes")
        storage._pool.conn.fetchrow_returns = [
            {"oid": 42, "data": b"data-bytes", "refs": b"ref-bytes"}
        ]

        result = asyncio.run(storage.load(oid))

        assert result == expected
        # Verify the SELECT query used an int8 OID.
        assert storage._pool.conn.fetchrow_calls[0][1][0] == 42

    def test_load_raises_keyerror_when_missing(self) -> None:
        storage = _make_storage()
        storage._pool.conn.fetchrow_returns = [None]

        with pytest.raises(KeyError):
            asyncio.run(storage.load(int8_to_str(999)))

    def test_load_handles_null_data_and_refs(self) -> None:
        """Robustness: NULL columns → empty bytes in packed record."""
        storage = _make_storage()
        oid = int8_to_str(7)
        storage._pool.conn.fetchrow_returns = [{"oid": 7, "data": None, "refs": None}]

        result = asyncio.run(storage.load(oid))

        # pack_record with empty data and refs still produces a valid packed record.
        assert isinstance(result, bytes)
        assert len(result) > 0


# --------------------------- begin / store / end ---------------------------


class TestTransactionLifecycle:
    def test_begin_acquires_connection_and_starts_tx(self) -> None:
        storage = _make_storage()
        # Pre-clear pool state to make assertions clear.
        assert storage._conn is None
        assert storage._in_transaction is False

        asyncio.run(storage.begin())

        assert storage._conn is storage._pool.conn
        assert storage._in_transaction is True
        assert storage._pool.conn.transaction_obj.started is True
        # Pending records cleared.
        assert storage._pending_records == []

    def test_begin_twice_raises_runtimeerror(self) -> None:
        storage = _make_storage()
        asyncio.run(storage.begin())

        with pytest.raises(RuntimeError, match="already in transaction"):
            asyncio.run(storage.begin())

    def test_store_inserts_and_marks_dirty(self) -> None:
        storage = _make_storage()
        asyncio.run(storage.begin())

        oid = int8_to_str(123)
        record = pack_record(oid, b"data", b"")
        asyncio.run(storage.store(oid, record))

        # Two execute calls: INSERT and INSERT INTO dhara_dirty_oids.
        queries = [q for q, _ in storage._pool.conn.execute_calls]
        assert any("INSERT INTO dhara_objects" in q for q in queries)
        assert any("dhara_dirty_oids" in q for q in queries)

    def test_store_appends_to_pack_extra(self) -> None:
        storage = _make_storage()
        storage._pack_extra = []
        asyncio.run(storage.begin())

        oid = int8_to_str(5)
        record = pack_record(oid, b"x", b"")
        asyncio.run(storage.store(oid, record))

        assert oid in storage._pack_extra

    def test_store_without_begin_raises_runtimeerror(self) -> None:
        storage = _make_storage()

        with pytest.raises(RuntimeError, match="outside transaction"):
            asyncio.run(storage.store(int8_to_str(1), b""))

    def test_end_commits_and_releases(self) -> None:
        storage = _make_storage()
        asyncio.run(storage.begin())

        asyncio.run(storage.end())

        assert storage._pool.conn.transaction_obj.committed is True
        assert storage._conn is None
        assert storage._in_transaction is False

    def test_end_without_begin_raises(self) -> None:
        storage = _make_storage()

        with pytest.raises(RuntimeError, match="without begin"):
            asyncio.run(storage.end())

    def test_end_rolls_back_on_commit_failure(self) -> None:
        storage = _make_storage()
        asyncio.run(storage.begin())

        storage._pool.conn.transaction_obj.commit_should_raise = RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(storage.end())

        assert storage._pool.conn.transaction_obj.rolled_back is True
        assert storage._conn is None


# --------------------------- sync() ---------------------------


class TestSync:
    def test_sync_returns_empty_when_no_dirty(self) -> None:
        storage = _make_storage()
        # fetch returns empty list → no dirty oids → nothing deleted.
        storage._pool.conn.fetch_returns = [[]]

        result = asyncio.run(storage.sync())

        assert result == []
        # Only the SELECT ran; no DELETE.
        assert len(storage._pool.conn.execute_calls) == 0

    def test_sync_returns_dirty_and_deletes(self) -> None:
        storage = _make_storage()
        oid1 = int8_to_str(1)
        oid2 = int8_to_str(2)
        # fetch returns two rows; DELETE follows.
        storage._pool.conn.fetch_returns = [
            [{"oid": 1}, {"oid": 2}],
        ]

        result = asyncio.run(storage.sync())

        assert result == [oid1, oid2]
        # DELETE was called once.
        delete_calls = [q for q, _ in storage._pool.conn.execute_calls if "DELETE" in q]
        assert len(delete_calls) == 1


# --------------------------- new_oid() ---------------------------


class TestNewOid:
    def test_new_oid_returns_int8_bytes_from_sequence(self) -> None:
        storage = _make_storage()
        storage._pool.conn.fetchval_returns = [42]

        oid = asyncio.run(storage.new_oid())

        assert oid == int8_to_str(42)
        assert storage._pool.conn.fetchval_calls[0][0] == "SELECT nextval('dhara_oid_seq')"


# --------------------------- gen_oid_record() ---------------------------


class TestGenOidRecord:
    def test_gen_oid_record_no_start_oid_yields_from_cursor(self) -> None:
        """When start_oid is None, iterate ``dhara_objects`` via cursor."""
        storage = _make_storage()

        # Patch cursor to return an async iterator directly (no coroutine).
        async def empty_iter() -> Any:
            if False:
                yield None  # pragma: no cover

        storage._pool.conn.cursor = lambda *a, **kw: empty_iter()  # type: ignore[method-assign]

        async def collect() -> list[tuple[Any, bytes]]:
            return [r async for r in storage.gen_oid_record()]

        result = asyncio.run(collect())
        assert result == []

    def test_gen_oid_record_with_start_oid_skips_missing(self) -> None:
        """BFS: ``load()`` raising KeyError on an OID is silently skipped."""
        storage = _make_storage()
        oid = int8_to_str(7)
        expected_record = pack_record(oid, b"D", b"")

        # First load returns a record; second raises KeyError.
        load_calls = {"n": 0}

        async def fake_load(target_oid: Any) -> bytes:
            load_calls["n"] += 1
            if load_calls["n"] == 1:
                return expected_record
            raise KeyError(target_oid)

        storage.load = fake_load  # type: ignore[method-assign]

        async def collect() -> list[tuple[Any, bytes]]:
            return [
                r
                async for r in storage.gen_oid_record(
                    start_oid=oid, batch_size=10
                )
            ]

        result = asyncio.run(collect())
        assert len(result) == 1
        assert result[0][0] == oid


# --------------------------- bulk_load() ---------------------------


class TestBulkLoad:
    def test_bulk_load_yields_records_and_skips_missing(self) -> None:
        storage = _make_storage()
        oid1 = int8_to_str(1)
        oid2 = int8_to_str(2)
        oid3 = int8_to_str(3)
        record1 = pack_record(oid1, b"A", b"")
        # oid2 is missing; oid3 loads fine.

        async def fake_load(target_oid: Any) -> bytes:
            if target_oid == oid2:
                raise KeyError(target_oid)
            return record1 if target_oid == oid1 else pack_record(target_oid, b"C", b"")

        storage.load = fake_load  # type: ignore[method-assign]

        async def collect() -> list[bytes]:
            return [r async for r in storage.bulk_load([oid1, oid2, oid3])]

        result = asyncio.run(collect())
        # 3 loads; oid2's KeyError is skipped.
        assert len(result) == 2


# --------------------------- pack() / get_packer() ---------------------------


class TestPackPlaceholder:
    def test_pack_is_noop_placeholder(self) -> None:
        """``pack()`` is currently a no-op placeholder for the incremental packer."""
        storage = _make_storage()
        # Should not raise.
        asyncio.run(storage.pack())

    def test_get_packer_returns_none(self) -> None:
        """``get_packer()`` returns None until the incremental packer is wired."""
        storage = _make_storage()
        assert storage.get_packer() is None


# --------------------------- health() ---------------------------


class TestHealth:
    def test_health_returns_true_when_select_1_succeeds(self) -> None:
        storage = _make_storage()
        result = asyncio.run(storage.health())
        assert result is True

    def test_health_returns_false_when_pool_is_none(self) -> None:
        """No pool initialized → unhealthy."""
        storage = AsyncPostgresStorage(url="postgresql://t/t", min_size=1, max_size=2)
        storage._pool = None
        result = asyncio.run(storage.health())
        assert result is False

    def test_health_returns_false_when_select_raises_oserror(self) -> None:
        storage = _make_storage()
        # Wrap execute to raise OSError on SELECT 1.
        original = storage._pool.conn.execute

        async def selective_execute(query: str, *args: Any) -> str:
            if query.strip().upper().startswith("SELECT 1"):
                raise OSError("connection refused")
            return await original(query, *args)

        storage._pool.conn.execute = selective_execute  # type: ignore[method-assign]
        result = asyncio.run(storage.health())
        assert result is False

    def test_health_returns_false_when_select_raises_postgres_error(self) -> None:
        """asyncpg.PostgresError → False (caught via except clause)."""

        class FakePostgresError(Exception):
            pass

        storage = _make_storage()
        original = storage._pool.conn.execute

        async def selective_execute(query: str, *args: Any) -> str:
            if query.strip().upper().startswith("SELECT 1"):
                raise FakePostgresError("connection terminated")
            return await original(query, *args)

        storage._pool.conn.execute = selective_execute  # type: ignore[method-assign]

        # Patch the module-level asyncpg.PostgresError so the except clause works.
        import dhara.storage.postgres as pg_mod

        original_asyncpg = pg_mod.asyncpg
        patched = MagicMock()
        patched.PostgresError = FakePostgresError
        # asyncpg.create_pool is also referenced in init(); keep that working.
        patched.create_pool = original_asyncpg.create_pool

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pg_mod, "asyncpg", patched)
            result = asyncio.run(storage.health())
        assert result is False


# --------------------------- cleanup() / close() ---------------------------


class TestCleanupAndClose:
    def test_close_releases_pool(self) -> None:
        storage = _make_storage()
        pool = storage._pool
        assert pool is not None
        asyncio.run(storage.close())
        assert pool.closed is True
        assert storage._pool is None

    def test_close_is_noop_when_no_pool(self) -> None:
        storage = AsyncPostgresStorage(url="postgresql://t/t", min_size=1, max_size=2)
        storage._pool = None
        # Should not raise.
        asyncio.run(storage.close())

    def test_cleanup_calls_close(self) -> None:
        storage = _make_storage()
        pool = storage._pool
        asyncio.run(storage.cleanup())
        assert pool is not None
        assert pool.closed is True


# --------------------------- async context manager ---------------------------


class TestAsyncContextManager:
    async def test_aenter_initializes_and_returns_self(self) -> None:
        storage = AsyncPostgresStorage(
            url="postgresql://t/t", min_size=2, max_size=4
        )
        fake_pool = FakePool()
        with pytest.MonkeyPatch().context() as mp:

            async def fake_create_pool(*a: Any, **kw: Any) -> FakePool:
                return fake_pool

            mp.setattr(
                "dhara.storage.postgres.asyncpg.create_pool",
                fake_create_pool,
            )
            async with storage as ctx:
                assert ctx is storage
                assert storage._pool is fake_pool
                # Schema was executed.
                assert any("CREATE" in q.upper() for q, _ in fake_pool.conn.execute_calls)
        # On exit, the pool was closed.
        assert fake_pool.closed is True
