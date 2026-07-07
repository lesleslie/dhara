"""
$URL$
$Id$
"""

import heapq
from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING, Any, Protocol

from dhara.core import connection
from dhara.serialize.record import extract_class_name, split_oids, unpack_record
from dhara.utils import int8_to_str

if TYPE_CHECKING:
    pass

# Type alias for Object IDs
OID = str


class Storage:
    """
    This is the interface that Connection requires for Storage.
    """

    def __init__(self) -> None:
        raise RuntimeError("Storage is abstract")

    def load(self, oid: OID) -> bytes:
        """Return the record for this oid.
        Raises a KeyError if there is no such record.
        May also raise a ReadConflictError.
        """
        raise NotImplementedError

    def begin(self) -> None:
        """
        Begin a commit.
        """
        raise NotImplementedError

    def store(self, oid: OID, record: bytes) -> None:
        """Include this record in the commit underway."""
        raise NotImplementedError

    def end(self, handle_invalidations: Any | None = None) -> None:
        """Conclude a commit.
        This may raise a ConflictError.
        """
        raise NotImplementedError

    def sync(self) -> list[OID]:
        """() -> [oid:str]
        Return a list of oids that should be invalidated.
        """
        raise NotImplementedError

    def new_oid(self) -> OID:
        """() -> oid:str
        Return an unused oid.  Used by Connection for serializing new persistent
        instances.
        """
        raise NotImplementedError

    def close(self) -> None:
        """Clean up as needed."""

    def get_packer(self) -> Any | None:
        """
        Return an incremental packer (a generator), or None if this storage
        does not support incremental packing.
        Used by StorageServer.
        """
        return None

    def pack(self) -> Any | None:
        """If this storage supports it, remove obsolete records."""
        return None

    def bulk_load(self, oids: list[OID]) -> Iterator[bytes]:
        """(oids:sequence(oid:str)) -> sequence(record:str)"""
        for oid in oids:
            yield self.load(oid)

    def gen_oid_record(
        self,
        start_oid: OID | None = None,
        batch_size: int = 100,
        **kwargs: Any,
    ) -> Iterator[tuple[OID, bytes]]:
        """(start_oid:str = None, batch_size:int = 100) ->
            sequence((oid:str, record:bytes))
        Returns a generator for the sequence of (oid, record) pairs.

        If a start_oid is given, the resulting sequence follows a
        breadth-first traversal of the object graph, starting at the given
        start_oid.  This uses the storage's bulk_load() method because that
        is faster in some cases.  The batch_size argument sets the number
        of object records loaded on each call to bulk_load().

        If no start_oid is given, the sequence may include oids and records
        that are not reachable from the root.

        Concrete storages may accept additional keyword arguments (e.g.
        ``seen`` for visited-set reuse) via ``**kwargs``; the default
        implementation ignores them.
        """
        if start_oid is None:
            start_oid = connection.ROOT_OID
        # Normalize start_oid to bytes — storages key records by OID bytes.
        if isinstance(start_oid, str):
            start_oid = start_oid.encode("latin1")
        todo: list[OID] = [start_oid]
        seen: set[OID] = set()
        while todo:
            batch: list[OID] = []
            while todo and len(batch) < batch_size:
                oid = heapq.heappop(todo)
                if oid not in seen:
                    batch.append(oid)
                    seen.add(oid)
            for record in self.bulk_load(batch):
                oid_bytes, data, refdata = unpack_record(record)
                # The contract is to yield decoded str OIDs while keeping
                # the internal traversal in bytes (records are bytes-keyed).
                oid_str = (
                    oid_bytes.decode("latin1")
                    if isinstance(oid_bytes, bytes)
                    else oid_bytes
                )
                yield oid_str, record
                for ref in split_oids(refdata):
                    if ref not in seen:
                        heapq.heappush(todo, ref)


def gen_referring_oid_record(
    storage: Storage, referred_oid: OID
) -> Iterator[tuple[OID, bytes]]:
    """(storage:Storage, referred_oid:str) -> sequence([oid:str, record:bytes])
    Generate oid, record pairs for all objects that include a
    reference to the `referred_oid`.

    Note: ``referred_oid`` is converted to bytes for the ``in`` check
    against ``split_oids`` output (8-byte OIDs on the wire).
    """
    referred_oid_bytes = (
        referred_oid.encode("latin1") if isinstance(referred_oid, str) else referred_oid
    )
    for oid, record in storage.gen_oid_record():
        if referred_oid_bytes in split_oids(unpack_record(record)[2]):
            yield oid, record


def gen_oid_class(storage: Storage, *classes: str) -> Iterator[tuple[OID, str]]:
    """(storage:Storage, classes:(str)) ->
        sequence([(oid:str, class_name:str)])
    Generate a sequence of oid, class_name pairs.
    If classes are provided, only output pairs for which the
    class_name is in `classes`.
    """
    for oid, record in storage.gen_oid_record():
        class_name = extract_class_name(record)
        if not classes or class_name in classes:
            yield oid, class_name


def get_census(storage: Storage) -> dict[str, int]:
    """(storage:Storage) -> {class_name:str, instance_count:int}"""
    result: dict[str, int] = {}
    for oid, class_name in gen_oid_class(storage):
        result[class_name] = result.get(class_name, 0) + 1
    return result


def get_reference_index(storage: Storage) -> dict[OID, list[OID]]:
    """(storage:Storage) -> {oid:str : [referring_oid:str]}
    Return a full index giving the referring oids for each oid.
    This might be large.
    """
    result: dict[OID, list[OID]] = {}
    for oid, record in storage.gen_oid_record():
        for ref_bytes in split_oids(unpack_record(record)[2]):
            ref_str = (
                ref_bytes.decode("latin1")
                if isinstance(ref_bytes, bytes)
                else ref_bytes
            )
            result.setdefault(ref_str, []).append(oid)
    return result


class MemoryStorage(Storage):
    """
    A concrete Storage that keeps everything in memory.
    This may be useful for testing purposes.
    """

    def __init__(self) -> None:
        self.records: dict[OID, bytes] = {}
        self.transaction: dict[OID, bytes] | None = None
        self.oid: int = -1

    def new_oid(self) -> OID:
        self.oid += 1
        return int8_to_str(self.oid)  # type: ignore[no-any-return]

    def load(self, oid: OID) -> bytes:
        return self.records[oid]

    def begin(self) -> None:
        self.transaction = {}

    def store(self, oid: OID, record: bytes) -> None:
        assert self.transaction is not None
        self.transaction[oid] = record

    def end(self, handle_invalidations: Any | None = None) -> None:
        assert self.transaction is not None
        self.records.update(self.transaction)
        self.transaction = None

    def sync(self) -> list[OID]:
        return []


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
