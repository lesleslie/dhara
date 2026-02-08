"""
Durus - Persistent Object Database for Python

Copyright (c) Corporation for National Research Initiatives 2009. All Rights Reserved.
Modernized for Python 3.13+ with Oneiric ecosystem integration.
"""

__version__ = "5.0.0"

# Core persistence framework
from dhruva.core import Connection, Persistent, PersistentBase

# Storage backends
from dhruva.storage import Storage, FileStorage, SqliteStorage, ClientStorage

# Persistent collections
from dhruva.collections import (
    PersistentDict,
    PersistentList,
    PersistentSet,
    BTree,
    BNode,
)

# Storage server
from dhruva.server import StorageServer, wait_for_server

# Serialization
from dhruva.serialize import Serializer, MsgspecSerializer, PickleSerializer

# Utilities
from dhruva.utils import (
    as_bytes,
    int8_to_str,
    int4_to_str,
    str_to_int8,
    str_to_int4,
)

# Errors
from dhruva.error import (
    ConflictError,
    ReadConflictError,
    WriteConflictError,
    DurusKeyError,
)

__all__ = [
    # Version
    '__version__',
    # Core
    'Connection',
    'Persistent',
    'PersistentBase',
    # Storage
    'Storage',
    'FileStorage',
    'SqliteStorage',
    'ClientStorage',
    # Collections
    'PersistentDict',
    'PersistentList',
    'PersistentSet',
    'BTree',
    'BNode',
    # Server
    'StorageServer',
    'wait_for_server',
    # Serialization
    'Serializer',
    'MsgspecSerializer',
    'PickleSerializer',
    # Utilities
    'as_bytes',
    'int8_to_str',
    'int4_to_str',
    'str_to_int8',
    'str_to_int4',
    # Errors
    'ConflictError',
    'ReadConflictError',
    'WriteConflictError',
    'DurusKeyError',
]
