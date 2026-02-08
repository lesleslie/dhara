"""Core persistence framework.

This module contains the fundamental persistence abstractions:
- Connection: Transaction and object cache management
- Persistent: Base classes for persistent objects
- State: Object state machine (GHOST, SAVED, UNSAVED)
- Cache: LRU cache for loaded objects
"""

from dhruva.core.connection import Connection, ROOT_OID, ObjectDictionary, touch_every_reference
from dhruva.core.persistent import Persistent, PersistentBase

__all__ = [
    'Connection',
    'Persistent',
    'PersistentBase',
    'ROOT_OID',
    'ObjectDictionary',
    'touch_every_reference',
]
