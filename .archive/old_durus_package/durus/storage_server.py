"""Compatibility shim for durus.storage_server

Redirects imports to new location (durus.server.server)
for backward compatibility with Durus 4.x.
"""

from druva.server.server import *

__all__ = ['StorageServer', 'wait_for_server', 'DEFAULT_HOST', 'DEFAULT_PORT']
