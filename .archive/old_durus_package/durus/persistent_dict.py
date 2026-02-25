"""Compatibility shim for durus.persistent_dict

Redirects imports to new location (durus.collections.dict)
for backward compatibility with pickled data from Durus 4.x.
"""

# Import everything from new location and re-export
from druva.collections.dict import *

# Re-export all public classes and functions
__all__ = ['PersistentDict']
