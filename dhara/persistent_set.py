"""Compatibility shim for durus.persistent_set

Redirects imports to new location (durus.collections.set)
for backward compatibility with pickled data from Durus 4.x.
"""

from dhara.collections.set import PersistentSet

__all__ = ["PersistentSet"]
