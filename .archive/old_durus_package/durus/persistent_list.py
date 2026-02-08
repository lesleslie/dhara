"""Compatibility shim for durus.persistent_list

Redirects imports to new location (durus.collections.list)
for backward compatibility with pickled data from Durus 4.x.
"""

from dhruva.collections.list import *

__all__ = ['PersistentList']
