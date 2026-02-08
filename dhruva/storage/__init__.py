"""Storage backends for Durus.

Provides adapter pattern for multiple storage implementations:
- base: Abstract Storage interface
- file: FileStorage (default Durus file-based storage)
- sqlite: SQLite storage backend
- client: ClientStorage (network client to storage server)
- memory: MemoryStorage (in-memory for testing)
"""

from dhruva.storage.base import (
    MemoryStorage,
    Storage,
    gen_referring_oid_record,
    get_census,
    get_reference_index,
)
from dhruva.storage.client import ClientStorage
from dhruva.storage.file import FileStorage
from dhruva.storage.sqlite import SqliteStorage

__all__ = [
    "Storage",
    "MemoryStorage",
    "FileStorage",
    "SqliteStorage",
    "ClientStorage",
    "gen_referring_oid_record",
    "get_census",
    "get_reference_index",
]
