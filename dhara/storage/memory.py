"""
Async in-memory storage implementing AsyncStorage protocol.

This is the async counterpart to the sync MemoryStorage. Since memory
storage has no I/O, all methods are async coroutines that return immediately
without awaiting anything.
"""

from __future__ import annotations

import types
from collections.abc import AsyncIterator
from typing import Any, Self

from dhara.storage.base import OID
from dhara.utils import int8_to_str


class AsyncMemoryStorage:
    """
    Async in-memory storage implementing AsyncStorage protocol.

    State mirrors the sync MemoryStorage:
      records: dict mapping OID to record bytes
      transaction: dict | None (active transaction during commit)
      oid: int (counter for generating new OIDs)

    This may be useful for testing purposes or in-memory caching.
    """

    def __init__(self) -> None:
        self.records: dict[OID, bytes] = {}
        self.transaction: dict[OID, bytes] | None = None
        self.oid: int = -1

    async def init(self) -> None:
        """No-op for memory storage (nothing to initialize)."""

    async def load(self, oid: OID) -> bytes:
        """Return the record for oid. Raises KeyError if missing."""
        return self.records[oid]

    async def begin(self) -> None:
        """Begin a commit transaction."""
        self.transaction = {}

    async def store(self, oid: OID, record: bytes) -> None:
        """Store record for oid within the current transaction."""
        assert self.transaction is not None
        self.transaction[oid] = record

    async def end(self, handle_invalidations: Any | None = None) -> None:
        """End the transaction, committing changes to records."""
        assert self.transaction is not None
        self.records.update(self.transaction)
        self.transaction = None

    async def sync(self) -> list[OID]:
        """Sync and return list of invalidated OIDs (always empty)."""
        return []

    async def new_oid(self) -> OID:
        """Allocate and return a new OID."""
        self.oid += 1
        return int8_to_str(self.oid)  # type: ignore[no-any-return]

    async def gen_oid_record(
        self, start_oid: OID | None = None, batch_size: int = 100
    ) -> AsyncIterator[tuple[OID, bytes]]:
        """Async generator yielding (oid, record) pairs for all records."""
        for oid, record in self.records.items():
            yield oid, record

    async def bulk_load(self, oids: list[OID]) -> AsyncIterator[bytes]:
        """Async bulk load — yields bytes records for each oid."""
        for oid in oids:
            try:
                yield self.records[oid]
            except KeyError:
                continue

    async def pack(self) -> None:
        """No-op for memory storage (no packing needed)."""

    async def health(self) -> bool:
        """Return True (memory storage is always healthy)."""
        return True

    async def cleanup(self) -> None:
        """No-op (nothing to clean up)."""

    async def close(self) -> None:
        """No-op (nothing to close)."""

    def get_packer(self) -> Any | None:
        """Return None (memory storage does not support incremental packing)."""
        return None

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
