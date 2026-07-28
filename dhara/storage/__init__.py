"""Storage backends for Durus.

Provides adapter pattern for multiple storage implementations:
- base: Abstract Storage interface
- sqlite: SQLite storage backend (sync and async variants)
- client: ClientStorage (network client to storage server)
- memory: MemoryStorage (in-memory for testing)

The legacy ``FileStorage`` (Durus SHELF) backend was removed in the
async-migration cleanup — use ``AsyncFileStorage`` (a thin
``AsyncSqliteStorage`` alias) for path-based file storage.
"""

from dhara.storage.base import (
    AsyncStorage,
    MemoryStorage,
    Storage,
    gen_referring_oid_record,
    get_census,
    get_reference_index,
)
from dhara.storage.client import ClientStorage
from dhara.storage.memory import AsyncMemoryStorage

try:
    from dhara.storage.sqlite import AsyncSqliteStorage, SqliteStorage
except ImportError:
    AsyncSqliteStorage: type | None = None  # type: ignore[no-redef]
    SqliteStorage: type | None = None  # type: ignore[no-redef]

__all__ = [
    "AsyncMemoryStorage",
    "AsyncSqliteStorage",
    "AsyncStorage",
    "ClientStorage",
    "MemoryStorage",
    "SqliteStorage",
    "Storage",
    "gen_referring_oid_record",
    "get_census",
    "get_reference_index",
]
