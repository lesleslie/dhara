"""Storage backends for Durus.

Provides adapter pattern for multiple storage implementations:
- base: Abstract Storage interface
- file: FileStorage (default Durus file-based storage)
- sqlite: SQLite storage backend
- client: ClientStorage (network client to storage server)
- memory: MemoryStorage (in-memory for testing)
"""

from dhruva.storage.base import Storage, MemoryStorage, gen_referring_oid_record, get_census, get_reference_index
from dhruva.storage.file import FileStorage
from dhruva.storage.sqlite import SqliteStorage
from dhruva.storage.client import ClientStorage

__all__ = [
    'Storage',
    'MemoryStorage',
    'FileStorage',
    'SqliteStorage',
    'ClientStorage',
    'gen_referring_oid_record',
    'get_census',
    'get_reference_index',
]
