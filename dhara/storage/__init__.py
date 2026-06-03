"""Storage backends for Durus.

Provides adapter pattern for multiple storage implementations:
- base: Abstract Storage interface
- file: FileStorage (default Durus file-based storage)
- sqlite: SQLite storage backend
- client: ClientStorage (network client to storage server)
- memory: MemoryStorage (in-memory for testing)
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
from dhara.storage.file import FileStorage
from dhara.storage.memory import AsyncMemoryStorage

try:
    from dhara.storage.sqlite import AsyncSqliteStorage, SqliteStorage
except ImportError:
    AsyncSqliteStorage = SqliteStorage = None  # type: ignore[misc,assignment]

__all__ = [
    "Storage",
    "MemoryStorage",
    "AsyncStorage",
    "FileStorage",
    "SqliteStorage",
    "AsyncSqliteStorage",
    "AsyncMemoryStorage",
    "ClientStorage",
    "gen_referring_oid_record",
    "get_census",
    "get_reference_index",
]
