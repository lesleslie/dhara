"""Serialization layer for Dhara.

Provides multiple serialization backends:
- msgspec: Fast, type-safe, secure (recommended for new code)
- msgpack: Historical alias for msgspec-format serialization

The legacy pickle, dill, and FallbackSerializer backends are removed as
of 0.11.0 — the CWE-502 migration has been completed. DFS20 / Durus
4.x pickle-format databases are no longer supported; use the SHELF-1
storage format for new and migrated databases.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from dhara.serialize.base import Serializer, SerializerProtocol
from dhara.serialize.factory import create_serializer
from dhara.serialize.record import (
    ObjectReader,
    ObjectWriter,
    extract_class_name,
    pack_record,
    persistent_load,
    split_oids,
    unpack_record,
)

if TYPE_CHECKING:
    from dhara.serialize.msgpack import MsgpackSerializer
    from dhara.serialize.msgspec import MsgspecSerializer

__all__ = [
    # Interfaces
    "Serializer",
    "SerializerProtocol",
    # Implementations
    "MsgspecSerializer",
    "MsgpackSerializer",
    # Factory
    "create_serializer",
    # Record format helpers
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
        "MsgpackSerializer": ("dhara.serialize.msgpack", "MsgpackSerializer"),
        "DEFAULT_SERIALIZER": ("dhara.serialize.msgspec", "MsgspecSerializer"),
        # ObjectReader/ObjectWriter live in dhare.serialize.record (not lazy —
        # they are always available since record.py is imported above). Listed
        # here only for compatibility with code that resolves them through
        # the lazy map.
        "ObjectReader": ("dhara.serialize.record", "ObjectReader"),
        "ObjectWriter": ("dhara.serialize.record", "ObjectWriter"),
    }

    target = module_map.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = target
    # nosem: python.lang.security.audit.non-literal-import.non-literal-import
    module = importlib.import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(globals()))
