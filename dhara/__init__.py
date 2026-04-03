"""
Durus - Persistent Object Database for Python

Copyright (c) Corporation for National Research Initiatives 2009. All Rights Reserved.
Modernized for Python 3.13+ with Oneiric ecosystem integration.
"""

__version__ = "0.5.0"

# Import backward compatibility for Durus 4.x databases
from dhara import _compat  # noqa: F401 (side-effect imports for compat)

# Core persistence framework
# Persistent collections
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

# Serialization
from dhara.serialize import MsgspecSerializer, PickleSerializer, Serializer

# Storage server
from dhara.server import StorageServer, wait_for_server

# Storage backends
from dhara.storage import ClientStorage, FileStorage, SqliteStorage, Storage

# Utilities
from dhara.utils import (
    as_bytes,
    int4_to_str,
    int8_to_str,
    str_to_int4,
    str_to_int8,
)

__all__ = [
    # Version
    "__version__",
    # Core
    "Connection",
    "Persistent",
    "PersistentBase",
    # Storage
    "Storage",
    "FileStorage",
    "SqliteStorage",
    "ClientStorage",
    # Collections
    "PersistentDict",
    "PersistentList",
    "PersistentSet",
    "BTree",
    "BNode",
    # Server
    "StorageServer",
    "wait_for_server",
    # Serialization
    "Serializer",
    "MsgspecSerializer",
    "PickleSerializer",
    # Utilities
    "as_bytes",
    "int8_to_str",
    "int4_to_str",
    "str_to_int8",
    "str_to_int4",
    # Errors
    "ConflictError",
    "ReadConflictError",
    "WriteConflictError",
    "DruvaKeyError",
]
