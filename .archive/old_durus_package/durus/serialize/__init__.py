"""Serialization layer for Durus.

Provides multiple serialization backends:
- msgspec: Fast, type-safe, secure (recommended for Durus 5.0)
- pickle: Backward compatibility with Durus 4.x (use with caution)
- dill: Extended capability for lambdas and nested functions (use with caution)
- adapter: Bridge between old and new serialization code
- factory: Easy creation of serializer instances

Security Recommendations:
- Use msgspec for new databases (safest and fastest)
- Use pickle only for backward compatibility
- Use dill only when you need to serialize functions/lambdas
- Never deserialize untrusted data with pickle or dill
"""

from druva.serialize.base import Serializer, SerializerProtocol
from druva.serialize.msgspec import MsgspecSerializer
from druva.serialize.pickle import PickleSerializer
from druva.serialize.dill import DillSerializer
from druva.serialize.factory import create_serializer
from druva.serialize.adapter import (
    ObjectReader,
    ObjectWriter,
    pack_record,
    unpack_record,
    split_oids,
    persistent_load,
    extract_class_name,
)

__all__ = [
    # Interfaces
    'Serializer',
    'SerializerProtocol',
    # Implementations
    'MsgspecSerializer',
    'PickleSerializer',
    'DillSerializer',
    # Factory
    'create_serializer',
    # Adapters (backward compatibility)
    'ObjectReader',
    'ObjectWriter',
    'pack_record',
    'unpack_record',
    'split_oids',
    'persistent_load',
    'extract_class_name',
]

# Default serializer for Durus 5.0
DEFAULT_SERIALIZER = MsgspecSerializer
