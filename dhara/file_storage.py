"""Compatibility shim for durus.file_storage

Redirects imports to new location (durus.storage.file)
for backward compatibility with pickled data from Durus 4.x.
"""

from dhara.storage.file import *

__all__ = ["FileStorage"]
