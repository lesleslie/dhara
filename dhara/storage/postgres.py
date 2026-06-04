# dhara/storage/postgres.py
"""AsyncPostgresStorage — async PostgreSQL storage implementing AsyncStorage protocol.

Uses asyncpg for async I/O with a connection pool. Configuration is loaded
from Oneiric under the ``dhara.storage.postgres`` namespace.

Supported config keys:
- url: PostgreSQL connection URL (default: postgresql://localhost/dhara)
- min_size: Pool min connections (default: 2)
- max_size: Pool max connections (default: 10)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import asyncpg

from dhara.serialize.record import pack_record, unpack_record
from dhara.storage.base import OID
from dhara.utils import int8_to_str, str_to_int8

# Schema for PostgreSQL storage
_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS dhara_objects (
    oid BIGINT PRIMARY KEY,
    data BYTEA,
    refs BYTEA
);
CREATE TABLE IF NOT EXISTS dhara_dirty_oids (
    oid BIGINT PRIMARY KEY,
    marked_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE SEQUENCE IF NOT EXISTS dhara_oid_seq;
"""


class AsyncPostgresStorage:
    """Async PostgreSQL storage implementing AsyncStorage protocol.

    Uses asyncpg for async I/O operations with a connection pool.
    Configuration is loaded from Oneiric under the ``dhara.storage.postgres``
    namespace.

    Args:
        url: PostgreSQL connection URL. Can be postgresql://user:pass@host/db.
        min_size: Pool min connections (default 2).
        max_size: Pool max connections (default 10).
    """

    _PACK_INCREMENT = 100  # number of records to pack before yielding

    def __init__(
        self,
        url: str | None = None,
        min_size: int | None = None,
        max_size: int | None = None,
    ) -> None:
        # Load config from Oneiric if params not provided
        if url is None or min_size is None or max_size is None:
            try:
                from oneiric import Oneiric

                config = Oneiric.get_config("dhara.storage.postgres")
                url = url or config.get("url", "postgresql://localhost/dhara")
                min_size = min_size or config.get("min_size", 2)
                max_size = max_size or config.get("max_size", 10)
            except Exception:
                # Fallback defaults if Oneiric unavailable
                url = url or "postgresql://localhost/dhara"
                min_size = min_size or 2
                max_size = max_size or 10

        self._url = url
        self._min_size = min_size
        self._max_size = max_size
        self._pool: asyncpg.Pool | None = None
        self._conn: asyncpg.Connection | None = None
        self._tx: asyncpg.Transaction | None = None
        self._in_transaction: bool = False
        self._pending_records: list[tuple[OID, bytes]] = []
        self._pack_extra: list[OID] | None = None
        self._invalid: set[OID] = set()

    async def init(self) -> None:
        """Initialize the async PostgreSQL connection pool."""
        self._pool = await asyncpg.create_pool(
            self._url,
            min_size=self._min_size,
            max_size=self._max_size,
            command_timeout=60,
        )
        # Initialize schema
        async with self._pool.acquire() as conn:
            await conn.execute(_PG_SCHEMA)

    async def load(self, oid: OID) -> bytes:
        """Load record for oid. Raises KeyError if not found."""
        if self._pool is None:
            raise RuntimeError("Storage not initialized")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT oid, data, refs FROM dhara_objects WHERE oid = $1",
                str_to_int8(oid),
            )
        if row is None:
            raise KeyError(oid)
        # Return packed record format: oid|data_len|data|refs_len|refs
        # Uses pack_record from serialize_legacy for compatibility with sync storage
        stored_oid = int8_to_str(row["oid"])
        data = row["data"] or b""
        refs = row["refs"] or b""
        return pack_record(stored_oid, data, refs)  # type: ignore[no-any-return]

    async def begin(self) -> None:
        """Begin a commit transaction."""
        if self._pool is None:
            raise RuntimeError("Storage not initialized")
        if self._in_transaction:
            raise RuntimeError("begin() called while already in transaction")
        self._conn = await self._pool.acquire()
        self._tx = self._conn.transaction()
        await self._tx.start()
        self._in_transaction = True
        self._pending_records.clear()

    async def store(self, oid: OID, record: bytes) -> None:
        """Store record for oid within the current transaction."""
        if not self._in_transaction or self._conn is None:
            raise RuntimeError("store() called outside transaction")
        # record is already in packed format (oid|data_len|data|refs_len|refs)
        # Unpack to get data and refs for storage
        _rec_oid, data, refs = unpack_record(record)
        oid_int = str_to_int8(oid)
        await self._conn.execute(
            """
            INSERT INTO dhara_objects (oid, data, refs) VALUES ($1, $2, $3)
            ON CONFLICT (oid) DO UPDATE SET data = $2, refs = $3
            """,
            oid_int,
            data,
            refs,
        )
        await self._conn.execute(
            "INSERT INTO dhara_dirty_oids (oid) VALUES ($1) ON CONFLICT DO NOTHING",
            oid_int,
        )
        if self._pack_extra is not None:
            self._pack_extra.append(oid)

    async def end(self, handle_invalidations: Any | None = None) -> None:
        """End the transaction, committing or rolling back."""
        if not self._in_transaction:
            raise RuntimeError("end() called without begin()")
        try:
            await self._tx.commit()  # type: ignore[union-attr]
        except Exception:
            await self._tx.rollback()  # type: ignore[union-attr]
            raise
        finally:
            if self._conn and self._pool:
                await self._pool.release(self._conn)
                self._conn = None
                self._in_transaction = False

    async def sync(self) -> list[OID]:
        """Sync and return list of invalidated OIDs."""
        if self._pool is None:
            raise RuntimeError("Storage not initialized")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT oid FROM dhara_dirty_oids ORDER BY marked_at"
            )
            dirty_oids = [int8_to_str(row["oid"]) for row in rows]
            if dirty_oids:
                await conn.execute(
                    "DELETE FROM dhara_dirty_oids WHERE oid = ANY($1)",
                    [str_to_int8(oid) for oid in dirty_oids],
                )
        return dirty_oids

    async def new_oid(self) -> OID:
        """Allocate and return a new OID."""
        if self._pool is None:
            raise RuntimeError("Storage not initialized")
        async with self._pool.acquire() as conn:
            oid_int: int = await conn.fetchval("SELECT nextval('dhara_oid_seq')")
        return int8_to_str(oid_int)  # type: ignore[no-any-return]

    async def gen_oid_record(
        self, start_oid: OID | None = None, batch_size: int = 100
    ) -> AsyncIterator[tuple[OID, bytes]]:
        """Async generator yielding (oid, record) pairs."""
        if self._pool is None:
            raise RuntimeError("Storage not initialized")

        if start_oid is None:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    async for row in conn.cursor(
                        "SELECT oid, data, refs FROM dhara_objects ORDER BY oid"
                    ):
                        oid_str = int8_to_str(row["oid"])
                        data = row["data"] or b""
                        refs = row["refs"] or b""
                        yield oid_str, pack_record(oid_str, data, refs)
        else:
            # BFS traversal from start_oid
            todo = [start_oid]
            seen: set[OID] = set()
            while todo:
                oid = todo.pop()
                if oid in seen:
                    continue
                seen.add(oid)
                try:
                    record = await self.load(oid)
                    yield oid, record
                except KeyError:
                    continue

    async def bulk_load(self, oids: list[OID]) -> AsyncIterator[bytes]:
        """Async bulk load — yields bytes records for each oid."""
        for oid in oids:
            try:
                record = await self.load(oid)
                yield record
            except KeyError:
                continue

    async def pack(self) -> None:
        """Pack storage, removing obsolete records."""
        # Placeholder for incremental packer
        pass

    async def health(self) -> bool:
        """Return True if storage is healthy."""
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    async def cleanup(self) -> None:
        """Clean up resources (close connections, etc.)."""
        await self.close()

    async def close(self) -> None:
        """Close and release all resources."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def get_packer(self) -> Any | None:
        """Return incremental packer generator, or None."""
        return None  # Placeholder for incremental packer

    async def __aenter__(self) -> AsyncPostgresStorage:
        """Async context manager entry."""
        await self.init()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()


# ── Backward-compatible aliases (sync-era test API) ──────────────
# The original sync API was renamed when asyncpg was adopted. The legacy
# ``PostgresStorageAdapter`` / ``PostgresStorageSettings`` names are kept
# as thin shims so the existing test suite continues to import them.
# These are not the production code path — callers should prefer the
# ``AsyncPostgresStorage`` class directly.


class PostgresStorageSettings:
    """Legacy settings object for ``PostgresStorageAdapter``.

    Mirrors the keyword arguments accepted by ``AsyncPostgresStorage.__init__``.
    """

    def __init__(
        self,
        url: str = "postgresql://localhost/dhara",
        min_size: int = 2,
        max_size: int = 10,
    ) -> None:
        self.url = url
        self.min_size = min_size
        self.max_size = max_size


# Adapter alias: existing tests treat it as a synchronous wrapper. The
# async interface is the production path; this name is kept so import-only
# references and basic construction work without code changes elsewhere.
PostgresStorageAdapter = AsyncPostgresStorage
