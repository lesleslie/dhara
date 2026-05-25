# dhara/storage/postgres.py
from __future__ import annotations

from dataclasses import dataclass

import asyncpg


@dataclass
class PostgresStorageSettings:
    pg_url: str
    pool_min_size: int = 2
    pool_max_size: int = 10

    def __post_init__(self) -> None:
        if not self.pg_url:
            raise ValueError("pg_url is required for PostgresStorageAdapter")


class StorageError(Exception):
    """Raised on storage operation failures."""
    pass


class PostgresStorageAdapter:
    """Postgres-backed storage implementing Dhara's Storage interface.

    Uses asyncpg with a connection pool. Transactions are managed via
    asyncpg transactions. Dirty OID tracking enables sync() to return
    invalidated oids.
    """

    metadata = {"capabilities": ["sql", "pool", "transactions"]}

    def __init__(self, settings: PostgresStorageSettings) -> None:
        self._settings = settings
        self._pool: asyncpg.Pool | None = None
        self._conn: asyncpg.Connection | None = None
        self._in_transaction: bool = False
        self._tx: asyncpg.Transaction | None = None

    async def init(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._settings.pg_url,
            min_size=self._settings.pool_min_size,
            max_size=self._settings.pool_max_size,
            command_timeout=60,
        )

    async def health(self) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    async def cleanup(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def load(self, oid: str) -> bytes:
        if self._pool is None:
            await self.init()
        if self._pool is None:
            raise StorageError("adapter not initialized")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT data FROM dhara_objects WHERE oid = $1", int(oid)
            )
        if row is None:
            raise KeyError(oid)
        return row["data"]

    async def begin(self) -> None:
        if self._pool is None:
            await self.init()
        if self._pool is None:
            raise StorageError("adapter not initialized")
        if self._in_transaction:
            raise RuntimeError("begin() called while already in transaction")
        try:
            self._conn = await self._pool.acquire()
            self._tx = self._conn.transaction()
            await self._tx.start()
            self._in_transaction = True
        except Exception:
            if self._conn and self._pool:
                await self._pool.release(self._conn)
                self._conn = None
            raise

    async def store(self, oid: str, record: bytes) -> None:
        if not self._in_transaction or self._conn is None:
            raise RuntimeError("store() called outside transaction")
        oid_int = int(oid)
        await self._conn.execute(
            """
            INSERT INTO dhara_objects (oid, data) VALUES ($1, $2)
            ON CONFLICT (oid) DO UPDATE SET data = $2
            """,
            oid_int,
            record,
        )
        await self._conn.execute(
            "INSERT INTO dhara_dirty_oids (oid) VALUES ($1) ON CONFLICT DO NOTHING",
            oid_int,
        )

    async def end(self) -> None:
        if not self._in_transaction:
            raise RuntimeError("end() called without begin()")
        tx = self._tx
        assert tx is not None, "tx must not be None when _in_transaction is True"
        try:
            await tx.commit()
        except Exception as e:
            raise StorageError("commit failed") from e
        finally:
            if self._conn and self._pool:
                await self._pool.release(self._conn)
                self._conn = None
            self._in_transaction = False

    async def sync(self) -> list[str]:
        if self._pool is None:
            await self.init()
        if self._pool is None:
            raise StorageError("adapter not initialized")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT oid FROM dhara_dirty_oids ORDER BY marked_at"
            )
            dirty_oids = [str(row["oid"]) for row in rows]
            if dirty_oids:
                await conn.execute(
                    "DELETE FROM dhara_dirty_oids WHERE oid = ANY($1)",
                    [int(oid) for oid in dirty_oids],
                )
        return dirty_oids

    async def new_oid(self) -> str:
        if self._pool is None:
            await self.init()
        if self._pool is None:
            raise StorageError("adapter not initialized")
        async with self._pool.acquire() as conn:
            oid_int: int = await conn.fetchval("SELECT nextval('dhara_oid_seq')")
        return str(oid_int)

    async def close(self) -> None:
        await self.cleanup()

    async def _rollback(self) -> None:
        """Rollback the current transaction. Used by abort path."""
        if self._in_transaction and self._tx:
            try:
                await self._tx.rollback()
            except Exception:
                pass
        if self._conn and self._pool:
            await self._pool.release(self._conn)
        self._conn = None
        self._in_transaction = False