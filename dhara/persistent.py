"""Compatibility shim for durus.persistent

Redirects imports to new location (durus.core.persistent)
for backward compatibility with pickled data from Durus 4.x.
"""

from dhara.core.persistent import *

__all__ = ["Persistent", "PersistentBase", "ConnectionBase"]
