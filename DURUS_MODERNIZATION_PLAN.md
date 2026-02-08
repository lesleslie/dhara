# Durus Modernization & Refactoring Plan

## Overview

Modernize the Durus persistent object database codebase with a complete architectural refactoring. This plan addresses structural issues, adds modern Python features, and integrates with the Mahavishnu ecosystem.

**Current State:**
- 20 Python files in flat `durus/` package (~5,573 lines)
- Outdated patterns: `optparse`, `pickle` protocol 2, no type hints
- Mixed concerns throughout codebase
- No configuration management or structured logging
- No validation layer or modern patterns

**Target State:**
- Modern package structure with clear separation of concerns
- Type hints throughout (Python 3.13+)
- Modern serialization with msgspec, dill, and pickle options
- Oneiric integration for config, logging, and CLI
- Pydantic validation layer
- **NO backward compatibility** - clean break from old API
- Mahavishnu ecosystem integration

---

## Phase 1: Structural Reorganization (Weeks 1-2)

### 1.1 New Package Structure

**Current Structure (Flat):**
```
durus/
├── __init__.py
├── connection.py (530 lines)
├── storage.py (182 lines)
├── serialize.py (242 lines)
├── persistent.py (282 lines)
├── utils.py (568 lines)
├── __main__.py (441 lines)
├── storage_server.py (526 lines)
├── file_storage.py (196 lines)
├── file_storage2.py (360 lines)
├── sqlite_storage.py (272 lines)
├── client_storage.py (154 lines)
├── persistent_dict.py (131 lines)
├── persistent_list.py (150 lines)
├── persistent_set.py (189 lines)
├── btree.py (593 lines)
├── shelf.py (442 lines)
├── file.py (148 lines)
├── logger.py (basic)
├── error.py (59 lines)
└── systemd_socket.py (66 lines)
```

**New Structure (Layered):**
```
durus/
├── __init__.py                   # Public API exports
├── __main__.py                   # CLI entry point (typer)
│
├── core/                         # Core persistence framework
│   ├── __init__.py
│   ├── connection.py             # Connection management
│   ├── persistent.py             # Persistent base classes
│   ├── state.py                  # Object state management
│   └── cache.py                  # Caching logic
│
├── storage/                      # Storage backends (adapter pattern)
│   ├── __init__.py
│   ├── base.py                   # Abstract Storage interface
│   ├── file.py                   # FileStorage
│   ├── sqlite.py                 # SQLite storage
│   ├── client.py                 # ClientStorage
│   └── memory.py                 # MemoryStorage (extract from storage.py)
│
├── serialize/                    # Serialization layer (adapter pattern)
│   ├── __init__.py
│   ├── base.py                   # Serializer interface
│   ├── pickle.py                 # Pickle implementation (backward compat)
│   ├── msgspec.py                # msgspec implementation
│   └── signing.py                # HMAC signing wrapper
│
├── collections/                  # Persistent collection types
│   ├── __init__.py
│   ├── dict.py                   # PersistentDict
│   ├── list.py                   # PersistentList
│   ├── set.py                    # PersistentSet
│   └── btree.py                  # BTree
│
├── server/                       # Server components
│   ├── __init__.py
│   ├── server.py                 # StorageServer
│   ├── socket.py                 # Socket management
│   └── protocol.py               # Client/server protocol
│
├── cli/                          # CLI commands (typer)
│   ├── __init__.py
│   ├── server.py                 # Server commands
│   ├── client.py                 # Client commands
│   ├── shell.py                  # Interactive shell
│   └── admin.py                  # Admin commands (Oneiric)
│
├── utils/                        # Utilities
│   ├── __init__.py
│   ├── types.py                  # Common types
│   ├── formats.py                # Format conversions
│   └── helpers.py                # Helper functions
│
├── config/                       # Configuration (Oneiric)
│   ├── __init__.py
│   ├── defaults.py               # Default config
│   └── loader.py                 # Config loader
│
├── logging/                      # Logging (Oneiric)
│   ├── __init__.py
│   └── logger.py                 # Structured logger
│
├── validation/                   # Validation layer
│   ├── __init__.py
│   ├── models.py                 # Pydantic models
│   └── validators.py             # Custom validators
│
├── compatibility/                # Compatibility layers
│   ├── __init__.py
│   ├── zodb.py                   # ZODB compatibility
│   └── legacy.py                 # Legacy API support
│
└── errors/                       # Error handling
    ├── __init__.py
    ├── exceptions.py             # Exception classes
    └── handlers.py               # Error handlers
```

### 1.2 Implementation Steps

**Step 1: Create new directory structure**
```bash
mkdir -p durus/{core,storage,serialize,collections,server,cli,utils,config,logging,validation,compatibility,errors}
```

**Step 2: Move and rename files**
- Move `connection.py` → `core/connection.py`
- Move `persistent.py` → `core/persistent.py`
- Move `storage.py` → `storage/base.py`
- Move `file_storage.py` → `storage/file.py`
- Move `sqlite_storage.py` → `storage/sqlite.py`
- Move `client_storage.py` → `storage/client.py`
- Move `serialize.py` → `serialize/pickle.py`
- Move `persistent_dict.py` → `collections/dict.py`
- Move `persistent_list.py` → `collections/list.py`
- Move `persistent_set.py` → `collections/set.py`
- Move `btree.py` → `collections/btree.py`
- Move `storage_server.py` → `server/server.py`
- Move `systemd_socket.py` → `server/socket.py`
- Move `__main__.py` (refactor into `cli/`)
- Move `logger.py` → `logging/logger.py`
- Move `error.py` → `errors/exceptions.py`
- Move `utils.py` → `utils/helpers.py`
- Move `file.py` → `utils/formats.py`

**Step 3: Update all imports**
- Update internal imports to use new structure
- Update test imports
- Update documentation

**Step 4: Add `__init__.py` files**
- Each subdirectory gets an `__init__.py`
- Export public APIs at each level
- Maintain backward compatibility via re-exports in root `__init__.py`

### 1.3 Critical Files for Updates

| File | Lines | Complexity | Priority |
|------|-------|------------|----------|
| `durus/__init__.py` | NEW | Medium | HIGH |
| `durus/core/__init__.py` | NEW | Low | HIGH |
| `durus/storage/__init__.py` | NEW | Low | HIGH |
| `durus/serialize/__init__.py` | NEW | Medium | HIGH |
| All files with imports | ~20 | High | HIGH |

---

## Phase 2: Type Hints & Modern Python (Weeks 3-4)

### 2.1 Add Type Hints

**Priority Files:**
1. `core/connection.py` (530 lines) - Core transaction management
2. `core/persistent.py` (282 lines) - Base classes
3. `storage/base.py` (182 lines) - Storage interface
4. `serialize/pickle.py` (242 lines) - Serialization
5. `collections/btree.py` (593 lines) - Complex data structure

**Type Hint Strategy:**
```python
# Before
class Connection:
    def __init__(self, storage, cache_size=100000, root_class=None):
        self.storage = storage
        self.cache = Cache(cache_size)

# After
from typing import Any, Protocol, Type, TypeVar, Union
from durus.storage.base import Storage

T = TypeVar('T', bound='Persistent')

class Connection:
    def __init__(
        self,
        storage: Storage,
        cache_size: int = 100000,
        root_class: Type[T] | None = None,
    ) -> None:
        self.storage: Storage = storage
        self.cache: Cache = Cache(cache_size)

    def get(self, oid: str | int, klass: Type[T] | None = None) -> T | None: ...
    def get_root(self) -> PersistentDict: ...
    def commit(self) -> None: ...
    def abort(self) -> None: ...
```

### 2.2 Add Protocols for Interfaces

**Storage Protocol:**
```python
# storage/protocol.py
from typing import Protocol, Iterator, Generator

class Storage(Protocol):
    """Protocol for storage backends."""

    def load(self, oid: str) -> bytes: ...

    def store(self, oid: str, record: bytes) -> None: ...

    def begin(self) -> None: ...

    def end(self, handle_invalidations: Callable | None = None) -> list[str]: ...

    def sync(self) -> list[str]: ...

    def new_oid(self) -> str: ...

    def close(self) -> None: ...

    def gen_oid_record(
        self,
        start_oid: str | None = None,
        batch_size: int = 100,
    ) -> Iterator[tuple[str, bytes]]: ...
```

### 2.3 Critical Type-annotated Files

| File | Est. Effort | Impact |
|------|-------------|--------|
| `core/connection.py` | 2 days | High - core API |
| `core/persistent.py` | 1 day | High - base classes |
| `storage/base.py` | 1 day | High - interface |
| `serialize/base.py` | 1 day | Medium - new abstraction |
| `collections/btree.py` | 2 days | Medium - complex structure |

---

## Phase 3: Oneiric Integration (Weeks 5-6)

### 3.1 Configuration Management

**Create `config/defaults.py`:**
```python
from oneiric import Config, Field

class DurusConfig(Config):
    """Durus configuration."""

    storage: StorageConfig = Field(
        default_factory=StorageConfig,
        description="Storage backend configuration",
    )

    cache: CacheConfig = Field(
        default_factory=CacheConfig,
        description="Cache settings",
    )

    logging: LoggingConfig = Field(
        default_factory=LoggingConfig,
        description="Logging configuration",
    )

    security: SecurityConfig = Field(
        default_factory=SecurityConfig,
        description="Security settings",
    )

class StorageConfig(Config):
    backend: str = Field(
        default="file",
        description="Storage backend: file, sqlite, client, memory",
    )
    path: str | None = Field(
        default=None,
        description="Path to file storage",
    )
    host: str = Field(
        default="localhost",
        description="Server host (for client storage)",
    )
    port: int = Field(
        default=2972,
        description="Server port (for client storage)",
    )

class CacheConfig(Config):
    size: int = Field(
        default=100000,
        description="Maximum number of objects in cache",
    )

class LoggingConfig(Config):
    level: str = Field(
        default="INFO",
        description="Log level: DEBUG, INFO, WARNING, ERROR",
    )
    format: str = Field(
        default="json",
        description="Log format: json, text",
    )

class SecurityConfig(Config):
    sign_objects: bool = Field(
        default=False,
        description="Enable HMAC signing of serialized objects",
    )
    secret_key: str | None = Field(
        default=None,
        description="Secret key for signing (from env if not set)",
    )
```

**Configuration file example:**
```yaml
# durus.yaml
storage:
  backend: file
  path: /var/lib/durus/data.durus

cache:
  size: 100000

logging:
  level: INFO
  format: json
  outputs:
    - type: stdout
      level: INFO
    - type: file
      path: /var/log/durus/durus.log
      level: DEBUG

security:
  sign_objects: true
  secret_key_env: DURUS_SECRET_KEY
```

### 3.2 Structured Logging

**Create `logging/logger.py`:**
```python
from oneiric import get_logger

logger = get_logger(__name__)

def get_connection_logger(connection_id: str):
    """Get a logger with connection context."""
    return logger.bind(
        component="connection",
        connection_id=connection_id,
    )

def get_storage_logger(backend: str, path: str):
    """Get a logger with storage context."""
    return logger.bind(
        component="storage",
        backend=backend,
        path=path,
    )
```

### 3.3 Modern CLI with Typer

**Create `cli/__init__.py`:**
```python
import typer
from oneiric import load_config

app = typer.Typer(
    name="durus",
    help="Durus persistent object database",
    add_completion=True,
)

@app.command()
def server(
    config_file: str = typer.Option(
        "durus.yaml",
        "--config", "-c",
        help="Configuration file path",
    ),
    port: int = typer.Option(
        None,
        "--port", "-p",
        help="Override server port",
    ),
):
    """Start Durus storage server."""
    config = load_config(config_file)
    if port:
        config.storage.port = port

    from durus.server.server import StorageServer
    server = StorageServer.from_config(config)
    server.start()

@app.command()
def client(
    config_file: str = typer.Option(
        "durus.yaml",
        "--config", "-c",
        help="Configuration file path",
    ),
):
    """Start Durus client shell."""
    config = load_config(config_file)

    from durus.cli.shell import interactive_shell
    interactive_shell(config)

@app.command()
def admin(
    config_file: str = typer.Option(
        "durus.yaml",
        "--config", "-c",
        help="Configuration file path",
    ),
):
    """Start Durus admin shell (Oneiric)."""
    config = load_config(config_file)

    from durus.cli.admin import admin_shell
    admin_shell(config)
```

### 3.4 Critical Files for Oneiric

| File | Type | Priority |
|------|------|----------|
| `config/defaults.py` | NEW | HIGH |
| `config/loader.py` | NEW | HIGH |
| `logging/logger.py` | NEW | HIGH |
| `cli/__init__.py` | NEW | HIGH |
| `cli/server.py` | NEW | MEDIUM |
| `cli/client.py` | NEW | MEDIUM |
| `cli/shell.py` | NEW | MEDIUM |
| `cli/admin.py` | NEW | LOW |

---

## Phase 4: Serialization Modernization (Weeks 7-8)

### 4.1 Serializer Adapter Pattern

**Create `serialize/base.py`:**
```python
from abc import ABC, abstractmethod
from typing import Any

class Serializer(ABC):
    """Abstract serializer interface."""

    @abstractmethod
    def serialize(self, obj: Any) -> bytes:
        """Serialize object to bytes."""
        pass

    @abstractmethod
    def deserialize(self, data: bytes) -> Any:
        """Deserialize bytes to object."""
        pass

    @abstractmethod
    def get_state(self, obj: Persistent) -> dict:
        """Extract serializable state from object."""
        pass
```

**Create `serialize/pickle.py`:**
```python
import pickle
from durus.serialize.base import Serializer

class PickleSerializer(Serializer):
    """Pickle-based serializer (backward compatible)."""

    def __init__(self, protocol: int = 2):
        self.protocol = protocol

    def serialize(self, obj: Any) -> bytes:
        return pickle.dumps(obj, protocol=self.protocol)

    def deserialize(self, data: bytes) -> Any:
        return pickle.loads(data)

    def get_state(self, obj: Persistent) -> dict:
        return obj.__getstate__()
```

**Create `serialize/msgspec.py`:**
```python
import msgspec
from durus.serialize.base import Serializer

class MsgspecSerializer(Serializer):
    """msgspec-based serializer (faster, safer)."""

    def __init__(self, use_json: bool = False):
        self.use_json = use_json
        if use_json:
            self.encoder = msgspec.json.Encoder()
            self.decoder = msgspec.json.Decoder(type=Any)
        else:
            self.encoder = msgspec.msgpack.Encoder()
            self.decoder = msgspec.msgpack.Decoder(type=Any)

    def serialize(self, obj: Any) -> bytes:
        return self.encoder.encode(obj)

    def deserialize(self, data: bytes) -> Any:
        return self.decoder.decode(data)

    def get_state(self, obj: Persistent) -> dict:
        # Extract state compatible with msgspec
        return obj.__getstate__()
```

**Create `serialize/dill.py`:**
```python
import dill
from durus.serialize.base import Serializer

class DillSerializer(Serializer):
    """dill-based serializer (more capable than pickle).

    Advantages over pickle:
    - Can serialize more object types (lambdas, nested functions, etc.)
    - Better handling of interactive sessions
    - Supports interactive interpreter objects

    Trade-offs:
    - Slightly slower than msgspec
    - Larger serialized size
    - Still has security concerns (unpickling untrusted data)
    """

    def __init__(self, protocol: int | None = None):
        # dill uses pickle protocols
        self.protocol = protocol or dill.DEFAULT_PROTOCOL

    def serialize(self, obj: Any) -> bytes:
        return dill.dumps(obj, protocol=self.protocol)

    def deserialize(self, data: bytes) -> Any:
        return dill.loads(data)

    def get_state(self, obj: Persistent) -> dict:
        return obj.__getstate__()
```

### 4.2 Object Signing

**Create `serialize/signing.py`:**
```python
import hmac
import hashlib
from typing import Any
from durus.serialize.base import Serializer

class SigningSerializer(Serializer):
    """Serializer wrapper that adds HMAC signatures."""

    def __init__(
        self,
        inner: Serializer,
        secret: bytes,
        algorithm: str = "sha256",
    ):
        self.inner = inner
        self.secret = secret
        self.algorithm = algorithm
        self.digest_size = hashlib.new(algorithm).digest_size

    def serialize(self, obj: Any) -> bytes:
        data = self.inner.serialize(obj)
        signature = hmac.new(
            self.secret,
            data,
            getattr(hashlib, self.algorithm),
        ).digest()
        return signature + data

    def deserialize(self, data: bytes) -> Any:
        signature = data[:self.digest_size]
        payload = data[self.digest_size:]

        # Verify signature
        expected = hmac.new(
            self.secret,
            payload,
            getattr(hashlib, self.algorithm),
        ).digest()

        if not hmac.compare_digest(signature, expected):
            raise ValueError("Signature verification failed")

        return self.inner.deserialize(payload)

    def get_state(self, obj: Persistent) -> dict:
        return self.inner.get_state(obj)
```

### 4.3 Integration with Connection

**Update `core/connection.py`:**
```python
class Connection:
    def __init__(
        self,
        storage: Storage,
        cache_size: int = 100000,
        root_class: Type[T] | None = None,
        serializer: Serializer | None = None,  # NEW
    ):
        self.storage = storage
        self.serializer = serializer or PickleSerializer()  # NEW
        self.writer = ObjectWriter(self, self.serializer)  # UPDATED
        self.reader = ObjectReader(self, self.serializer)  # UPDATED
        # ... rest of init
```

### 4.4 Critical Serialization Files

| File | Type | Priority |
|------|------|----------|
| `serialize/base.py` | NEW | HIGH |
| `pickle/pickle.py` | NEW | HIGH (default) |
| `serialize/msgspec.py` | NEW | HIGH (performance) |
| `serialize/dill.py` | NEW | MEDIUM (capability) |
| `serialize/signing.py` | NEW | MEDIUM (security) |
| `core/connection.py` | MODIFY | HIGH |
| `core/persistent.py` | MODIFY | MEDIUM |

---

## Phase 6: Modern Caching Architecture (Weeks 10-11)

### 6.1 Oneiric Cache Adapter Implementation

**Create `cache/oneiric_adapter.py`:**
```python
"""Oneiric cache adapter using Durus as backend.

Implements Oneiric cache interface with modern caching patterns:
- Multi-tier caching (memory, storage, remote)
- Write-through and write-back strategies
- TTL-based expiration
- Cache warming and prefetching
- Distributed cache coordination
"""

from oneiric.adapters.cache import CacheBase
from durus.connection import Connection
from durus.storage.file import FileStorage
from durus.serialize.msgspec import MsgspecSerializer
from typing import Any, Optional, Callable
from datetime import datetime, timedelta
import time
import threading
from collections import OrderedDict

class LRUCache:
    """Thread-safe LRU cache with TTL support.

    Modern LRU implementation with:
    - O(1) get/set operations
    - Per-entry TTL
    - Thread-safe operations
    - Size-based eviction
    """

    def __init__(self, max_size: int = 1000, default_ttl: int = 300):
        """Initialize LRU cache.

        Args:
            max_size: Maximum number of entries
            default_ttl: Default TTL in seconds
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: OrderedDict = OrderedDict()
        self._lock = threading.RLock()
        self._expiry: dict = {}

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        with self._lock:
            # Check expiration
            if key in self._expiry and time.time() > self._expiry[key]:
                self._remove(key)
                return None

            # Move to end (most recently used)
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]

            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds (uses default if None)
        """
        with self._lock:
            # Evict if at capacity
            if len(self._cache) >= self.max_size and key not in self._cache:
                self._cache.popitem(last=False)  # Remove least recently used

            self._cache[key] = value
            self._cache.move_to_end(key)  # Mark as recently used

            # Set expiration
            if ttl is None:
                ttl = self.default_ttl
            if ttl > 0:
                self._expiry[key] = time.time() + ttl
            elif key in self._expiry:
                del self._expiry[key]

    def invalidate(self, key: str) -> bool:
        """Invalidate cache entry.

        Args:
            key: Cache key

        Returns:
            True if key was cached
        """
        with self._lock:
            if key in self._cache:
                self._remove(key)
                return True
            return False

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
            self._expiry.clear()

    def _remove(self, key: str) -> None:
        """Remove entry from cache."""
        self._cache.pop(key, None)
        self._expiry.pop(key, None)

    def cleanup_expired(self) -> int:
        """Remove all expired entries.

        Returns:
            Number of entries removed
        """
        with self._lock:
            now = time.time()
            expired = [k for k, v in self._expiry.items() if v < now]

            for key in expired:
                self._remove(key)

            return len(expired)


class DurusCacheAdapter(CacheBase):
    """Durus-based cache adapter implementing Oneiric CacheBase.

    Provides multi-tier caching:
    - Tier 1: In-memory LRU cache (hot data)
    - Tier 2: Durus persistent cache (warm data)
    - Tier 3: Optional remote cache (distributed)

    Cache strategies:
    - Write-through: Write to all tiers immediately
    - Write-back: Write to memory, flush to storage later
    - Read-through: Load from storage on cache miss
    """

    def __init__(
        self,
        db_path: str = "durus_cache.durus",
        cache_size: int = 100000,
        lru_size: int = 10000,
        lru_ttl: int = 300,
        strategy: str = "write-through",  # or "write-back"
    ):
        """Initialize Durus cache adapter.

        Args:
            db_path: Path to Durus database
            cache_size: Durus connection cache size
            lru_size: LRU cache max entries
            lru_ttl: Default LRU TTL in seconds
            strategy: Cache strategy (write-through or write-back)
        """
        # Durus storage backend
        self.storage = FileStorage(db_path)
        self.serializer = MsgspecSerializer()
        self.connection = Connection(
            self.storage,
            cache_size=cache_size,
            serializer=self.serializer,
        )
        self.root = self.connection.get_root()

        # Initialize cache namespace
        if "cache" not in self.root:
            self.root["cache"] = {}
            self.connection.commit()

        # L1: In-memory LRU cache
        self.lru = LRUCache(max_size=lru_size, default_ttl=lru_ttl)

        # Strategy
        self.strategy = strategy

        # Write-back buffer for write-back strategy
        self._writeback_buffer: dict = {}
        self._writeback_lock = threading.Lock()

    def get(self, key: str, default: Any = None) -> Any:
        """Get value from cache.

        Checks tiers in order:
        1. LRU cache (memory) - fastest
        2. Durus cache (disk) - slower but persistent
        3. Returns default if not found

        Args:
            key: Cache key
            default: Default value if not found

        Returns:
            Cached value or default
        """
        # L1: Check LRU cache
        value = self.lru.get(key)
        if value is not None:
            return value

        # L2: Check Durus cache
        cache_data = self.root["cache"].get(key)
        if cache_data is not None:
            # Promote to LRU
            value, metadata = cache_data["value"], cache_data["metadata"]

            # Check expiration
            if "expires_at" in metadata:
                if time.time() > metadata["expires_at"]:
                    # Expired
                    del self.root["cache"][key]
                    self.connection.commit()
                    return default

            self.lru.set(key, value, ttl=metadata.get("ttl"))
            return value

        return default

    def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
    ) -> None:
        """Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds (None = no expiration)
        """
        metadata = {
            "created_at": time.time(),
        }

        if ttl is not None:
            metadata["expires_at"] = time.time() + ttl
            metadata["ttl"] = ttl

        if self.strategy == "write-through":
            # Write to all tiers immediately
            self._write_to_tiers(key, value, metadata)
        else:
            # Write-back: write to memory, flush asynchronously
            self.lru.set(key, value, ttl=ttl)

            with self._writeback_lock:
                self._writeback_buffer[key] = (value, metadata)

    def delete(self, key: str) -> bool:
        """Delete cache entry.

        Args:
            key: Cache key

        Returns:
            True if key was cached
        """
        # Remove from LRU
        self.lru.invalidate(key)

        # Remove from Durus
        if key in self.root["cache"]:
            del self.root["cache"][key]
            self.connection.commit()
            return True

        return False

    def exists(self, key: str) -> bool:
        """Check if key exists in cache (not expired).

        Args:
            key: Cache key

        Returns:
            True if key exists and not expired
        """
        # Check LRU first
        if self.lru.get(key) is not None:
            return True

        # Check Durus
        if key in self.root["cache"]:
            cache_data = self.root["cache"][key]
            metadata = cache_data["metadata"]

            # Check expiration
            if "expires_at" in metadata:
                if time.time() > metadata["expires_at"]:
                    return False

            return True

        return False

    def keys(self) -> list[str]:
        """Get all non-expired cache keys.

        Returns:
            List of cache keys
        """
        keys = set(self.root["cache"].keys())

        # Filter expired
        now = time.time()
        valid_keys = []
        for key in keys:
            cache_data = self.root["cache"][key]
            metadata = cache_data["metadata"]

            if "expires_at" in metadata:
                if now > metadata["expires_at"]:
                    continue

            valid_keys.append(key)

        return valid_keys

    def clear(self) -> None:
        """Clear all cache entries."""
        self.lru.clear()
        self.root["cache"] = {}
        self.connection.commit()

    def cleanup_expired(self) -> int:
        """Remove expired entries from all cache tiers.

        Returns:
            Number of entries removed
        """
        # Clean LRU
        lru_removed = self.lru.cleanup_expired()

        # Clean Durus cache
        now = time.time()
        expired_keys = []

        for key, cache_data in self.root["cache"].items():
            metadata = cache_data["metadata"]
            if "expires_at" in metadata and now > metadata["expires_at"]:
                expired_keys.append(key)

        for key in expired_keys:
            del self.root["cache"][key]

        if expired_keys:
            self.connection.commit()

        return lru_removed + len(expired_keys)

    def warm(self, keys: list[str], loader: Callable[[str], Any]) -> None:
        """Warm cache by pre-loading keys.

        Args:
            keys: List of keys to warm
            loader: Function to load value for a key
        """
        for key in keys:
            if not self.exists(key):
                try:
                    value = loader(key)
                    self.set(key, value)
                except Exception:
                    # Skip keys that fail to load
                    continue

    def get_or_set(
        self,
        key: str,
        loader: Callable[[], Any],
        ttl: int | None = None,
    ) -> Any:
        """Get value from cache, or load and cache if missing.

        Args:
            key: Cache key
            loader: Function to load value if cache miss
            ttl: Time to live in seconds

        Returns:
            Cached or loaded value
        """
        value = self.get(key)
        if value is not None:
            return value

        # Cache miss - load and cache
        value = loader()
        self.set(key, value, ttl=ttl)
        return value

    def flush_writeback_buffer(self) -> int:
        """Flush write-back buffer to Durus.

        Only applicable for write-back strategy.

        Returns:
            Number of entries flushed
        """
        if self.strategy != "write-back":
            return 0

        with self._writeback_lock:
            count = len(self._writeback_buffer)

            for key, (value, metadata) in self._writeback_buffer.items():
                self._write_to_tiers(key, value, metadata)

            self._writeback_buffer.clear()

        return count

    def _write_to_tiers(self, key: str, value: Any, metadata: dict) -> None:
        """Write value to all cache tiers.

        Args:
            key: Cache key
            value: Value to cache
            metadata: Cache metadata
        """
        # Write to LRU
        ttl = metadata.get("ttl")
        self.lru.set(key, value, ttl=ttl)

        # Write to Durus
        self.root["cache"][key] = {
            "value": value,
            "metadata": metadata,
        }
        self.connection.commit()

    def close(self) -> None:
        """Close cache and flush any pending writes."""
        if self.strategy == "write-back":
            self.flush_writeback_buffer()

        self.connection.abort()
```

### 6.2 Cache Coordination for Distributed Systems

**Create `cache/coordination.py`:**
```python
"""Cache coordination for distributed Durus deployments.

Provides:
- Pub/Sub cache invalidation
- Distributed cache warming
- Cache versioning
- Lock-based coordination
"""

from durus.connection import Connection
from durus.storage.client import ClientStorage
from typing import Callable
import threading

class CacheCoordinator:
    """Coordinate cache across multiple Durus instances.

    Uses pub/sub pattern to broadcast invalidations:
    - When one instance invalidates a key, all instances do
    - Prevents stale data in distributed scenarios
    """

    def __init__(self, connection: Connection):
        """Initialize cache coordinator.

        Args:
            connection: Durus connection (use ClientStorage for multi-node)
        """
        self.connection = connection
        self.root = connection.get_root()

        # Initialize coordination namespace
        if "cache_coordination" not in self.root:
            self.root["cache_coordination"] = {
                "invalidations": [],
                "version": 0,
            }
            self.connection.commit()

    def invalidate(self, key: str) -> None:
        """Invalidate key across all instances.

        Args:
            key: Cache key to invalidate
        """
        coordination = self.root["cache_coordination"]

        # Add to invalidation log
        coordination["invalidations"].append({
            "key": key,
            "timestamp": time.time(),
            "instance_id": self._get_instance_id(),
        })

        # Increment version
        coordination["version"] += 1

        self.connection.commit()

        # Trigger sync for ClientStorage
        self.connection.sync()

    def get_invalidations(self, since_version: int) -> list[dict]:
        """Get invalidations since version.

        Args:
            since_version: Minimum version to check

        Returns:
            List of invalidation records
        """
        coordination = self.root["cache_coordination"]
        invalidations = []

        for record in coordination["invalidations"]:
            # Filter by version (would need to add version to records)
            invalidations.append(record)

        return invalidations

    def _get_instance_id(self) -> str:
        """Get unique instance ID."""
        import os
        import socket

        return f"{os.getpid()}@{socket.gethostname()}"

    def acquire_lock(self, key: str, timeout: int = 30) -> bool:
        """Acquire distributed lock for key.

        Args:
            key: Lock key
            timeout: Timeout in seconds

        Returns:
            True if lock acquired
        """
        # Simple lock implementation using Durus
        if "locks" not in self.root:
            self.root["locks"] = {}

        locks = self.root["locks"]

        if key in locks:
            lock_data = locks[key]
            if time.time() - lock_data["acquired_at"] < lock_data["timeout"]:
                # Lock still held
                return False

        # Acquire lock
        locks[key] = {
            "instance_id": self._get_instance_id(),
            "acquired_at": time.time(),
            "timeout": timeout,
        }
        self.connection.commit()

        return True

    def release_lock(self, key: str) -> bool:
        """Release distributed lock.

        Args:
            key: Lock key

        Returns:
            True if lock was held by this instance
        """
        if "locks" not in self.root:
            return False

        locks = self.root["locks"]

        if key in locks:
            lock_data = locks[key]
            if lock_data["instance_id"] == self._get_instance_id():
                del locks[key]
                self.connection.commit()
                return True

        return False
```

### 6.3 Cache Statistics and Monitoring

**Create `cache/metrics.py`:**
```python
"""Cache metrics and monitoring for Durus cache.

Provides:
- Hit/miss ratios
- Eviction counts
- Size statistics
- Performance metrics
"""

from typing import Counter
from collections import defaultdict
import time

class CacheMetrics:
    """Track cache performance metrics."""

    def __init__(self):
        self._hits: Counter = Counter()
        self._misses: Counter = Counter()
        self._evictions: Counter = Counter()
        self._errors: Counter = Counter()
        self._latency: list = []

    def record_hit(self, tier: str) -> None:
        """Record cache hit.

        Args:
            tier: Cache tier (lru, durus)
        """
        self._hits[tier] += 1

    def record_miss(self, tier: str) -> None:
        """Record cache miss.

        Args:
            tier: Cache tier (lru, durus)
        """
        self._misses[tier] += 1

    def record_eviction(self, tier: str) -> None:
        """Record cache eviction.

        Args:
            tier: Cache tier (lru, durus)
        """
        self._evictions[tier] += 1

    def record_error(self, operation: str) -> None:
        """Record cache error.

        Args:
            operation: Operation that failed (get, set, delete)
        """
        self._errors[operation] += 1

    def record_latency(self, operation: str, duration_ms: float) -> None:
        """Record operation latency.

        Args:
            operation: Operation type
            duration_ms: Duration in milliseconds
        """
        self._latency.append({
            "operation": operation,
            "duration_ms": duration_ms,
            "timestamp": time.time(),
        })

    def get_stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dictionary with statistics
        """
        total_hits = sum(self._hits.values())
        total_misses = sum(self._misses.values())

        stats = {
            "hits": dict(self._hits),
            "misses": dict(self._misses),
            "evictions": dict(self._evictions),
            "errors": dict(self._errors),
            "hit_rate": total_hits / (total_hits + total_misses) if (total_hits + total_misses) > 0 else 0,
        }

        # Calculate percentiles
        if self._latency:
            latencies = [l["duration_ms"] for l in self._latency]
            latencies.sort()

            stats["latency_ms"] = {
                "p50": latencies[len(latencies) // 2],
                "p95": latencies[int(len(latencies) * 0.95)],
                "p99": latencies[int(len(latencies) * 0.99)],
                "avg": sum(latencies) / len(latencies),
            }

        return stats

    def reset(self) -> None:
        """Reset all metrics."""
        self._hits.clear()
        self._misses.clear()
        self._evictions.clear()
        self._errors.clear()
        self._latency.clear()
```

### 6.4 Critical Caching Files

| File | Type | Priority |
|------|------|----------|
| `cache/oneiric_adapter.py` | NEW | HIGH |
| `cache/coordination.py` | NEW | MEDIUM |
| `cache/metrics.py` | NEW | MEDIUM |

---

## Phase 7: Database Storage Adapters (Weeks 12-13)

### 7.1 Storage Adapter Interface

**Create `storage/adapters/base.py`:**
```python
"""Storage adapter interface for Durus.

Allows Durus to use various databases as storage backends:
- ZODB (native object database)
- Relational databases via SQLAlchemy
- Document databases (MongoDB, etc.)
- Key-value stores (Redis, etc.)
"""

from abc import ABC, abstractmethod
from typing import Any, Iterator, Optional

class StorageAdapter(ABC):
    """Abstract base class for storage adapters.

    Provides a unified interface for Durus to interact with
    different storage backends.
    """

    @abstractmethod
    def load(self, oid: str) -> bytes | None:
        """Load object data by OID.

        Args:
            oid: Object ID

        Returns:
            Object data or None if not found
        """
        pass

    @abstractmethod
    def store(self, oid: str, data: bytes, refs: list[str]) -> None:
        """Store object data.

        Args:
            oid: Object ID
            data: Serialized object data
            refs: List of referenced OIDs
        """
        pass

    @abstractmethod
    def delete(self, oid: str) -> bool:
        """Delete object by OID.

        Args:
            oid: Object ID

        Returns:
            True if object was deleted
        """
        pass

    @abstractmethod
    def begin_transaction(self) -> Any:
        """Begin a transaction.

        Returns:
            Transaction handle
        """
        pass

    @abstractmethod
    def commit_transaction(self, transaction: Any) -> None:
        """Commit a transaction.

        Args:
            transaction: Transaction handle
        """
        pass

    @abstractmethod
    def abort_transaction(self, transaction: Any) -> None:
        """Abort a transaction.

        Args:
            transaction: Transaction handle
        """
        pass

    @abstractmethod
    def gen_oids(self) -> Iterator[str]:
        """Generate all OIDs in storage.

        Yields:
            Object IDs
        """
        pass

    @abstractmethod
    def sync(self) -> list[str]:
        """Synchronize and return invalidated OIDs.

        Returns:
            List of invalidated OIDs
        """
        pass

    @abstractmethod
    def new_oid(self) -> str:
        """Generate a new OID.

        Returns:
            New object ID
        """
        pass

    @abstractmethod
    def pack(self) -> None:
        """Pack storage (remove old revisions)."""
        pass

    def close(self) -> None:
        """Close storage adapter."""
        pass
```

### 7.2 ZODB Storage Adapter

**Create `storage/adapters/zodb_adapter.py`:**
```python
"""ZODB storage adapter for Durus.

Provides ZODB compatibility and allows Durus to use ZODB
as a storage backend. This enables:
- Migration from ZODB to Durus
- Coexistence with ZODB applications
- Leveraging ZODB's advanced features
"""

from ZODB import DB, FileStorage as ZODBFileStorage
from ZODB.Connection import Connection as ZODBConnection
from transaction import commit as transaction_commit
from durus.storage.adapters.base import StorageAdapter
from typing import Any, Iterator
import time

class ZODBStorageAdapter(StorageAdapter):
    """ZODB storage adapter for Durus.

    Maps Durus storage operations to ZODB storage,
    enabling Durus to use ZODB databases as backends.
    """

    def __init__(self, file_path: str):
        """Initialize ZODB adapter.

        Args:
            file_path: Path to ZODB FileStorage database
        """
        self.zodb_storage = ZODBFileStorage(file_path)
        self.db = DB(self.zodb_storage)
        self.connection = self.db.open()
        self.root = self.connection.root()

        # Initialize Durus namespace
        if "durus_objects" not in self.root:
            self.root["durus_objects"] = {}
            transaction_commit()

    def load(self, oid: str) -> bytes | None:
        """Load object from ZODB."""
        return self.root["durus_objects"].get(oid)

    def store(self, oid: str, data: bytes, refs: list[str]) -> None:
        """Store object in ZODB."""
        self.root["durus_objects"][oid] = {"data": data, "refs": refs}
        transaction_commit()

    def delete(self, oid: str) -> bool:
        """Delete object from ZODB."""
        if oid in self.root["durus_objects"]:
            del self.root["durus_objects"][oid]
            transaction_commit()
            return True
        return False

    def begin_transaction(self) -> Any:
        """Begin transaction (ZODB uses implicit transactions)."""
        # ZODB uses transaction module, return sentinel
        return "zodb_transaction"

    def commit_transaction(self, transaction: Any) -> None:
        """Commit transaction."""
        transaction_commit()

    def abort_transaction(self, transaction: Any) -> None:
        """Abort transaction."""
        self.connection.abort()

    def gen_oids(self) -> Iterator[str]:
        """Generate all OIDs."""
        return iter(self.root["durus_objects"].keys())

    def sync(self) -> list[str]:
        """Sync and return invalidated OIDs."""
        # ZODB sync happens implicitly
        self.connection.sync()
        return []

    def new_oid(self) -> str:
        """Generate new OID."""
        # Use timestamp-based OID
        return str(int(time.time() * 1000000))

    def pack(self) -> None:
        """Pack ZODB storage."""
        self.db.pack()

    def close(self) -> None:
        """Close ZODB connection."""
        self.connection.close()
        self.db.close()
```

### 7.3 SQLAlchemy Storage Adapter

**Create `storage/adapters/sqlalchemy_adapter.py`:**
```python
"""SQLAlchemy storage adapter for Durus.

Enables Durus to use relational databases as storage:
- PostgreSQL
- MySQL
- SQLite
- Any SQLAlchemy-supported database
"""

from sqlalchemy import create_engine, Column, String, LargeBinary, Text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from durus.storage.adapters.base import StorageAdapter
from typing import Any, Iterator
import time
import json

Base = declarative_base()

class DurusObject(Base):
    """SQLAlchemy model for Durus objects."""
    __tablename__ = 'durus_objects'

    oid = Column(String(16), primary_key=True)
    data = Column(LargeBinary, nullable=False)
    refs = Column(Text, nullable=False)  # JSON array of OIDs
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class SQLAlchemyStorageAdapter(StorageAdapter):
    """SQLAlchemy storage adapter for Durus.

    Stores Durus objects in relational databases using SQLAlchemy.
    Supports any database with SQLAlchemy driver.
    """

    def __init__(self, database_url: str):
        """Initialize SQLAlchemy adapter.

        Args:
            database_url: SQLAlchemy database URL
                Examples:
                - SQLite: sqlite:///durus.db
                - PostgreSQL: postgresql://user:pass@localhost/db
                - MySQL: mysql://user:pass@localhost/db
        """
        self.engine = create_engine(database_url)
        Base.metadata.create_all(self.engine)

        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()

        # Track OID counter
        self._next_oid = self._get_max_oid() + 1

    def _get_max_oid(self) -> int:
        """Get maximum OID from database."""
        from sqlalchemy import func

        result = self.session.query(func.max(DurusObject.oid)).scalar()
        return int(result) if result else 0

    def load(self, oid: str) -> bytes | None:
        """Load object from database."""
        obj = self.session.query(DurusObject).get(oid)
        if obj:
            return obj.data
        return None

    def store(self, oid: str, data: bytes, refs: list[str]) -> None:
        """Store object in database."""
        obj = self.session.query(DurusObject).get(oid)

        if obj:
            # Update existing
            obj.data = data
            obj.refs = json.dumps(refs)
            obj.updated_at = time.time()
        else:
            # Insert new
            obj = DurusObject(
                oid=oid,
                data=data,
                refs=json.dumps(refs),
                created_at=time.time(),
                updated_at=time.time(),
            )
            self.session.add(obj)

        self.session.commit()

    def delete(self, oid: str) -> bool:
        """Delete object from database."""
        obj = self.session.query(DurusObject).get(oid)
        if obj:
            self.session.delete(obj)
            self.session.commit()
            return True
        return False

    def begin_transaction(self) -> Any:
        """Begin transaction."""
        return self.session.begin()

    def commit_transaction(self, transaction: Any) -> None:
        """Commit transaction."""
        transaction.commit()

    def abort_transaction(self, transaction: Any) -> None:
        """Abort transaction."""
        transaction.rollback()

    def gen_oids(self) -> Iterator[str]:
        """Generate all OIDs."""
        for obj in self.session.query(DurusObject.oid):
            yield obj.oid

    def sync(self) -> list[str]:
        """Sync (no-op for SQLAlchemy)."""
        return []

    def new_oid(self) -> str:
        """Generate new OID."""
        oid = self._next_oid
        self._next_oid += 1
        return str(oid).zfill(16)

    def pack(self) -> None:
        """Pack database (remove old objects if applicable)."""
        # Could implement soft delete cleanup here
        pass

    def close(self) -> None:
        """Close connection."""
        self.session.close()
        self.engine.dispose()
```

### 7.4 Redis Storage Adapter

**Create `storage/adapters/redis_adapter.py`:**
```python
"""Redis storage adapter for Durus.

Provides high-performance key-value storage for Durus objects.
Ideal for:
- Distributed caching
- Fast object access
- Shared state across multiple Durus instances
"""

from redis import Redis
from durus.storage.adapters.base import StorageAdapter
from typing import Any, Iterator
import json
import time

class RedisStorageAdapter(StorageAdapter):
    """Redis storage adapter for Durus.

    Stores Durus objects in Redis for fast access and
    distributed caching.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
        prefix: str = "durus:",
    ):
        """Initialize Redis adapter.

        Args:
            host: Redis host
            port: Redis port
            db: Redis database number
            password: Optional password
            prefix: Key prefix for Durus objects
        """
        self.redis = Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=False,  # Keep binary for data
        )
        self.prefix = prefix

        # Track OID counter
        counter_key = f"{prefix}meta:counter"
        if not self.redis.exists(counter_key):
            self.redis.set(counter_key, 0)

    def _make_key(self, oid: str) -> str:
        """Create Redis key for OID."""
        return f"{self.prefix}object:{oid}"

    def load(self, oid: str) -> bytes | None:
        """Load object from Redis."""
        key = self._make_key(oid)
        data = self.redis.get(key)
        return data if data else None

    def store(self, oid: str, data: bytes, refs: list[str]) -> None:
        """Store object in Redis."""
        key = self._make_key(oid)

        # Store data
        self.redis.hset(
            key,
            mapping={
                "data": data,
                "refs": json.dumps(refs),
                "updated_at": time.time(),
            },
        )

        # No expiration for persistent storage
        # For caching, could use: self.redis.expire(key, ttl)

    def delete(self, oid: str) -> bool:
        """Delete object from Redis."""
        key = self._make_key(oid)
        result = self.redis.delete(key)
        return result > 0

    def begin_transaction(self) -> Any:
        """Begin transaction (Redis uses MULTI)."""
        return self.redis.pipeline()

    def commit_transaction(self, transaction: Any) -> None:
        """Commit transaction (execute pipeline)."""
        transaction.execute()

    def abort_transaction(self, transaction: Any) -> None:
        """Abort transaction (discard pipeline)."""
        transaction.reset()

    def gen_oids(self) -> Iterator[str]:
        """Generate all OIDs."""
        pattern = f"{self.prefix}object:*"
        for key in self.redis.scan_iter(match=pattern):
            # Extract OID from key
            oid = key.decode().split(":")[-1]
            yield oid

    def sync(self) -> list[str]:
        """Sync (no-op for Redis)."""
        return []

    def new_oid(self) -> str:
        """Generate new OID."""
        counter_key = f"{self.prefix}meta:counter"
        oid = self.redis.incr(counter_key)
        return str(oid).zfill(16)

    def pack(self) -> None:
        """Pack (no-op for Redis)."""
        pass

    def close(self) -> None:
        """Close Redis connection."""
        self.redis.close()
```

### 7.5 Adapter Factory

**Create `storage/adapters/factory.py`:**
```python
"""Factory for creating storage adapters."""

from durus.storage.adapters.base import StorageAdapter
from durus.storage.adapters.zodb_adapter import ZODBStorageAdapter
from durus.storage.adapters.sqlalchemy_adapter import SQLAlchemyStorageAdapter
from durus.storage.adapters.redis_adapter import RedisStorageAdapter

def create_adapter(adapter_type: str, **kwargs) -> StorageAdapter:
    """Create storage adapter by type.

    Args:
        adapter_type: Adapter type (zodb, sqlalchemy, redis)
        **kwargs: Adapter-specific arguments

    Returns:
        Storage adapter instance

    Raises:
        ValueError: Unknown adapter type
    """
    adapters = {
        "zodb": ZODBStorageAdapter,
        "sqlalchemy": SQLAlchemyStorageAdapter,
        "redis": RedisStorageAdapter,
    }

    adapter_class = adapters.get(adapter_type.lower())
    if adapter_class is None:
        raise ValueError(f"Unknown adapter type: {adapter_type}")

    return adapter_class(**kwargs)
```

### 7.6 Critical Adapter Files

| File | Type | Priority |
|------|------|----------|
| `storage/adapters/base.py` | NEW | HIGH |
| `storage/adapters/zodb_adapter.py` | NEW | HIGH |
| `storage/adapters/sqlalchemy_adapter.py` | NEW | HIGH |
| `storage/adapters/redis_adapter.py` | NEW | MEDIUM |
| `storage/adapters/factory.py` | NEW | MEDIUM |

---

## Phase 8: Observability & Monitoring (Weeks 14-15)

### 8.1 OpenTelemetry Integration

**Create `observability/tracing.py`:**
```python
"""OpenTelemetry integration for Durus.

Provides distributed tracing, metrics, and monitoring
compatible with Oneiric's observability patterns.
"""

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation import instrument

# Initialize tracing
resource = Resource.create({
    "service.name": "durus",
    "service.version": "5.0.0",
})

trace.set_tracer_provider(TracerProvider(resource=resource))
tracer = trace.get_tracer(__name__)

class TracedConnection:
    """Wrapper for Durus Connection with OpenTelemetry tracing."""

    def __init__(self, connection, tracer=None):
        """Initialize traced connection.

        Args:
            connection: Durus Connection instance
            tracer: OpenTelemetry tracer
        """
        self.connection = connection
        self.tracer = tracer or trace.get_tracer(__name__)

    def get_root(self):
        """Get root with tracing."""
        with self.tracer.start_as_current_span("Connection.get_root") as span:
            root = self.connection.get_root()
            span.set_attribute("root.oid", root._p_oid)
            return root

    def commit(self):
        """Commit transaction with tracing."""
        with self.tracer.start_as_current_span("Connection.commit") as span:
            span.set_attribute("transaction.changed_count", len(self.connection.changed))

            start_time = time.time()
            try:
                result = self.connection.commit()
                duration_ms = (time.time() - start_time) * 1000

                span.set_attribute("duration_ms", duration_ms)
                span.set_status("ok")

                return result
            except Exception as e:
                span.set_status("error", str(e))
                raise

    def abort(self):
        """Abort transaction with tracing."""
        with self.tracer.start_as_current_span("Connection.abort") as span:
            try:
                self.connection.abort()
                span.set_status("ok")
            except Exception as e:
                span.set_status("error", str(e))
                raise

    def get(self, oid, klass=None):
        """Get object with tracing."""
        with self.tracer.start_as_current_span("Connection.get") as span:
            span.set_attribute("object.oid", oid)
            if klass:
                span.set_attribute("object.class", klass.__name__)

            result = self.connection.get(oid, klass)

            if result is not None:
                span.set_attribute("object.found", True)
                span.set_attribute("object.ghost", result._p_is_ghost())
            else:
                span.set_attribute("object.found", False)

            return result


def instrument_connection(connection):
    """Add OpenTelemetry instrumentation to connection.

    Args:
        connection: Durus Connection instance

    Returns:
        TracedConnection wrapper
    """
    return TracedConnection(connection)
```

### 8.2 Prometheus Metrics

**Create `observability/metrics.py`:**
```python
"""Prometheus metrics for Durus.

Exposes metrics that Prometheus can scrape:
- Operation counters
- Latency histograms
- Gauge metrics for cache/storage size
- Conflict error rates
"""

from prometheus_client import Counter, Histogram, Gauge, Info
from prometheus_client.core import CollectorRegistry
from prometheus_client.exposition import start_http_server
import time

# Create registry
registry = CollectorRegistry()

# Metrics
commit_counter = Counter(
    'durus_commits_total',
    'Total number of Durus commits',
    ['status'],  # success, failure
    registry=registry,
)

abort_counter = Counter(
    'durus_aborts_total',
    'Total number of Durus aborts',
    registry=registry,
)

get_counter = Counter(
    'durus_gets_total',
    'Total number of Durus get operations',
    ['cache_hit'],  # hit, miss
    registry=registry,
)

conflict_counter = Counter(
    'durus_conflicts_total',
    'Total number of Durus conflicts',
    ['conflict_type'],  # write_conflict, read_conflict
    registry=registry,
)

commit_duration = Histogram(
    'durus_commit_duration_seconds',
    'Durus commit operation duration',
    registry=registry,
)

get_duration = Histogram(
    'durus_get_duration_seconds',
    'Durus get operation duration',
    registry=registry,
)

cache_size = Gauge(
    'durus_cache_size',
    'Current number of objects in cache',
    registry=registry,
)

storage_size = Gauge(
    'durus_storage_size_bytes',
    'Current storage size in bytes',
    registry=registry,
)

connection_info = Info(
    'durus_connection',
    'Durus connection information',
    ['storage_type'],  # file, sqlite, client
    registry=registry,
)


class MetricsCollector:
    """Collect and report metrics for Durus operations.

    Integrates with Oneiric's metrics system.
    """

    def __init__(self, connection):
        """Initialize metrics collector.

        Args:
            connection: Durus Connection instance
        """
        self.connection = connection
        self.storage_type = type(connection.storage).__name__

        # Set static info
        connection_info.labels({'storage_type': self.storage_type})

    def record_commit(self, success: bool = True):
        """Record commit operation.

        Args:
            success: Whether commit succeeded
        """
        status = "success" if success else "failure"
        commit_counter.labels(status=status).inc()

    def record_abort(self):
        """Record abort operation."""
        abort_counter.inc()

    def record_get(self, cache_hit: bool):
        """Record get operation.

        Args:
            cache_hit: Whether object was in cache
        """
        hit_type = "hit" if cache_hit else "miss"
        get_counter.labels(cache_hit=hit_type).inc()

    def record_conflict(self, conflict_type: str):
        """Record conflict error.

        Args:
            conflict_type: Type of conflict (write_conflict, read_conflict)
        """
        conflict_counter.labels(conflict_type=conflict_type).inc()

    def time_commit(self, func):
        """Time commit operation.

        Args:
            func: Function to time

        Returns:
            Function result
        """
        with commit_duration.time():
            return func()

    def time_get(self, func):
        """Time get operation.

        Args:
            func: Function to time

        Returns:
            Function result
        """
        with get_duration.time():
            return func()

    def update_cache_size(self):
        """Update cache size gauge."""
        cache_size.set(len(self.connection.get_cache()))

    def update_storage_size(self):
        """Update storage size gauge."""
        # This would need storage-specific implementation
        pass

    def start_metrics_server(self, port: int = 8000):
        """Start Prometheus metrics server.

        Args:
            port: Port to expose metrics on
        """
        start_http_server(port, registry=registry)
```

### 8.3 Health Check Endpoint

**Create `observability/health.py`:**
```python
"""Health check endpoints for Durus.

Provides health status for orchestrators and load balancers.
Compatible with Oneiric health check patterns.
"""

from typing import Dict, Any
from datetime import datetime
import time

class HealthChecker:
    """Health checker for Durus instances."""

    def __init__(self, connection):
        """Initialize health checker.

        Args:
            connection: Durus Connection instance
        """
        self.connection = connection

    def check_health(self) -> Dict[str, Any]:
        """Perform comprehensive health check.

        Returns:
            Health status dictionary
        """
        health = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "checks": {},
        }

        # Check storage accessibility
        try:
            # Try to load root object
            root = self.connection.get_root()
            health["checks"]["storage"] = {
                "status": "pass",
                "root_oid": root._p_oid,
            }
        except Exception as e:
            health["checks"]["storage"] = {
                "status": "fail",
                "error": str(e),
            }
            health["status"] = "unhealthy"

        # Check cache
        try:
            cache_count = len(self.connection.get_cache())
            health["checks"]["cache"] = {
                "status": "pass",
                "size": cache_count,
            }
        except Exception as e:
            health["checks"]["cache"] = {
                "status": "fail",
                "error": str(e),
            }
            health["status"] = "degraded"

        # Check transaction status
        try:
            transaction_serial = self.connection.get_transaction_serial()
            health["checks"]["transaction"] = {
                "status": "pass",
                "serial": transaction_serial,
            }
        except Exception as e:
            health["checks"]["transaction"] = {
                "status": "fail",
                "error": str(e),
            }
            health["status"] = "unhealthy"

        return health

    def is_ready(self) -> bool:
        """Quick readiness check.

        Returns:
            True if system is ready to accept requests
        """
        try:
            root = self.connection.get_root()
            return root is not None
        except Exception:
            return False

    def is_live(self) -> bool:
        """Liveness check - is the system responding?

        Returns:
            True if system is responding
        """
        try:
            # Quick operation to verify liveness
            self.connection.get_root()
            return True
        except Exception:
            return False
```

### 8.4 Oneiric Logging Integration

**Create `observability/logging.py`:**
```python
"""Oneiric-compatible structured logging for Durus.

Integrates with Oneiric's logging patterns for consistent
observability across the Mahavishnu ecosystem.
"""

from oneiric import get_logger
import structlog
from opentelemetry import trace

logger = get_logger(__name__)

def get_connection_logger(connection_id: str):
    """Get logger with connection context.

    Args:
        connection_id: Unique connection identifier

    Returns:
        Bound logger with connection context
    """
    return logger.bind(
        component="durus",
        connection_id=connection_id,
    )

def log_operation(operation: str, **kwargs):
    """Log Durus operation with context.

    Args:
        operation: Operation name (commit, abort, get, etc.)
        **kwargs: Operation-specific context
    """
    log_kwargs = {
        "operation": operation,
        "timestamp": time.time(),
        **kwargs,
    }

    # Add trace context if available
    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
        log_kwargs["trace_id"] = f"{current_span.context.trace_id:032x}"
        log_kwargs["span_id"] = f"{current_span.context.span_id:016x}"

    logger.info("durus.operation", **log_kwargs)


class DurusLogger:
    """Context manager for logging Durus operations."""

    def __init__(self, operation: str, **context):
        """Initialize logger.

        Args:
            operation: Operation name
            **context: Additional context
        """
        self.operation = operation
        self.context = context
        self.start_time = None

    def __enter__(self):
        """Start logging operation."""
        self.start_time = time.time()
        log_operation(self.operation, stage="start", **self.context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Complete logging operation."""
        duration = time.time() - self.start_time if self.start_time else 0

        if exc_type is None:
            log_operation(
                self.operation,
                stage="complete",
                duration_ms=duration * 1000,
                **self.context,
            )
        else:
            log_operation(
                self.operation,
                stage="error",
                duration_ms=duration * 1000,
                error=str(exc_val),
                **self.context,
            )
```

### 8.5 Mahavishnu/Akosha Integration

**Create `observability/mahavishnu_client.py`:**
```python
"""Mahavishnu/Akosha integration for Durus observability.

Pushes logs, metrics, and events to Mahavishnu orchestrator and
Akosha knowledge graph system, following ecosystem patterns.
"""

from typing import Any, Dict
import time
import json
from datetime import datetime

class MahavishnuClient:
    """Client for pushing observability data to Mahavishnu.

    Mahavishnu serves as the central orchestrator and collects:
    - Structured logs from all ecosystem components
    - Metrics for monitoring and alerting
    - Events for workflow coordination
    - Health status for orchestration decisions
    """

    def __init__(
        self,
        mahavishnu_url: str = "http://localhost:8680",
        component_id: str = "durus",
        instance_id: str | None = None,
    ):
        """Initialize Mahavishnu client.

        Args:
            mahavishnu_url: Mahavishnu server URL
            component_id: Component identifier
            instance_id: Unique instance ID (auto-generated if None)
        """
        self.mahavishnu_url = mahavishnu_url
        self.component_id = component_id
        self.instance_id = instance_id or self._generate_instance_id()
        self.session = None  # Lazy import of httpx/requests

    def _generate_instance_id(self) -> str:
        """Generate unique instance ID."""
        import os
        import socket
        return f"{os.getpid()}@{socket.gethostname()}:{int(time.time())}"

    def push_log(self, log_record: Dict[str, Any]) -> bool:
        """Push log record to Mahavishnu.

        Args:
            log_record: Structured log record with:
                - level: str (DEBUG, INFO, WARNING, ERROR)
                - message: str
                - timestamp: float
                - component: str
                - context: Dict[str, Any]

        Returns:
            True if push succeeded
        """
        try:
            # Add component context
            log_record.update({
                "component": self.component_id,
                "instance_id": self.instance_id,
                "timestamp": log_record.get("timestamp", time.time()),
            })

            # Push to Mahavishnu log endpoint
            # POST /api/v1/logs
            response = self._post("/api/v1/logs", log_record)
            return response.status_code == 200
        except Exception as e:
            # Log locally but don't fail
            print(f"Failed to push log to Mahavishnu: {e}")
            return False

    def push_metrics(self, metrics: Dict[str, Any]) -> bool:
        """Push metrics to Mahavishnu.

        Args:
            metrics: Dictionary with metric values:
                - commits_total: int
                - aborts_total: int
                - cache_hit_rate: float
                - transaction_duration_ms: float
                - storage_size_bytes: int
                - ... (any Prometheus-style metric)

        Returns:
            True if push succeeded
        """
        try:
            # Add metadata
            payload = {
                "component": self.component_id,
                "instance_id": self.instance_id,
                "timestamp": time.time(),
                "metrics": metrics,
            }

            # Push to Mahavishnu metrics endpoint
            # POST /api/v1/metrics
            response = self._post("/api/v1/metrics", payload)
            return response.status_code == 200
        except Exception as e:
            print(f"Failed to push metrics to Mahavishnu: {e}")
            return False

    def push_event(self, event_type: str, event_data: Dict[str, Any]) -> bool:
        """Push event to Mahavishnu for workflow coordination.

        Args:
            event_type: Event type (transaction_begin, transaction_end, conflict, etc.)
            event_data: Event-specific data

        Returns:
            True if push succeeded
        """
        try:
            payload = {
                "component": self.component_id,
                "instance_id": self.instance_id,
                "event_type": event_type,
                "timestamp": time.time(),
                "data": event_data,
            }

            # Push to Mahavishnu events endpoint
            # POST /api/v1/events
            response = self._post("/api/v1/events", payload)
            return response.status_code == 200
        except Exception as e:
            print(f"Failed to push event to Mahavishnu: {e}")
            return False

    def push_health(self, health_status: Dict[str, Any]) -> bool:
        """Push health status to Mahavishnu.

        Args:
            health_status: Health check results from HealthChecker

        Returns:
            True if push succeeded
        """
        try:
            payload = {
                "component": self.component_id,
                "instance_id": self.instance_id,
                "timestamp": time.time(),
                "health": health_status,
            }

            # Push to Mahavishnu health endpoint
            # POST /api/v1/health
            response = self._post("/api/v1/health", payload)
            return response.status_code == 200
        except Exception as e:
            print(f"Failed to push health to Mahavishnu: {e}")
            return False

    def _post(self, endpoint: str, data: Dict[str, Any]):
        """POST request to Mahavishnu.

        Args:
            endpoint: API endpoint
            data: Request payload

        Returns:
            Response object
        """
        if self.session is None:
            import httpx
            self.session = httpx.Client(timeout=5.0)

        url = f"{self.mahavishnu_url}{endpoint}"
        return self.session.post(url, json=data)

    def close(self):
        """Close client session."""
        if self.session:
            self.session.close()


class AkoshaClient:
    """Client for integrating with Akosha knowledge graph.

    Akosha stores:
    - Vector embeddings for semantic search
    - Knowledge graph of relationships
    - Persistent memory across sessions
    - Historical patterns and insights

    Durus can push:
    - Query patterns for optimization
    - Access patterns for cache warming
    - Schema metadata for discovery
    - Performance metrics for analysis
    """

    def __init__(
        self,
        akosha_url: str = "http://localhost:8682",
    ):
        """Initialize Akosha client.

        Args:
            akosha_url: Akosha server URL
        """
        self.akosha_url = akosha_url
        self.session = None

    def store_embeddings(
        self,
        vectors: list[list[float]],
        metadata: list[Dict[str, Any]],
    ) -> bool:
        """Store vector embeddings in Akosha.

        Use cases:
        - Semantic search over stored objects
        - Similarity-based recommendations
        - Clustering and anomaly detection

        Args:
            vectors: List of embedding vectors
            metadata: List of metadata records (one per vector)

        Returns:
            True if storage succeeded
        """
        try:
            payload = {
                "vectors": vectors,
                "metadata": metadata,
                "collection": "durus_objects",
            }

            # POST /api/v1/vectors
            response = self._post("/api/v1/vectors", payload)
            return response.status_code == 200
        except Exception as e:
            print(f"Failed to store embeddings in Akosha: {e}")
            return False

    def store_knowledge(
        self,
        entity_type: str,
        entity_id: str,
        attributes: Dict[str, Any],
        relationships: list[Dict[str, str]] | None = None,
    ) -> bool:
        """Store knowledge graph entity in Akosha.

        Use cases:
        - Schema discovery and documentation
        - Object relationship mapping
        - Dependency tracking

        Args:
            entity_type: Type of entity (class, object, relationship)
            entity_id: Unique entity identifier
            attributes: Entity attributes
            relationships: List of relationships to other entities

        Returns:
            True if storage succeeded
        """
        try:
            payload = {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "attributes": attributes,
                "relationships": relationships or [],
                "source": "durus",
            }

            # POST /api/v1/knowledge
            response = self._post("/api/v1/knowledge", payload)
            return response.status_code == 200
        except Exception as e:
            print(f"Failed to store knowledge in Akosha: {e}")
            return False

    def search_similar(
        self,
        query_vector: list[float],
        top_k: int = 10,
        filters: Dict[str, Any] | None = None,
    ) -> list[Dict[str, Any]]:
        """Search for similar vectors in Akosha.

        Args:
            query_vector: Query embedding
            top_k: Number of results to return
            filters: Optional metadata filters

        Returns:
            List of similar items with metadata
        """
        try:
            payload = {
                "vector": query_vector,
                "top_k": top_k,
                "filters": filters or {},
                "collection": "durus_objects",
            }

            # POST /api/v1/search
            response = self._post("/api/v1/search", payload)
            if response.status_code == 200:
                return response.json().get("results", [])
            return []
        except Exception as e:
            print(f"Failed to search Akosha: {e}")
            return []

    def _post(self, endpoint: str, data: Dict[str, Any]):
        """POST request to Akosha."""
        if self.session is None:
            import httpx
            self.session = httpx.Client(timeout=5.0)

        url = f"{self.akosha_url}{endpoint}"
        return self.session.post(url, json=data)

    def close(self):
        """Close client session."""
        if self.session:
            self.session.close()


class ObservabilityManager:
    """Unified observability manager for Mahavishnu and Akosha.

    Combines log/metric/event pushing with knowledge graph storage.
    """

    def __init__(
        self,
        mahavishnu_url: str = "http://localhost:8680",
        akosha_url: str = "http://localhost:8682",
        component_id: str = "durus",
        enable_mahavishnu: bool = True,
        enable_akosha: bool = True,
    ):
        """Initialize observability manager.

        Args:
            mahavishnu_url: Mahavishnu server URL
            akosha_url: Akosha server URL
            component_id: Component identifier
            enable_mahavishnu: Enable Mahavishnu integration
            enable_akosha: Enable Akosha integration
        """
        self.mahavishnu = MahavishnuClient(mahavishnu_url, component_id) if enable_mahavishnu else None
        self.akosha = AkoshaClient(akosha_url) if enable_akosha else None

    def log_and_track(self, log_record: Dict[str, Any]) -> None:
        """Log to Mahavishnu and track in Akosha if applicable.

        Args:
            log_record: Structured log record
        """
        if self.mahavishnu:
            self.mahavishnu.push_log(log_record)

        # Track error patterns in Akosha
        if self.akosha and log_record.get("level") == "ERROR":
            self.akosha.store_knowledge(
                entity_type="error",
                entity_id=f"{log_record.get('operation')}_{int(time.time())}",
                attributes={
                    "operation": log_record.get("operation"),
                    "error": log_record.get("message"),
                    "context": log_record.get("context", {}),
                    "timestamp": log_record.get("timestamp"),
                },
            )

    def track_metrics(self, metrics: Dict[str, Any]) -> None:
        """Track metrics in Mahavishnu.

        Args:
            metrics: Metrics dictionary
        """
        if self.mahavishnu:
            self.mahavishnu.push_metrics(metrics)

    def track_performance(
        self,
        operation: str,
        duration_ms: float,
        metadata: Dict[str, Any],
    ) -> None:
        """Track performance metrics and patterns.

        Args:
            operation: Operation name
            duration_ms: Duration in milliseconds
            metadata: Additional metadata
        """
        # Push to Mahavishnu as metrics
        if self.mahavishnu:
            self.mahavishnu.push_metrics({
                f"{operation}_duration_ms": duration_ms,
                **metadata,
            })

        # Store performance pattern in Akosha
        if self.akosha:
            self.akosha.store_knowledge(
                entity_type="performance_pattern",
                entity_id=f"{operation}_{int(time.time())}",
                attributes={
                    "operation": operation,
                    "duration_ms": duration_ms,
                    **metadata,
                },
            )

    def close(self) -> None:
        """Close all clients."""
        if self.mahavishnu:
            self.mahavishnu.close()
        if self.akosha:
            self.akosha.close()
```

### 8.6 Critical Observability Files

| File | Type | Priority |
|------|------|----------|
| `observability/tracing.py` | NEW | HIGH |
| `observability/metrics.py` | NEW | HIGH |
| `observability/health.py` | NEW | HIGH |
| `observability/logging.py` | NEW | HIGH |
| `observability/mahavishnu_client.py` | NEW | HIGH |

---

## Phase 9: Future Features & Modernizations (Post-5.0)

### 9.1 Planned Feature Enhancements

**Priority 1: Core Features (High Impact)**

1. **Automatic Schema Migration & Versioning**
   - Track schema versions of Persistent objects
   - Automatic migration when loading old objects
   - Rollback capability for migrations
   - Migration CLI: `durus migrate [up|down|status]`
   - Inspired by: Alembic, Django migrations
   - **Estimated effort**: 2-3 weeks
   - **File**: `schema/migration.py`

2. **Change Data Capture (CDC) Event Stream**
   - Stream all database changes to Kafka/Redis/Pulsar
   - Enable real-time analytics, caching invalidation, replication
   - Per-object filtering and transformation
   - Configurable capture rules
   - Inspired by: Debezium
   - **Estimated effort**: 2 weeks
   - **Files**: `cdc/producer.py`, `cdc/config.py`

3. **Full-Text Search Integration**
   - Automatic indexing of Persistent objects
   - Support for Elasticsearch, Meilisearch, Tantivy
   - Query DSL for complex searches
   - CLI: `durus search "query" --index`
   - Inspired by: PostgreSQL full-text search
   - **Estimated effort**: 2 weeks
   - **Files**: `search/indexer.py`, `search/query.py`

**Priority 2: Advanced Features (Medium Impact)**

4. **GraphQL Query Interface**
   - Expose Durus data via GraphQL API
   - Type-safe queries with schema introspection
   - Real-time subscriptions for data changes
   - Auto-generate schema from Persistent classes
   - Inspired by: Hasura, PostGraphile
   - **Estimated effort**: 3 weeks
   - **Files**: `graphql/schema.py`, `graphql/server.py`

5. **Time Travel / Temporal Queries**
   - Query data as it was at any point in time
   - Automatic retention policies for historical data
   - Comparison queries between time points
   - CLI: `durus query --at="2025-01-15 10:00:00"`
   - Inspired by: PostgreSQL temporal tables
   - **Estimated effort**: 3 weeks
   - **Files**: `temporal/history.py`, `temporal/query.py`

### 9.2 Planned Modernizations

**Priority 1: Core Modernizations (High Impact)**

1. **Async/Await Native Support**
   - Rewrite all I/O operations with asyncio
   - Support async/await throughout the stack
   - Compatible with FastAPI, Starlette
   - New async Connection API
   - Inspired by: asyncio, trio
   - **Estimated effort**: 4 weeks
   - **Files**: `core/async_connection.py`, `storage/async_storage.py`

2. **Native Vector Embedding Storage**
   - Built-in vector similarity search
   - Integration with sentence-transformers, OpenAI
   - HNSW indexing for fast ANN
   - CLI: `durus vector search --query="..."`
   - Inspired by: pgvector, Weaviate
   - **Estimated effort**: 3 weeks
   - **Files**: `vector/storage.py`, `vector/hnsw_index.py`

3. **Automatic Compression (zstd/lz4)**
   - Transparent compression for large objects
   - Configurable compression thresholds
   - Benchmark: 5-10x space savings
   - Minimal CPU overhead with lz4
   - Inspired by: ZFS compression
   - **Estimated effort**: 1 week
   - **Files**: `storage/compression.py`, `serialize/compressed.py`

**Priority 2: UX & Performance (Medium Impact)**

4. **Streaming API for Large Datasets**
   - Iterator-based streaming without memory load
   - Server-sent events (SSE) for progressive loading
   - Memory-efficient processing
   - Compatible with async iteration
   - Inspired by: Kafka Streams
   - **Estimated effort**: 2 weeks
   - **Files**: `core/streaming.py`, `server/sse.py`

5. **Built-in Pydantic Schema Validation**
   - Validate objects on storage
   - Auto-generate JSON schemas
   - Runtime type checking
   - Decorator-based validation
   - Inspired by: Pydantic, TypeGuard
   - **Estimated effort**: 1 week
   - **Files**: `validation/pydantic_integration.py`

### 9.3 Implementation Priority

**Short-term (3-6 months post-5.0):**
1. Automatic Compression (1 week) - Quick win, high impact
2. Pydantic Validation (1 week) - Improves data quality
3. CDC Event Stream (2 weeks) - Enables ecosystem integration
4. Async/Await Support (4 weeks) - Foundation for modern async stack

**Medium-term (6-12 months):**
5. Full-Text Search (2 weeks) - Major UX improvement
6. Schema Migration (2-3 weeks) - Solves upgrade pain point
7. Vector Storage (3 weeks) - AI/ML integration
8. Streaming API (2 weeks) - Performance for large datasets

**Long-term (12+ months):**
9. GraphQL Interface (3 weeks) - Modern API layer
10. Time Travel Queries (3 weeks) - Advanced analytics capability

---

## Phase 10: Oneiric Adapter Registry & Distribution (Weeks 16-17)

### 6.1 Oneiric Adapter Storage Model

**Create `oneiric/adapter_registry.py`:**
```python
"""Oneiric adapter registry using Durus for persistent storage.

This module implements a durable adapter registry that can:
- Store adapter manifests and metadata
- Cache adapter code for distribution
- Maintain version history
- Support dynamic adapter loading
- Provide MCP-compatible interface

This serves as an alternative or backend to oneiric-mcp server.
"""

from durus.persistent import Persistent
from durus.collections.dict import PersistentDict
from typing import Any
from datetime import datetime
import time
import hashlib

class AdapterManifest(Persistent):
    """Persistent adapter manifest.

    Stores metadata about a Oneiric adapter including:
    - Name, version, type
    - Dependencies
    - Schema definitions
    - Source code hash
    - Upload timestamp
    """

    def __init__(
        self,
        name: str,
        version: str,
        adapter_type: str,
        schema: dict[str, Any],
        code: str,
        dependencies: list[str] | None = None,
        author: str | None = None,
        description: str | None = None,
    ):
        """Initialize adapter manifest.

        Args:
            name: Adapter name
            version: Semantic version
            adapter_type: Type (storage, vector, logging, etc.)
            schema: Pydantic schema definition
            code: Adapter source code
            dependencies: List of dependencies
            author: Author name/email
            description: Description
        """
        self._p_name = name
        self._p_version = version
        self._p_adapter_type = adapter_type
        self._p_schema = schema
        self._p_code = code
        self._p_dependencies = dependencies or []
        self._p_author = author
        self._p_description = description
        self._p_created_at = time.time()
        self._p_code_hash = hashlib.sha256(code.encode()).hexdigest()

    @property
    def name(self) -> str:
        return self._p_name

    @property
    def version(self) -> str:
        return self._p_version

    @property
    def adapter_type(self) -> str:
        return self._p_adapter_type

    @property
    def id(self) -> str:
        """Unique identifier (name:version)."""
        return f"{self._p_name}:{self._p_version}"

    def __getstate__(self) -> dict:
        return {
            "name": self._p_name,
            "version": self._p_version,
            "adapter_type": self._p_adapter_type,
            "schema": self._p_schema,
            "code": self._p_code,
            "dependencies": self._p_dependencies,
            "author": self._p_author,
            "description": self._p_description,
            "created_at": self._p_created_at,
            "code_hash": self._p_code_hash,
        }

    def __setstate__(self, state: dict) -> None:
        self._p_name = state["name"]
        self._p_version = state["version"]
        self._p_adapter_type = state["adapter_type"]
        self._p_schema = state["schema"]
        self._p_code = state["code"]
        self._p_dependencies = state["dependencies"]
        self._p_author = state["author"]
        self._p_description = state["description"]
        self._p_created_at = state["created_at"]
        self._p_code_hash = state["code_hash"]


class AdapterRegistry(Persistent):
    """Registry of Oneiric adapters with version management.

    Provides:
    - Adapter registration and versioning
    - Query by type, name, version
    - Version history tracking
    - Code retrieval for loading
    """

    def __init__(self):
        self._p_adapters: PersistentDict = PersistentDict()  # id -> manifest
        self._p_by_name: PersistentDict = PersistentDict()  # name -> [ids]
        self._p_by_type: PersistentDict = PersistentDict()  # type -> [ids]

    def register(self, manifest: AdapterManifest) -> str:
        """Register an adapter manifest.

        Args:
            manifest: Adapter manifest to register

        Returns:
            Adapter ID (name:version)
        """
        adapter_id = manifest.id

        # Store manifest
        self._p_adapters[adapter_id] = manifest

        # Update by_name index
        if manifest.name not in self._p_by_name:
            self._p_by_name[manifest.name] = []
        self._p_by_name[manifest.name].append(adapter_id)

        # Update by_type index
        if manifest.adapter_type not in self._p_by_type:
            self._p_by_type[manifest.adapter_type] = []
        self._p_by_type[manifest.adapter_type].append(adapter_id)

        return adapter_id

    def get(self, adapter_id: str) -> AdapterManifest | None:
        """Get adapter manifest by ID.

        Args:
            adapter_id: Adapter ID (name:version)

        Returns:
            Adapter manifest or None
        """
        return self._p_adapters.get(adapter_id)

    def get_latest(self, name: str) -> AdapterManifest | None:
        """Get latest version of an adapter.

        Args:
            name: Adapter name

        Returns:
            Latest manifest or None
        """
        adapter_ids = self._p_by_name.get(name, [])
        if not adapter_ids:
            return None

        # Sort by version and return latest
        versions = [
            (self._p_adapters[aid].version, aid)
            for aid in adapter_ids
        ]
        versions.sort(reverse=True)

        return self._p_adapters[versions[0][1]]

    def list_by_type(self, adapter_type: str) -> list[AdapterManifest]:
        """List all adapters of a given type.

        Args:
            adapter_type: Adapter type (storage, vector, logging, etc.)

        Returns:
            List of adapter manifests
        """
        adapter_ids = self._p_by_type.get(adapter_type, [])
        return [
            self._p_adapters[aid]
            for aid in adapter_ids
        ]

    def list_all(self) -> list[AdapterManifest]:
        """List all registered adapters.

        Returns:
            List of all adapter manifests
        """
        return list(self._p_adapters.values())

    def search(
        self,
        name: str | None = None,
        adapter_type: str | None = None,
        author: str | None = None,
    ) -> list[AdapterManifest]:
        """Search for adapters matching criteria.

        Args:
            name: Filter by name (optional)
            adapter_type: Filter by type (optional)
            author: Filter by author (optional)

        Returns:
            List of matching adapters
        """
        results = list(self._p_adapters.values())

        if name:
            results = [m for m in results if name.lower() in m.name.lower()]

        if adapter_type:
            results = [m for m in results if m.adapter_type == adapter_type]

        if author:
            results = [m for m in results if m.author and author.lower() in m.author.lower()]

        return results

    def __getstate__(self) -> dict:
        return {
            "adapters": self._p_adapters,
            "by_name": self._p_by_name,
            "by_type": self._p_by_type,
        }

    def __setstate__(self, state: dict) -> None:
        self._p_adapters = state["adapters"]
        self._p_by_name = state["by_name"]
        self._p_by_type = state["by_type"]
```

### 6.2 Oneiric-MCP Compatible Server

**Create `mcp/oneiric_server.py`:**
```python
"""Oneiric-MCP compatible server using Durus as backend.

This implements the same interface as oneiric-mcp but uses Durus
for persistent adapter storage and distribution.
"""

from mcp.server.fastmcp import FastMCP
from durus.connection import Connection
from durus.storage.file import FileStorage
from durus.serialize.msgspec import MsgspecSerializer
from durus.oneiric.adapter_registry import AdapterRegistry, AdapterManifest
import typer
import json

app = FastMCP("oneiric-durus")

# Global connection and registry
_conn: Connection | None = None
_registry: AdapterRegistry | None = None


def _ensure_connection():
    """Ensure connection is established."""
    global _conn, _registry
    if _conn is None:
        storage = FileStorage("oneiric_adapters.durus")
        serializer = MsgspecSerializer()
        _conn = Connection(storage, cache_size=10000, serializer=serializer)
        root = _conn.get_root()

        # Initialize registry if doesn't exist
        if "registry" not in root:
            root["registry"] = AdapterRegistry()
            _conn.commit()

        _registry = root["registry"]


@app.tool()
def oneiric_register_adapter(
    name: str,
    version: str,
    adapter_type: str,
    schema: str,  # JSON string
    code: str,
    dependencies: str | None = None,  # JSON string
    author: str | None = None,
    description: str | None = None,
) -> str:
    """Register a new Oneiric adapter.

    Args:
        name: Adapter name
        version: Semantic version (e.g., "1.0.0")
        adapter_type: Adapter type (storage, vector, logging, etc.)
        schema: Pydantic schema as JSON string
        code: Adapter source code
        dependencies: Optional dependencies as JSON string
        author: Optional author name/email
        description: Optional description

    Returns:
        Adapter ID (name:version)
    """
    _ensure_connection()

    # Parse JSON inputs
    schema_dict = json.loads(schema)
    dependencies_list = json.loads(dependencies) if dependencies else None

    # Create manifest
    manifest = AdapterManifest(
        name=name,
        version=version,
        adapter_type=adapter_type,
        schema=schema_dict,
        code=code,
        dependencies=dependencies_list,
        author=author,
        description=description,
    )

    # Register
    adapter_id = _registry.register(manifest)

    # Commit
    _conn.commit()

    return f"Registered adapter: {adapter_id}"


@app.tool()
def oneiric_get_adapter(
    name: str,
    version: str | None = None,
) -> str:
    """Get adapter manifest and code.

    Args:
        name: Adapter name
        version: Optional version (gets latest if not specified)

    Returns:
        JSON string with adapter manifest and code
    """
    _ensure_connection()

    if version:
        manifest = _registry.get(f"{name}:{version}")
    else:
        manifest = _registry.get_latest(name)

    if manifest is None:
        raise ValueError(f"Adapter not found: {name}" + (f":{version}" if version else ""))

    return json.dumps({
        "id": manifest.id,
        "name": manifest.name,
        "version": manifest.version,
        "adapter_type": manifest.adapter_type,
        "schema": manifest.schema,
        "code": manifest.code,
        "dependencies": manifest.dependencies,
        "author": manifest.author,
        "description": manifest.description,
        "created_at": manifest.created_at,
        "code_hash": manifest.code_hash,
    })


@app.tool()
def oneiric_list_adapters(
    adapter_type: str | None = None,
) -> str:
    """List registered adapters.

    Args:
        adapter_type: Optional filter by adapter type

    Returns:
        JSON array of adapter summaries
    """
    _ensure_connection()

    if adapter_type:
        manifests = _registry.list_by_type(adapter_type)
    else:
        manifests = _registry.list_all()

    summaries = [
        {
            "id": m.id,
            "name": m.name,
            "version": m.version,
            "adapter_type": m.adapter_type,
            "author": m.author,
            "description": m.description,
        }
        for m in manifests
    ]

    return json.dumps(summaries)


@app.tool()
def oneiric_search_adapters(
    query: str,
    adapter_type: str | None = None,
) -> str:
    """Search for adapters.

    Args:
        query: Search query (matches name, description, author)
        adapter_type: Optional filter by adapter type

    Returns:
        JSON array of matching adapters
    """
    _ensure_connection()

    manifests = _registry.search(name=query, adapter_type=adapter_type)

    results = [
        {
            "id": m.id,
            "name": m.name,
            "version": m.version,
            "adapter_type": m.adapter_type,
            "author": m.author,
            "description": m.description,
        }
        for m in manifests
    ]

    return json.dumps(results)


@app.tool()
def oneiric_get_adapter_types() -> str:
    """Get list of all adapter types.

    Returns:
        JSON array of adapter types
    """
    _ensure_connection()

    # Get all manifests and extract unique types
    manifests = _registry.list_all()
    types = sorted(set(m.adapter_type for m in manifests))

    return json.dumps(types)


@app.tool()
def oneiric_validate_adapter(code: str) -> str:
    """Validate adapter code without registering.

    Args:
        code: Adapter source code to validate

    Returns:
        JSON string with validation results
    """
    # Basic validation
    results = {
        "valid": True,
        "errors": [],
        "warnings": [],
    }

    # Check for required patterns
    if "class" not in code:
        results["valid"] = False
        results["errors"].append("Missing class definition")

    if "def " not in code:
        results["warnings"].append("No functions defined")

    # Check for common Oneiric patterns
    if "StorageBase" in code or "VectorBase" in code:
        results["warnings"].append("Extends Oneiric base class (good)")

    return json.dumps(results)


# Alternative: Standalone server entry point
if __name__ == "__main__":
    import mcp.server.cli

    # Run with standard MCP CLI
    mcp.server.cli.run()
```

### 6.3 Durus as Oneiric Storage Backend

**Create `oneiric/storage_backend.py`:**
```python
"""Oneiric storage backend using Durus.

Implements Oneiric StorageBase interface using Durus for persistence.
Can be used as storage for Oneiric configuration, state, etc.
"""

from oneiric.adapters.storage import StorageBase
from durus.connection import Connection
from durus.storage.file import FileStorage
from durus.serialize.msgspec import MsgspecSerializer
from pathlib import Path
from typing import Any, Iterator

class DurusOneiricStorage(StorageBase):
    """Durus-based storage for Oneiric.

    Features:
    - Persistent configuration storage
    - Schema versioning
    - Fast key-value access
    - Transactional updates
    - Automatic caching
    """

    def __init__(
        self,
        db_path: str | Path = "oneiric_state.durus",
        cache_size: int = 100000,
    ):
        """Initialize Durus storage backend.

        Args:
            db_path: Path to Durus database
            cache_size: Object cache size
        """
        self.storage = FileStorage(str(db_path))
        self.serializer = MsgspecSerializer()
        self.connection = Connection(
            self.storage,
            cache_size=cache_size,
            serializer=self.serializer,
        )
        self.root = self.connection.get_root()

        # Initialize Oneiric storage namespace
        if "oneiric" not in self.root:
            self.root["oneiric"] = {}
            self.connection.commit()

    def get(self, key: str, default: Any = None) -> Any:
        """Get value by key."""
        return self.root["oneiric"].get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set value by key."""
        self.root["oneiric"][key] = value
        self.connection.commit()

    def delete(self, key: str) -> None:
        """Delete key."""
        if key in self.root["oneiric"]:
            del self.root["oneiric"][key]
            self.connection.commit()

    def exists(self, key: str) -> bool:
        """Check if key exists."""
        return key in self.root["oneiric"]

    def keys(self) -> Iterator[str]:
        """Iterate over all keys."""
        return iter(self.root["oneiric"].keys())

    def items(self) -> Iterator[tuple[str, Any]]:
        """Iterate over all key-value pairs."""
        return iter(self.root["oneiric"].items())

    def close(self) -> None:
        """Close connection."""
        self.connection.abort()
```

### 6.4 Critical Oneiric Integration Files

| File | Type | Priority |
|------|------|----------|
| `oneiric/adapter_registry.py` | NEW | HIGH |
| `mcp/oneiric_server.py` | NEW | HIGH |
| `oneiric/storage_backend.py` | NEW | HIGH |

---
```python
"""Oneiric storage adapter for Durus.

Integrates Durus as a storage backend for Oneiric configuration
and state persistence in the Mahavishnu ecosystem.
"""

from oneiric.adapters.storage import StorageBase
from durus.connection import Connection
from durus.storage.file import FileStorage
from durus.serialize.msgspec import MsgspecSerializer
from pathlib import Path
from typing import Any

class DurusStorageAdapter(StorageBase):
    """Oneiric storage adapter using Durus.

    Provides persistent object storage for:
    - Workflow state checkpointing
    - Configuration persistence
    - Session data storage
    - Agent memory persistence
    """

    def __init__(
        self,
        db_path: str | Path = "mahavishnu.durus",
        cache_size: int = 100000,
    ):
        """Initialize Durus storage adapter.

        Args:
            db_path: Path to Durus database file
            cache_size: Object cache size
        """
        self.storage = FileStorage(str(db_path))
        self.serializer = MsgspecSerializer()
        self.connection = Connection(
            self.storage,
            cache_size=cache_size,
            serializer=self.serializer,
        )
        self.root = self.connection.get_root()

    def get(self, key: str, default: Any = None) -> Any:
        """Get value by key."""
        return self.root.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set value by key."""
        self.root[key] = value
        self.connection.commit()

    def delete(self, key: str) -> None:
        """Delete key."""
        if key in self.root:
            del self.root[key]
            self.connection.commit()

    def exists(self, key: str) -> bool:
        """Check if key exists."""
        return key in self.root

    def keys(self) -> list[str]:
        """Get all keys."""
        return list(self.root.keys())

    def close(self) -> None:
        """Close connection."""
        self.connection.abort()
```

### 6.2 MCP Server for Durus

**Create `mcp/server.py`:**
```python
"""MCP server for Durus database operations.

Provides tool-based access to Durus for Mahavishnu and other MCP clients.
"""

from mcp.server.fastmcp import FastMCP
from durus.connection import Connection
from durus.storage.file import FileStorage
from durus.serialize.msgspec import MsgspecSerializer
import typer

app = FastMCP("durus")

# Global connection
_conn: Connection | None = None

@app.tool()
def durus_connect(
    db_path: str = typer.Argument(default="mahavishnu.durus"),
    cache_size: int = typer.Argument(default=100000),
) -> str:
    """Connect to Durus database."""
    global _conn

    storage = FileStorage(db_path)
    serializer = MsgspecSerializer()
    _conn = Connection(storage, cache_size=cache_size, serializer=serializer)

    return f"Connected to Durus database: {db_path}"

@app.tool()
def durus_get(key: str) -> str:
    """Get value from Durus by key.

    Args:
        key: The key to retrieve

    Returns:
        JSON string of the value
    """
    if _conn is None:
        raise RuntimeError("Not connected to Durus. Call durus_connect first.")

    root = _conn.get_root()
    value = root.get(key)

    import json
    return json.dumps({"key": key, "value": str(value)})

@app.tool()
def durus_set(key: str, value: str) -> str:
    """Set value in Durus.

    Args:
        key: The key to set
        value: The value to set (JSON string)

    Returns:
        Success message
    """
    if _conn is None:
        raise RuntimeError("Not connected to Durus. Call durus_connect first.")

    import json
    root = _conn.get_root()
    root[key] = json.loads(value)
    _conn.commit()

    return f"Set {key} in Durus"

@app.tool()
def durus_list() -> str:
    """List all keys in Durus root.

    Returns:
        JSON array of keys
    """
    if _conn is None:
        raise RuntimeError("Not connected to Durus. Call durus_connect first.")

    root = _conn.get_root()
    keys = list(root.keys())

    import json
    return json.dumps({"keys": keys})

@app.tool()
def durus_checkpoint(
    workflow_id: str,
    state: dict,
) -> str:
    """Save workflow checkpoint.

    Args:
        workflow_id: Workflow identifier
        state: Workflow state dictionary

    Returns:
        Success message
    """
    if _conn is None:
        raise RuntimeError("Not connected to Durus. Call durus_connect first.")

    root = _conn.get_root()

    # Create checkpoints dict if doesn't exist
    if "checkpoints" not in root:
        root["checkpoints"] = {}

    root["checkpoints"][workflow_id] = {
        "state": state,
        "timestamp": time.time(),
    }
    _conn.commit()

    return f"Saved checkpoint for workflow: {workflow_id}"

@app.tool()
def durus_restore_checkpoint(workflow_id: str) -> str:
    """Restore workflow checkpoint.

    Args:
        workflow_id: Workflow identifier

    Returns:
        JSON string of checkpoint state
    """
    if _conn is None:
        raise RuntimeError("Not connected to Durus. Call durus_connect first.")

    root = _conn.get_root()

    if "checkpoints" not in root or workflow_id not in root["checkpoints"]:
        raise ValueError(f"Checkpoint not found: {workflow_id}")

    checkpoint = root["checkpoints"][workflow_id]

    import json
    return json.dumps(checkpoint)
```

### 6.3 Workflow State Persistence

**Create `mahavishnu/workflow_state.py`:**
```python
"""Workflow state persistence using Durus.

Integrates with Mahavishnu workflow orchestration to provide
durable state storage and checkpointing.
"""

from durus.connection import Connection
from durus.storage.file import FileStorage
from durus.serialize.msgspec import MsgspecSerializer
from durus.collections.dict import PersistentDict
from datetime import datetime
import time
from typing import Any

class WorkflowStateStore:
    """Persistent workflow state storage using Durus.

    Features:
    - Checkpoint-based state persistence
    - Transactional state updates
    - Automatic state versioning
    - Fast recovery from checkpoints
    - Multi-workflow isolation
    """

    def __init__(
        self,
        db_path: str = "mahavishnu_workflows.durus",
        cache_size: int = 100000,
    ):
        """Initialize workflow state store.

        Args:
            db_path: Path to Durus database
            cache_size: Object cache size
        """
        self.storage = FileStorage(db_path)
        self.serializer = MsgspecSerializer()
        self.connection = Connection(
            self.storage,
            cache_size=cache_size,
            serializer=self.serializer,
        )
        self.root = self.connection.get_root()

        # Initialize workflow storage
        if "workflows" not in self.root:
            self.root["workflows"] = PersistentDict()
            self.connection.commit()

    def save_checkpoint(
        self,
        workflow_id: str,
        state: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Save workflow checkpoint.

        Args:
            workflow_id: Workflow identifier
            state: Workflow state
            metadata: Optional metadata (timestamp, node, etc.)

        Returns:
            Checkpoint ID
        """
        workflows = self.root["workflows"]

        # Create workflow entry if doesn't exist
        if workflow_id not in workflows:
            workflows[workflow_id] = PersistentDict()

        workflow = workflows[workflow_id]

        # Generate checkpoint ID
        checkpoint_id = f"{workflow_id}_{int(time.time() * 1000)}"

        # Save checkpoint
        workflow[checkpoint_id] = {
            "state": state,
            "metadata": {
                **(metadata or {}),
                "timestamp": time.time(),
                "checkpoint_id": checkpoint_id,
            },
        }

        # Update latest checkpoint reference
        workflow["latest_checkpoint"] = checkpoint_id

        self.connection.commit()

        return checkpoint_id

    def load_checkpoint(
        self,
        workflow_id: str,
        checkpoint_id: str | None = None,
    ) -> dict[str, Any]:
        """Load workflow checkpoint.

        Args:
            workflow_id: Workflow identifier
            checkpoint_id: Checkpoint ID (uses latest if None)

        Returns:
            Checkpoint data with state and metadata
        """
        workflows = self.root["workflows"]

        if workflow_id not in workflows:
            raise ValueError(f"Workflow not found: {workflow_id}")

        workflow = workflows[workflow_id]

        # Use latest if not specified
        if checkpoint_id is None:
            checkpoint_id = workflow.get("latest_checkpoint")
            if checkpoint_id is None:
                raise ValueError(f"No checkpoints found for workflow: {workflow_id}")

        if checkpoint_id not in workflow:
            raise ValueError(f"Checkpoint not found: {checkpoint_id}")

        return workflow[checkpoint_id]

    def list_checkpoints(self, workflow_id: str) -> list[dict[str, Any]]:
        """List all checkpoints for a workflow.

        Args:
            workflow_id: Workflow identifier

        Returns:
            List of checkpoint metadata
        """
        workflows = self.root["workflows"]

        if workflow_id not in workflows:
            return []

        workflow = workflows[workflow_id]
        checkpoints = []

        for key, value in workflow.items():
            if key == "latest_checkpoint":
                continue

            if isinstance(value, dict) and "metadata" in value:
                checkpoints.append(value["metadata"])

        # Sort by timestamp descending
        checkpoints.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

        return checkpoints

    def delete_workflow(self, workflow_id: str) -> None:
        """Delete workflow and all checkpoints.

        Args:
            workflow_id: Workflow identifier
        """
        workflows = self.root["workflows"]

        if workflow_id in workflows:
            del workflows[workflow_id]
            self.connection.commit()

    def get_active_workflows(self) -> list[str]:
        """Get list of active workflow IDs.

        Returns:
            List of workflow IDs
        """
        workflows = self.root["workflows"]
        return list(workflows.keys())

    def close(self) -> None:
        """Close connection."""
        self.connection.abort()
```

### 6.4 Vector/Embeddings Integration

**Create `mahavishnu/vector_integration.py`:**
```python
"""Vector search integration for Durus.

Provides compatibility with pgvector/AgentDB for semantic search
in the Mahavishnu ecosystem.
"""

import numpy as np
from typing import Any
from durus.persistent import Persistent

class VectorData(Persistent):
    """Persistent vector data with metadata.

    Used for storing embeddings and vector data that can be
    indexed by external vector databases (pgvector, AgentDB).
    """

    def __init__(
        self,
        vector: list[float] | np.ndarray,
        metadata: dict[str, Any] | None = None,
        id: str | None = None,
    ):
        """Initialize vector data.

        Args:
            vector: Embedding vector
            metadata: Optional metadata
            id: Optional identifier
        """
        self._p_vector = np.array(vector)
        self._p_metadata = metadata or {}
        self._p_id = id

    @property
    def vector(self) -> np.ndarray:
        """Get vector."""
        return self._p_vector

    @property
    def metadata(self) -> dict[str, Any]:
        """Get metadata."""
        return self._p_metadata

    @property
    def id(self) -> str | None:
        """Get ID."""
        return self._p_id

    def __getstate__(self) -> dict:
        """Get state for serialization."""
        return {
            "vector": self._p_vector.tolist(),
            "metadata": self._p_metadata,
            "id": self._p_id,
        }

    def __setstate__(self, state: dict) -> None:
        """Set state from deserialization."""
        self._p_vector = np.array(state["vector"])
        self._p_metadata = state["metadata"]
        self._p_id = state["id"]


class VectorCollection(Persistent):
    """Collection of vectors with export capability.

    Provides seamless integration with pgvector/AgentDB by
    exporting vectors for bulk indexing.
    """

    def __init__(self):
        self._p_vectors: dict[str, VectorData] = {}

    def add(self, vector_data: VectorData) -> None:
        """Add vector to collection.

        Args:
            vector_data: Vector data to add
        """
        self._p_vectors[vector_data.id or str(id(vector_data))] = vector_data

    def get(self, id: str) -> VectorData | None:
        """Get vector by ID.

        Args:
            id: Vector identifier

        Returns:
            Vector data or None
        """
        return self._p_vectors.get(id)

    def export_for_pgvector(self) -> tuple[list[list[float]], list[dict]]:
        """Export vectors for pgvector bulk insert.

        Returns:
            Tuple of (vectors, metadata_records)
        """
        vectors = []
        metadata = []

        for vector_data in self._p_vectors.values():
            vectors.append(vector_data.vector.tolist())
            metadata.append({
                "id": vector_data.id,
                **vector_data.metadata,
            })

        return vectors, metadata

    def export_for_agentdb(self) -> list[dict]:
        """Export vectors for AgentDB bulk insert.

        Returns:
            List of records with vector and metadata
        """
        records = []

        for vector_data in self._p_vectors.values():
            records.append({
                "id": vector_data.id,
                "vector": vector_data.vector.tolist(),
                "metadata": vector_data.metadata,
            })

        return records

    def __getstate__(self) -> dict:
        """Get state for serialization."""
        return {
            "vectors": self._p_vectors,
        }

    def __setstate__(self, state: dict) -> None:
        """Set state from deserialization."""
        self._p_vectors = state["vectors"]
```

### 6.5 Critical Mahavishnu Integration Files

| File | Type | Priority |
|------|------|----------|
| `config/oneiric_adapter.py` | NEW | HIGH |
| `mcp/server.py` | NEW | HIGH |
| `mahavishnu/workflow_state.py` | NEW | HIGH |
| `mahavishnu/vector_integration.py` | NEW | MEDIUM |

---

## Phase 5: Pydantic Validation (Week 9)

### 5.1 Create Validation Models

**Create `validation/models.py`:**
```python
from pydantic import BaseModel, Field, ConfigDict
from typing import Any
from durus.core.persistent import Persistent

class PersistentModel(BaseModel):
    """Base Pydantic model for persistent objects."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=True,
        frozen=False,  # Allow mutation
    )

    oid: str = Field(default="", description="Object ID")
    _p_status: int = Field(
        default=0,
        description="Object status: -1=ghost, 0=saved, 1=unsaved",
    )

    def to_persistent(self) -> Persistent:
        """Convert to Persistent instance."""
        obj = Persistent()
        obj._p_oid = self.oid
        obj._p_status = self._p_status
        for key, value in self.model_dump(exclude={'oid', '_p_status'}).items():
            setattr(obj, key, value)
        return obj

    @classmethod
    def from_persistent(cls, obj: Persistent) -> "PersistentModel":
        """Create from Persistent instance."""
        data = obj.__getstate__()
        data['oid'] = getattr(obj, '_p_oid', '')
        data['_p_status'] = getattr(obj, '_p_status', 0)
        return cls(**data)
```

### 5.2 Validation Middleware

**Create `validation/validators.py`:**
```python
from typing import Any, Callable
from functools import wraps
from pydantic import ValidationError

def validate_persistent(model_class: type):
    """Decorator to validate persistent objects."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, obj: Persistent, *args, **kwargs):
            try:
                model = model_class.from_persistent(obj)
                validated = model.model_validate(model.model_dump())
                return func(self, validated.to_persistent(), *args, **kwargs)
            except ValidationError as e:
                raise ValueError(f"Validation failed: {e}")

        return wrapper
    return decorator
```

### 5.3 Critical Validation Files

| File | Type | Priority |
|------|------|----------|
| `validation/models.py` | NEW | MEDIUM |
| `validation/validators.py` | NEW | LOW |
| `validation/__init__.py` | NEW | LOW |

---

## Phase 6: ZODB Compatibility (Week 10)

### 6.1 Create Compatibility Layer

**Create `compatibility/zodb.py`:**
```python
"""
ZODB compatibility layer for drop-in replacement.
"""
from typing import Any
from durus.connection import Connection as DurusConnection
from durus.storage.base import Storage as DurusStorage

# ZODB-like imports
class DB:
    """ZODB DB compatibility wrapper."""

    def __init__(
        self,
        storage: DurusStorage,
        cache_size: int = 100000,
    ):
        self._durus_storage = storage
        self._cache_size = cache_size

    def open(self) -> 'Connection':
        """Open a connection (ZODB-style)."""
        return Connection(self._durus_storage, cache_size=self._cache_size)

    def close(self) -> None:
        """Close the database."""
        self._durus_storage.close()

class Connection:
    """ZODB Connection compatibility wrapper."""

    def __init__(self, storage: DurusStorage, cache_size: int = 100000):
        self._conn = DurusConnection(storage, cache_size=cache_size)

    def root(self) -> Any:
        """Get root object (ZODB-style property)."""
        return self._conn.get_root()

    def get(self, oid: str) -> Any:
        """Get object by ID."""
        return self._conn.get(oid)

    def commit(self) -> None:
        """Commit transaction."""
        self._conn.commit()

    def abort(self) -> None:
        """Abort transaction."""
        self._conn.abort()

    def sync(self) -> None:
        """Sync with storage."""
        self._conn.sync()

    def close(self) -> None:
        """Close connection."""
        # Durus connections don't have explicit close
        pass

    def db(self) -> DB:
        """Get database (ZODB-style)."""
        # Store reference to DB on open
        return self._db
```

### 6.2 ZODB Mapping

| ZODB API | Durus Equivalent |
|----------|------------------|
| `DB(Storage)` | `DB(DurusStorage)` |
| `connection = db.open()` | `connection = Connection(storage)` |
| `root = connection.root()` | `root = connection.get_root()` |
| `connection.commit()` | `connection.commit()` (same) |
| `connection.abort()` | `connection.abort()` (same) |
| `connection.sync()` | `connection.sync()` (same) |
| `transaction.commit()` | `connection.commit()` |

### 6.3 Critical ZODB Files

| File | Type | Priority |
|------|------|----------|
| `compatibility/zodb.py` | NEW | MEDIUM |
| `compatibility/__init__.py` | NEW | LOW |

---

## Phase 7: Testing & Documentation (Weeks 11-12)

### 7.1 Update Tests

**Test Structure:**
```
test/
├── unit/                        # Unit tests
│   ├── test_core/
│   │   ├── test_connection.py
│   │   └── test_persistent.py
│   ├── test_storage/
│   │   ├── test_file.py
│   │   ├── test_sqlite.py
│   │   └── test_client.py
│   ├── test_serialize/
│   │   ├── test_pickle.py
│   │   ├── test_msgspec.py
│   │   └── test_signing.py
│   └── test_collections/
│       ├── test_dict.py
│       ├── test_list.py
│       ├── test_set.py
│       └── test_btree.py
│
├── integration/                 # Integration tests
│   ├── test_connection_flow.py
│   ├── test_transaction.py
│   └── test_conflicts.py
│
├── compatibility/               # Compatibility tests
│   ├── test_zodb_compat.py
│   └── test_legacy_api.py
│
└── conftest.py                  # Shared fixtures
```

**Fixtures:**
```python
# test/conftest.py
import pytest
from durus.core.connection import Connection
from durus.storage.memory import MemoryStorage
from durus.serialize.pickle import PickleSerializer
from durus.serialize.msgspec import MsgspecSerializer

@pytest.fixture
def memory_storage():
    """Memory storage for testing."""
    return MemoryStorage()

@pytest.fixture
def pickle_connection(memory_storage):
    """Connection with pickle serializer."""
    return Connection(memory_storage, serializer=PickleSerializer())

@pytest.fixture
def msgspec_connection(memory_storage):
    """Connection with msgspec serializer."""
    return Connection(memory_storage, serializer=MsgspecSerializer())
```

### 7.2 Documentation Updates

**Files to Update:**
1. `README.md` - Update with new architecture
2. `MIGRATION.md` - Migration guide from old to new
3. `docs/architecture.md` - Architecture overview
4. `docs/api.md` - API documentation
5. `docs/configuration.md` - Configuration reference
6. `docs/zodb_compat.md` - ZODB compatibility guide

### 7.3 Testing Coverage Goals

- Maintain current 22% coverage minimum
- Target 40%+ coverage for new code
- Critical paths (serialization, storage): 80%+ coverage

---

## Implementation Order Summary

### Week 1-2: Phase 1 - Structure
1. Create new directory structure
2. Move files to new locations
3. Update all imports
4. Add `__init__.py` files
5. Test reorganization

### Week 3-4: Phase 2 - Type Hints
1. Add type hints to core files
2. Define protocols for interfaces
3. Add type checking to CI
4. Fix type errors

### Week 5-6: Phase 3 - Oneiric
1. Add configuration system
2. Implement structured logging
3. Create modern CLI with typer
4. Add admin shell

### Week 7-8: Phase 4 - Serialization
1. Create serializer adapter
2. Implement msgspec serializer
3. Add signing serializer
4. Update Connection to use adapters

### Week 9: Phase 5 - Validation
1. Create Pydantic models
2. Add validation middleware
3. Integrate with Connection

### Week 10: Phase 6 - ZODB
1. Create ZODB compatibility layer
2. Write compatibility tests
3. Document ZODB mapping

### Week 11-12: Phase 7 - Testing & Docs
1. Reorganize test structure
2. Update all tests
3. Write documentation
4. Create migration guide

---

## Dependencies to Add

```toml
[project.dependencies]
oneiric = ">=1.0.0"
msgspec = ">=0.18.0"
pydantic = ">=2.0.0"
typer = { extras = ["all"], version = ">=0.9.0" }

[project.optional-dependencies]
zodb = ["ZODB>=5.0"]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "pytest-asyncio>=0.21",
    "pytest-benchmark>=4.0",
    "ruff>=0.1.0",
    "pyright>=1.1.0",
    "mypy>=1.5.0",
]
```

---

## Verification Steps

### After Each Phase
```bash
# 1. Check type hints
pyright durus/

# 2. Run linter
ruff check durus/

# 3. Run tests
pytest test/ -v

# 4. Check coverage
pytest test/ --cov=durus --cov-report=term-missing

# 5. Import test
python -c "import durus; print(durus.__version__)"
```

### Final Verification
```bash
# All tests pass
pytest test/ -xvs

# Type checking passes
pyright durus/
mypy durus/

# Linting passes
ruff check durus/
ruff format --check durus/

# Coverage acceptable
pytest test/ --cov=durus --cov-report=html

# Documentation builds
# (if using sphinx/docs tooling)

# Performance benchmark
pytest test/ --benchmark-only
```

---

## MCP Server Architecture Decision

Durus provides **two complementary MCP servers** for different purposes:

### 1. Durus MCP Server (`mcp/server.py`)
**Purpose:** General database operations

**Target Users:** Applications using Durus as a database

**Key Tools:**
- `durus_connect()` - Connect to database
- `durus_get()` / `durus_set()` - CRUD operations
- `durus_list()` - List keys
- `durus_checkpoint()` / `durus_restore_checkpoint()` - Workflow state persistence
- `durus_query()` - Query objects (future)

**Use Cases:**
- Mahavishnu workflow checkpointing
- General data persistence for agents
- Application-level database operations

**Starting Command:**
```bash
mcp-durus-server --port 3030
```

### 2. Oneiric-MCP Compatible Server (`mcp/oneiric_server.py`)
**Purpose:** Oneiric adapter registry and distribution

**Target Users:** Applications needing Oneiric adapters

**Key Tools:**
- `oneiric_register_adapter()` - Register new adapter
- `oneiric_get_adapter()` - Get adapter by name/version
- `oneiric_list_adapters()` - List all adapters
- `oneiric_search_adapters()` - Search adapters
- `oneiric_validate_adapter()` - Validate adapter code

**Use Cases:**
- Centralized adapter distribution
- Adapter version management
- Dynamic adapter loading
- Alternative to oneiric-mcp file-based storage

**Starting Command:**
```bash
mcp-oneiric-durus-server --port 3031
```

### Architecture Rationale

**Why Two Servers?**

1. **Separation of Concerns**
   - Durus server: Database operations (persistence focus)
   - Oneiric server: Adapter management (registry focus)

2. **Independent Deployment**
   - Can run Durus server without Oneiric integration
   - Can use Oneiric server with other storage backends

3. **Clear API Boundaries**
   - Database tools stay focused on data operations
   - Registry tools stay focused on metadata and distribution

4. **Ecosystem Compatibility**
   - Durus server integrates with any MCP client
   - Oneiric server is drop-in compatible with oneiric-mcp

**Alternative: Unified Server**

If a unified approach is preferred, both server implementations can be merged into a single FastMCP app with two "modules":

```python
app = FastMCP("durus-unified")

# Database module
@app.tool()
def durus_connect(...): ...

# Oneiric registry module
@app.tool()
def oneiric_register_adapter(...): ...
```

**Recommendation:** Start with two separate servers for clarity. Can merge later if ecosystem feedback suggests it would be beneficial.

---

## Backward Compatibility

**IMPORTANT:** Per user decision, there is **NO backward compatibility**. This is a clean break from the old API.

### Breaking Changes

The following will **NOT** work in Durus 5.0:

```python
# ❌ Old imports (no longer work)
from durus.connection import Connection
from durus.file_storage import FileStorage
from durus.persistent import Persistent

# ❌ Old pickle-only serialization
# All objects must use msgspec or dill serializer
```

### New Required Imports

```python
# ✅ New imports (required)
from durus import Connection, Persistent, FileStorage
from durus.serialize.msgspec import MsgspecSerializer

# ✅ Explicit serializer selection
conn = Connection(storage, serializer=MsgspecSerializer())
```

### Migration Path

Users must:
1. Update all imports to new structure
2. Choose a serializer (msgspec recommended)
3. Update Connection initialization
4. Test all code with new API

No automatic migration or compatibility layer is provided.

---

## Success Criteria

- [ ] All files moved to new structure
- [ ] All imports updated and working
- [ ] Type hints on all public APIs
- [ ] Oneiric config system integrated
- [ ] Structured logging in place
- [ ] Modern CLI with typer working
- [ ] msgspec serializer functional
- [ ] Object signing implemented
- [ ] Pydantic models created
- [ ] ZODB compatibility layer working
- [ ] All tests passing
- [ ] Coverage ≥ 22%
- [ ] Documentation updated
- [ ] Migration guide complete
- [ ] Two MCP servers operational (database + Oneiric registry)
- [ ] Mahavishnu/Akosha integration functional
- [ ] Clean break from old API (no backward compatibility)
