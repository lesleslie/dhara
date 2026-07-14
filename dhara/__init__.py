"""
Dhara - Persistent Object Database for Python

Copyright (c) Corporation for National Research Initiatives 2009. All Rights Reserved.
Modernized for Python 3.13+ with Oneiric ecosystem integration.
"""

from __future__ import annotations

import importlib
from importlib.metadata import version as _pkg_version
from typing import Any

try:
    # Read the version from package metadata so it stays in sync with releases.
    # Falls back to a dev sentinel if the package is imported without being
    # installed (e.g. running tests directly from a source checkout).
    __version__ = _pkg_version("dhara")
except Exception:  # pragma: no cover - dev/source-checkout path
    __version__ = "0.0.0+unknown"

# Core persistence framework
from dhara.collections import (
    BNode,
    BTree,
    PersistentDict,
    PersistentList,
    PersistentSet,
)
from dhara.core import Connection, Persistent, PersistentBase

# Errors
from dhara.error import (
    ConflictError,
    DruvaKeyError,
    ReadConflictError,
    WriteConflictError,
)

# Storage server
from dhara.server import StorageServer, wait_for_server

# Storage backends
from dhara.storage import (
    AsyncMemoryStorage,
    AsyncSqliteStorage,
    AsyncStorage,
    ClientStorage,
    FileStorage,
    SqliteStorage,
    Storage,
)

# Utilities
from dhara.utils import (
    as_bytes,
    int4_to_str,
    int8_to_str,
    str_to_int4,
    str_to_int8,
)

__all__ = [
    "__version__",
    "Connection",
    "Persistent",
    "PersistentBase",
    "Storage",
    "AsyncStorage",
    "FileStorage",
    "SqliteStorage",
    "AsyncSqliteStorage",
    "AsyncMemoryStorage",
    "ClientStorage",
    "PersistentDict",
    "PersistentList",
    "PersistentSet",
    "BTree",
    "BNode",
    "StorageServer",
    "wait_for_server",
    "Serializer",
    "SerializerProtocol",
    "MsgspecSerializer",
    "MsgpackSerializer",
    "create_serializer",
    "as_bytes",
    "int8_to_str",
    "int4_to_str",
    "str_to_int8",
    "str_to_int4",
    "ConflictError",
    "ReadConflictError",
    "WriteConflictError",
    "DruvaKeyError",
]


def __getattr__(name: str) -> Any:
    """Resolve serializer symbols lazily to avoid optional dependency coupling."""
    if name in {
        "Serializer",
        "SerializerProtocol",
        "MsgspecSerializer",
        "MsgpackSerializer",
        "create_serializer",
    }:
        module = importlib.import_module("dhara.serialize")
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(globals()))
