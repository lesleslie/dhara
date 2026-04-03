"""Serialization layer for Durus.

Provides multiple serialization backends:
- msgspec: Fast, type-safe, secure (recommended for dhara 5.0)
- pickle: Backward compatibility with Durus 4.x (use with caution)
- dill: Extended capability for lambdas and nested functions (use with caution)
- fallback: Whitelist-based auto-fallback (msgspec → pickle → dill)
- adapter: Bridge between old and new serialization code
- factory: Easy creation of serializer instances

Security Recommendations:
- Use msgspec for new databases (safest and fastest)
- Use fallback for mixed workloads with some msgspec-incompatible types
- Use pickle only for backward compatibility
- Use dill only when you need to serialize functions/lambdas
- Never deserialize untrusted data with pickle or dill
"""

from dhara.serialize.adapter import (
    ObjectReader,
    ObjectWriter,
    extract_class_name,
    pack_record,
    persistent_load,
    split_oids,
    unpack_record,
)
from dhara.serialize.base import Serializer, SerializerProtocol
from dhara.serialize.dill import DillSerializer
from dhara.serialize.factory import create_serializer
from dhara.serialize.fallback import FallbackSerializer
from dhara.serialize.msgspec import MsgspecSerializer
from dhara.serialize.pickle import PickleSerializer

__all__ = [
    # Interfaces
    "Serializer",
    "SerializerProtocol",
    # Implementations
    "MsgspecSerializer",
    "PickleSerializer",
    "DillSerializer",
    "FallbackSerializer",
    # Factory
    "create_serializer",
    # Adapters (backward compatibility)
    "ObjectReader",
    "ObjectWriter",
    "pack_record",
    "unpack_record",
    "split_oids",
    "persistent_load",
    "extract_class_name",
]

# Default serializer for dhara 5.0
DEFAULT_SERIALIZER = MsgspecSerializer
