"""Compatibility shim for durus.btree

Redirects imports to new location (durus.collections.btree)
for backward compatibility with pickled data from Durus 4.x.
"""

from dhruva.collections.btree import *

__all__ = ["BTree", "BNode"]
