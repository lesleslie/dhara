"""Compatibility shim for durus.storage_server

Redirects imports to new location (durus.server.server)
for backward compatibility with Durus 4.x.
"""

from dhara.server.server import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    StorageServer,
    wait_for_server,
)

__all__ = ["StorageServer", "wait_for_server", "DEFAULT_HOST", "DEFAULT_PORT"]
