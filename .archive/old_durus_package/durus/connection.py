"""Compatibility shim for durus.connection

Redirects imports to new location (durus.core.connection)
for backward compatibility with pickled data from Durus 4.x.
"""

from druva.core.connection import *

__all__ = ['Connection', 'ROOT_OID']
