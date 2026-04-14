"""Serialization layer for Durus.

Provides multiple serialization backends:
- msgspec: Fast, type-safe, secure (recommended for dhara 5.0)
- pickle: Backward compatibility with Durus 4.x (use with caution)
- dill: Extended capability for lambdas and nested functions (use with caution)
- fallback: Whitelist-based auto-fallback (msgspec → pickle → dill)
- adapter: Bridge between old and new serialization code
- factory: Easy creation of serializer instances
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

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
from dhara.serialize.factory import create_serializer

if TYPE_CHECKING:
    from dhara.serialize.dill import DillSerializer
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
    # Default implementation alias
    "DEFAULT_SERIALIZER",
]


def __getattr__(name: str) -> Any:
    """Resolve optional serializer backends lazily."""
    module_map = {
        "MsgspecSerializer": ("dhara.serialize.msgspec", "MsgspecSerializer"),
        "PickleSerializer": ("dhara.serialize.pickle", "PickleSerializer"),
        "DillSerializer": ("dhara.serialize.dill", "DillSerializer"),
        "FallbackSerializer": ("dhara.serialize.fallback", "FallbackSerializer"),
        "DEFAULT_SERIALIZER": ("dhara.serialize.msgspec", "MsgspecSerializer"),
    }

    target = module_map.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = target
    module = importlib.import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(globals()))
