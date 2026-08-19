"""
An sqlite-based storage module.  Uses a sqlite as the on-disc storage of
persistent data.

SqliteStorage compares favourably with ShelfStorage for performance,
based on limited tests. The main downside is that it does not
provide point-in-time recovery, easy backups and asynchronous replication.
"""

from __future__ import annotations

import asyncio
import collections
import sqlite3
import struct
import types
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self, cast

import aiosqlite

from dhara.core import connection
from dhara.logger import is_logging, log
from dhara.serialize.record import pack_record, split_oids, unpack_record
from dhara.storage.base import OID, Storage
from dhara.utils import as_bytes, int8_to_str, iteritems, str_to_int8

_DB_SCHEMA = """\
BEGIN TRANSACTION;
CREATE TABLE objects (
    id integer primary key,
    data blob,
    refs blob
    );
COMMIT;
"""

# it is possible that WAL mode is better but for now we leave it as default
_PRAGMAS = """\
PRAGMA journal_mode=WAL;
"""

# Schema for async SQLite storage
_ASYNC_DB_SCHEMA = """\
CREATE TABLE IF NOT EXISTS objects (
    id INTEGER PRIMARY KEY,
    data BLOB,
    refs BLOB
);
"""

# WAL mode pragmas - must be set per-connection
_ASYNC_PRAGMAS = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=5000;
"""


class SqliteStorage(Storage):
    """
    Provides a Sqlite storage backend for Durus.

    Instance attributes:
      _conn: Sqlite connection
      pending_records : [ record:str ]
        Object records are accumulated here during a commit.
      pack_extra : [oid:str] | None
        oids of objects that have been committed after the pack began.  It is
        None if a pack is not in progress.
      invalid : set[str]
        set of oids removed by packs since the last call to sync().
    """

    _PACK_INCREMENT = 100  # number of records to pack before yielding

    def __init__(self, filename, readonly=False, repair=False) -> None:
        if readonly:
            raise NotImplementedError
        self.filename = filename
        if not Path(filename).exists():
            self._init()
        else:
            self._conn = sqlite3.connect(filename)
            self._last_oid = self._get_last_oid()
        self._conn.text_factory = bytes
        # self._conn.executescript(_PRAGMAS)
        self.pending_records = []
        self.pack_extra = None
        self.invalid = set()

    def _commit(self) -> None:
        self._conn.commit()

    def _init(self) -> None:
        self._conn = sqlite3.connect(self.filename)
        c = self._conn.cursor()
        c.executescript(_DB_SCHEMA)
        self._commit()
        self._last_oid = 0

    def get_filename(self) -> str:
        """() -> str
        Returns the full path name of the file that contains the data.
        """
        return self.filename

    def _get_last_oid(self) -> int:
        """() -> int
        Return the highest OID in the database as integer.
        """
        c = self._conn.cursor()
        c.execute("SELECT max(id) FROM objects")
        v = c.fetchone()
        if v is None:
            return 0
        return v[0]

    def load(self, oid: OID) -> bytes:
        """(str) -> bytes
        Return object record identified by 'oid'.
        """
        c = self._conn.cursor()
        c.execute(
            "SELECT id, data, refs FROM objects WHERE id = ?", (str_to_int8(oid),)
        )
        v = c.fetchone()
        if v is None:
            raise KeyError(oid)
        return pack_record(int8_to_str(v[0]), v[1], v[2])

    def begin(self) -> None:
        self.pending_records.clear()

    def store(self, oid, record) -> None:
        """(str, str)"""
        self.pending_records.append(record)

    def _store_records(self, records) -> None:
        def gen_items(records: list[bytes]) -> Iterator[tuple[bytes, bytes, bytes]]:
            for record in records:
                oid, data, refdata = unpack_record(record)
                yield str_to_int8(oid), as_bytes(data), as_bytes(refdata)
                if self.pack_extra is not None:
                    # ensure object and refs are marked alive and not removed
                    self.pack_extra.append(oid)

        c = self._conn.cursor()
        c.executemany(
            "INSERT OR REPLACE INTO objects (id, data, refs) VALUES (?, ?, ?)",
            gen_items(records),
        )
        self._commit()

    def end(self, handle_invalidations=None) -> None:
        self._store_records(self.pending_records)
        if is_logging(20):
            log(20, f"Transaction at [{datetime.now(UTC)}]")
        self.begin()

    def sync(self) -> list[OID]:
        """() -> [str]
        Return a list of oids that should be invalidated.
        """
        result = list(self.invalid)
        self.invalid.clear()
        return result

    def _list_all_oids(self) -> Iterator[OID]:
        c = self._conn.cursor()
        c.execute("SELECT id FROM objects ORDER BY id")
        for (oid,) in c.fetchall():
            yield int8_to_str(oid)

    def _gen_records(self) -> Iterator[tuple[OID, bytes]]:
        c = self._conn.cursor()
        c.execute("SELECT (id, data, refs) FROM objects ORDER BY id")
        for oid, data, refs in c.fetchall():
            yield int8_to_str(oid), pack_record(oid, data, refs)

    def gen_oid_record(
        self,
        start_oid: str | None = None,
        batch_size: int = 100,
        **kwargs: Any,
    ) -> Iterator[tuple[OID, bytes]]:
        if start_oid is None:
            yield from iteritems(self._gen_records())
        else:
            # Normalize to bytes — SQLite stores oid as int8 (8-byte
            # big-endian); ``split_oids`` returns bytes.
            if isinstance(start_oid, str):
                start_oid = start_oid.encode("latin1")  # ty: ignore[invalid-assignment]
            todo: list[bytes] = [start_oid]  # ty: ignore[invalid-assignment]
            seen: set[bytes] = cast(set[bytes], kwargs.get("seen") or set())
            while todo:
                oid = todo.pop()
                if oid in seen:
                    continue
                seen.add(oid)
                record = self.load(oid)  # ty: ignore[invalid-argument-type]
                record_oid, _data, refdata = unpack_record(record)
                assert oid == record_oid
                todo.extend(split_oids(refdata))
                yield oid, record  # ty: ignore[invalid-yield]  # oid is bytes form (preserves runtime semantics; matches base.py pattern)

    def new_oid(self) -> OID:
        oid = int8_to_str(self._last_oid)
        self._last_oid += 1
        return oid

    def is_temporary(self) -> bool:
        return False

    def is_readonly(self) -> bool:
        return False

    def _get_refs(self, oid: OID) -> list[OID]:
        c = self._conn.cursor()
        c.execute("SELECT refs FROM objects WHERE id = ?", (str_to_int8(oid),))
        v = c.fetchone()
        if v is None:
            raise KeyError(oid)
        # ``split_oids`` yields 8-byte OID blobs that are already in the
        # canonical ``bytes`` form expected by the ``OID`` type; pack the
        # ints back to bytes (the prior ``int8_to_str`` call raised a
        # ``struct.error`` because each ``ref`` was already bytes).
        return [bytes(ref) for ref in split_oids(v[0])]

    def _delete(self, oids) -> None:
        def gen_ids() -> Iterator[tuple[bytes]]:
            for oid in oids:
                yield (str_to_int8(oid),)

        c = self._conn.cursor()
        c.executemany("DELETE FROM objects WHERE id = ?", gen_ids())
        self._commit()

    def get_packer(self) -> Any | None:
        if (
            self.pending_records
            or self.pack_extra is not None
            or self.is_temporary()
            or self.is_readonly()
        ):
            return [x for x in ()]  # Don't pack.
        self.pack_extra = []
        alive = set()  # will contain OIDs of all reachable from root

        def packer() -> Iterator[str | None]:
            yield f"started {datetime.now(UTC)}"
            n = 0
            # find all reachable objects.  Note that when we yield, new
            # commits may happen and pack_extra will contain new or modified
            # OIDs.
            pack_todo = collections.deque([connection.ROOT_OID])
            while pack_todo or self.pack_extra:
                if self.pack_extra:
                    oid = self.pack_extra.pop()
                    # note we don't check 'alive' because it could be an
                    # object that got updated since the pack began and in
                    # that case we have to write the new record to the pack
                    # file
                else:
                    oid = pack_todo.popleft()
                    if oid in alive:
                        continue
                alive.add(oid)
                pack_todo.extend(self._get_refs(oid))
                n += 1
                if n % self._PACK_INCREMENT == 0:
                    yield None  # allow server to do other work
            # identified all reachable objects, find dead ones
            # note we cannot yield while iterating over all OIDs because
            # new ones could get created
            dead = set()
            for oid in self._list_all_oids():
                if oid not in alive:
                    dead.add(oid)
            self.pack_extra = None
            # safe to yield now, we have finished identifying dead objects
            yield None
            self._delete(dead)
            yield "finished %s, %d live objects, %d removed" % (  # noqa: UP031
                datetime.now(UTC),
                len(alive),
                len(dead),
            )

        return packer()

    def pack(self) -> Any | None:
        packer = self.get_packer()
        if packer is not None:
            for iteration in packer:
                pass

    def close(self) -> None:
        self._conn.close()

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.get_filename()!r})"

    def create_from_records(self, oid_records) -> None:
        assert self._last_oid == 0, "db not empty"

        def gen_recs(items: list[tuple[OID, bytes]]) -> Iterator[bytes]:
            for oid, record in items:
                yield record

        self._store_records(gen_recs(oid_records))


class AsyncSqliteStorage:
    """Async SQLite storage implementing AsyncStorage protocol.

    Uses aiosqlite for async I/O operations. WAL mode is enabled per
    connection for improved concurrency. Configuration is loaded from
    Oneiric under the ``dhara.storage.sqlite`` namespace.

    Args:
        url: SQLite connection URL. Can be a file path, ``:memory:``,
            or ``sqlite+aiosqlite:///dev/shm/dhara.db`` for dev/shm storage.
        pack_increment: Number of records to pack before yielding (default 100).
    """

    _PACK_INCREMENT = 100  # number of records to pack before yielding

    def __init__(
        self,
        url: str | None = None,
        pack_increment: int = 100,
    ) -> None:
        # Load config from Oneiric if URL not provided
        if url is None:
            # NOTE: The Oneiric class lives at oneiric.core.config.Oneiric; the
            # top-level `oneiric` package only re-exports `DemoAdapter`, so the
            # bare `from oneiric import Oneiric` raises ImportError. Try the
            # canonical path first, then fall back to the symbol at top level.
            try:
                from oneiric.core.config import Oneiric  # type: ignore
            except ImportError:
                try:
                    from oneiric import Oneiric  # type: ignore
                except ImportError:
                    Oneiric = None

            # macOS-friendly default: ~/.local/share/dhara/async.db (resolved
            # at runtime). The previous default `/dev/shm/dhara.db` is
            # Linux-only and breaks on macOS.
            import os

            default_url = "sqlite+aiosqlite://" + os.path.expanduser(
                "~/.local/share/dhara/async.db"
            )

            if Oneiric is not None:
                config = Oneiric.get_config("dhara.storage.sqlite")
                url = config.get("url", default_url)
            else:
                # Oneiric unavailable — use the same macOS-friendly default.
                url = default_url

        # Strip aiosqlite prefix for aiosqlite.connect()
        self._url = url
        if url.startswith("sqlite+aiosqlite://"):
            self._url = url.replace("sqlite+aiosqlite://", "")
        elif url.startswith("sqlite://"):
            self._url = url.replace("sqlite://", "")

        self._conn: aiosqlite.Connection | None = None
        self._last_oid: int = 0
        self._oid_lock: asyncio.Lock = asyncio.Lock()
        self._pack_increment = pack_increment
        self._pending_records: list[tuple[str, bytes]] = []
        self._pack_extra: list[str] | None = None
        self._invalid: set[str] = set()
        self._transaction_open: bool = False

    async def init(self) -> None:
        """Initialize the async SQLite connection."""
        self._conn = await aiosqlite.connect(self._url)
        self._conn.row_factory = aiosqlite.Row
        # Apply WAL mode pragmas
        await self._conn.executescript(_ASYNC_PRAGMAS)
        # Initialize schema
        await self._conn.executescript(_ASYNC_DB_SCHEMA)
        await self._conn.commit()
        # Get the current max OID
        self._last_oid = await self._get_last_oid()

    async def _get_last_oid(self) -> int:
        """Return the highest OID in the database as integer."""
        if self._conn is None:
            return 0
        async with self._conn.execute("SELECT max(id) FROM objects") as cursor:
            row = await cursor.fetchone()
            if row is None or row[0] is None:
                return 0
            return row[0]  # type: ignore[no-any-return]

    async def load(self, oid: str) -> bytes:
        """Load record for oid. Raises KeyError if not found."""
        if self._conn is None:
            raise RuntimeError("Storage not initialized")
        async with self._conn.execute(
            "SELECT id, data, refs FROM objects WHERE id = ?", (str_to_int8(oid),)
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                raise KeyError(oid)
            # Return raw data bytes - the stored record is the data itself
            return row[1] or b""

    def _pack_record(self, oid: str, data: bytes, refs: bytes) -> bytes:
        """Pack oid, data, refs into a record bytes."""
        # All inputs are typed as bytes; encode oid to bytes for length-prefix framing
        oid_bytes = oid.encode("utf-8")
        # data and refs are already bytes (per type annotation)
        data_bytes = data
        refs_bytes = refs
        # Pack as: oid_len(4) | oid | data_len(4) | data | refs_len(4) | refs
        result = (
            struct.pack("<I", len(oid_bytes))
            + oid_bytes
            + struct.pack("<I", len(data_bytes))
            + data_bytes
            + struct.pack("<I", len(refs_bytes))
            + refs_bytes
        )
        return result

    def _unpack_record(self, record: bytes) -> tuple[str, bytes, bytes]:
        """Unpack a record bytes into (oid, data, refs)."""
        pos = 0
        oid_len = struct.unpack("<I", record[pos : pos + 4])[0]
        pos += 4
        oid = record[pos : pos + oid_len].decode()
        pos += oid_len
        data_len = struct.unpack("<I", record[pos : pos + 4])[0]
        pos += 4
        data = record[pos : pos + data_len]
        pos += data_len
        refs_len = struct.unpack("<I", record[pos : pos + 4])[0]
        pos += 4
        refs = record[pos : pos + refs_len]
        return oid, data, refs

    async def begin(self) -> None:
        """Begin a commit transaction."""
        self._pending_records.clear()
        self._transaction_open = True

    async def store(self, oid: str, record: bytes) -> None:
        """Store record for oid within the current transaction."""
        self._pending_records.append((oid, record))

    async def end(self, handle_invalidations: Any | None = None) -> None:
        """End the transaction, committing or rolling back."""
        if self._conn is None:
            raise RuntimeError("Storage not initialized")

        # Store records with their OIDs directly as (id, data, refs) tuples
        # The record passed to store() is raw application data (not packed format)
        def gen_items() -> Iterator[tuple[bytes, bytes, bytes]]:
            for oid, record in self._pending_records:
                oid_int = str_to_int8(oid)
                # record is raw bytes - store as data with empty refs
                yield (oid_int, record, b"")
                if self._pack_extra is not None:
                    self._pack_extra.append(oid)

        await self._conn.executemany(
            "INSERT OR REPLACE INTO objects (id, data, refs) VALUES (?, ?, ?)",
            gen_items(),
        )
        await self._conn.commit()
        self._transaction_open = False

    async def sync(self) -> list[str]:
        """Sync and return list of invalidated OIDs."""
        result = self._invalid.copy()
        self._invalid.clear()
        return list(result)  # type: ignore[return-value]

    async def new_oid(self) -> str:
        """Allocate and return a new OID (thread-safe)."""
        async with self._oid_lock:
            oid = int8_to_str(self._last_oid)
            self._last_oid += 1
            return oid  # type: ignore[no-any-return]

    async def gen_oid_record(
        self, start_oid: str | None = None, batch_size: int = 100
    ) -> AsyncIterator[tuple[str, bytes]]:
        """Async generator yielding (oid, record) pairs."""
        if self._conn is None:
            raise RuntimeError("Storage not initialized")

        if start_oid is None:
            async with self._conn.execute(
                "SELECT id, data, refs FROM objects ORDER BY id"
            ) as cursor:
                async for row in cursor:
                    oid_str = int8_to_str(row[0])
                    # Return raw data bytes as the record
                    yield oid_str, row[1] or b""
        else:
            # BFS traversal from start_oid
            todo = [start_oid]
            seen: set[str] = set()
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

    def _split_oids(self, refs: bytes) -> list[str]:
        """Split refs bytes into list of OID strings."""
        if not refs:
            return []

        result = []
        pos = 0
        while pos < len(refs):
            if pos + 4 > len(refs):
                break
            oid_len = struct.unpack("<I", refs[pos : pos + 4])[0]
            pos += 4
            if pos + oid_len > len(refs):
                break
            oid = refs[pos : pos + oid_len].decode()
            result.append(oid)
            pos += oid_len
        return result

    async def bulk_load(self, oids: list[str]) -> AsyncIterator[bytes]:
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

    async def health(self) -> bool:
        """Return True if storage is healthy."""
        if self._conn is None:
            return False
        try:
            async with self._conn.execute("SELECT 1") as cursor:
                await cursor.fetchone()
            return True
        except sqlite3.Error:
            return False

    async def cleanup(self) -> None:
        """Clean up resources (close connections, etc.)."""
        await self.close()

    async def close(self) -> None:
        """Close and release all resources."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    def get_packer(self) -> Any | None:
        """Return incremental packer generator, or None."""
        return None  # Placeholder for incremental packer

    async def __aenter__(self) -> Self:
        """Async context manager entry."""
        await self.init()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Async context manager exit."""
        await self.close()
