# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

dhruva is a modern persistent object system for Python - essentially a noSQL database with ACID properties (Atomicity, Consistency, Isolation, Durability). It provides transactional persistence for Python objects through a client/server model optimized for read-heavy workloads with aggressive caching.

**Key Modernization (v5.0):**

- Complete architectural refactoring with layered package structure
- Modern Python 3.13+ type hints throughout
- Multiple serialization backends (msgspec, pickle, dill)
- Oneiric integration for configuration and logging
- MCP server for modern AI/agent workflows
- Enhanced security with proper secret management

## Build and Test Commands

### Installation

```bash
# Install in development mode
pip install -e .

# Install with dev dependencies
pip install -e ".[dev]"
```

### Running Tests

Tests use pytest (modernized from legacy sancho.utest):

```bash
# Run all tests
pytest

# Run specific test file
pytest test/test_connection.py

# Run with coverage
pytest --cov=dhruva --cov-report=html

# Run by markers
pytest -m unit              # Unit tests only
pytest -m "not slow"        # Exclude slow tests
pytest -m integration       # Integration tests only

# Run specific test
pytest test/test_connection.py::test_connection_basic
```

### Quality Checks

```bash
# Run all quality checks via crackerjack
python -m crackerjack check

# Individual checks
python -m crackerjack lint          # Ruff linting
python -m crackerjack format        # Ruff formatting
python -m crackerjack test          # Pytest
python -m crackerjack typecheck     # Pyright (strict mode)
python -m crackerjack security      # Bandit security scan
python -m crackerjack complexity    # Complexity analysis

# Auto-fix issues
python -m crackerjack lint --fix
python -m crackerjack format --fix
```

### Building C Extension

The project includes a C extension (`dhruva/_persistent.c`) for CPython:

```bash
# Build the extension
python setup.py build_ext --inplace
```

On PyPy, the pure Python implementation is used automatically.

### Running the Server/Client

```bash
# Start storage server (uses temporary file by default)
dhruva -s

# Start server with specific file
dhruva -s --file test.dhruva

# Start server on custom port
dhruva -s --port 2973

# Connect to server (interactive console)
dhruva -c

# Connect to server with specific port
dhruva -c --port 2973

# Open file directly (no server)
dhruva -c --file test.dhruva

# Stop server
dhruva -s --stop

# Pack storage (garbage collection)
dhruva -p --file test.dhruva
```

## Architecture

### Modern Package Structure

dhruva 5.0 uses a layered architecture with clear separation of concerns:

```
dhruva/
├── __init__.py                   # Public API exports
├── __main__.py                   # CLI entry point
│
├── core/                         # Core persistence framework
│   ├── connection.py             # Connection & transaction management
│   └── persistent.py             # Persistent base classes
│
├── storage/                      # Storage backends (adapter pattern)
│   ├── base.py                   # Abstract Storage interface
│   ├── file.py                   # FileStorage (default)
│   ├── sqlite.py                 # SQLite storage
│   ├── client.py                 # ClientStorage (network client)
│   └── memory.py                 # MemoryStorage (testing)
│
├── serialize/                    # Serialization layer
│   ├── base.py                   # Serializer interface
│   ├── msgspec.py                # msgspec (default, fast & safe)
│   ├── pickle.py                 # Pickle (backward compat)
│   ├── dill.py                   # Dill (extended capability)
│   └── factory.py                # Serializer creation
│
├── collections/                  # Persistent collection types
│   ├── dict.py                   # PersistentDict
│   ├── list.py                   # PersistentList
│   ├── set.py                    # PersistentSet
│   └── btree.py                  # BTree implementation
│
├── server/                       # Storage server
│   ├── server.py                 # StorageServer implementation
│   └── socket.py                 # Socket management
│
├── mcp/                          # MCP server integration
│   ├── server.py                 # MCP server
│   └── auth.py                   # Authentication
│
├── config/                       # Configuration management
│   ├── loader.py                 # Oneiric config loading
│   └── security.py               # Security settings
│
├── logging/                      # Structured logging
│   └── formatter.py              # Log formatting
│
└── security/                     # Security utilities
    └── oneiric_secrets.py        # Secret management
```

### Core Components

**Connection Layer** (`dhruva/core/connection.py`):

- Manages object cache (LRU with weak references)
- Transaction management via `commit()` and `abort()`
- Default cache size: 10,000 objects (configurable)
- Handles object state transitions (GHOST, SAVED, UNSAVED)

**Persistent Layer** (`dhruva/core/persistent.py`):

- `Persistent`: Base class using `__dict__` for state
- Three object states: `UNSAVED`, `SAVED`, `GHOST` (unloaded)
- C extension (`_persistent.c`) provides fast implementation on CPython
- Automatic change tracking for attributes

**Storage Backends** (`dhruva/storage/`):

- `FileStorage`: Default, append-only journal with on-disk index
- `SqliteStorage`: SQLite-based storage
- `ClientStorage`: Network client for storage server
- `MemoryStorage`: In-memory storage for testing

**Serialization** (`dhruva/serialize/`):

- `MsgspecSerializer`: Default (fast, type-safe, secure)
- `PickleSerializer`: For backward compatibility
- `DillSerializer`: Extended capability (lambdas, nested functions)

**Persistent Collections** (`dhruva/collections/`):

- `PersistentDict`: Dict-like with automatic change tracking
- `PersistentList`: List-like container
- `PersistentSet`: Set-like container
- `BTree`: B-Tree for efficient large-scale indexing (O(log n) operations)

### Storage Server

**StorageServer** (`dhruva/server/server.py`):

- Multi-client server with concurrent read handling
- Single-writer transaction serialization
- Automatic garbage collection with `gcinterval` parameter
- Supports both TCP and Unix domain sockets
- systemd socket activation support
- **TLS/SSL encryption for secure network communication**

### TLS/SSL Security

dhruva 5.0+ includes comprehensive TLS/SSL support for securing client-server communication over untrusted networks.

**Features:**

- TLS 1.2 and 1.3 support
- Certificate validation for server authentication
- Mutual TLS (client certificates) for enhanced security
- Configurable cipher suites and verification modes
- Self-signed certificate generation for testing

**Environment Variable Configuration:**

```bash
# Server TLS
export DHRUVA_TLS_CERTFILE=/path/to/server.crt
export DHRUVA_TLS_KEYFILE=/path/to/server.key
export DHRUVA_TLS_CAFILE=/path/to/ca.crt  # Optional, for mutual TLS

# Client TLS
export DHRUVA_TLS_CAFILE=/path/to/ca.crt  # Required for server verification
export DHRUVA_TLS_CLIENT_CERTFILE=/path/to/client.crt  # Optional, mutual TLS
export DHRUVA_TLS_CLIENT_KEYFILE=/path/to/client.key    # Required with client cert
export DHRUVA_TLS_VERIFY_MODE=required  # none, optional, or required (default)
export DHRUVA_TLS_VERSION=1.3  # Minimum TLS version: 1.2 or 1.3 (default)
```

**Command-Line Usage:**

```bash
# Generate self-signed certificate for testing
dhruva -s --generate-tls-cert localhost

# Start server with TLS
dhruva -s --tls-certfile server.crt --tls-keyfile server.key

# Connect with TLS (server verification)
dhruva -c --host localhost --tls-cafile server.crt

# Connect with mutual TLS
dhruva -c --host localhost \
  --tls-cafile server.crt \
  --tls-certfile client.crt \
  --tls-keyfile client.key

# Pack storage with TLS
dhruva -p --host localhost --tls-cafile server.crt
```

**Programmatic Usage:**

```python
from dhruva import Connection
from dhruva.storage import ClientStorage
from dhruva.security.tls import TLSConfig

# Server
from dhruva.server.server import StorageServer
from dhruva.storage import FileStorage

storage = FileStorage("data.dhruva")
tls_config = TLSConfig(
    certfile="server.crt",
    keyfile="server.key",
    cafile="ca.crt",  # Optional, for mutual TLS
)
server = StorageServer(storage, tls_config=tls_config)
server.serve()

# Client
tls_config = TLSConfig(
    cafile="server.crt",
    client_certfile="client.crt",  # Optional
    client_keyfile="client.key",    # Required with client_certfile
)
storage = ClientStorage(host="localhost", port=2972, tls_config=tls_config)
connection = Connection(storage)
```

**Security Best Practices:**

1. **Production Deployment:**

   - Use certificates from a trusted CA (Let's Encrypt, commercial CA)
   - Enable certificate verification (`DHRUVA_TLS_VERIFY_MODE=required`)
   - Use TLS 1.3 or higher (`DHRUVA_TLS_VERSION=1.3`)
   - Implement mutual TLS for sensitive environments

1. **Testing/Development:**

   - Use `--generate-tls-cert` for quick self-signed certificates
   - Set `DHRUVA_TLS_VERIFY_MODE=none` only for testing
   - Never disable verification in production

1. **Certificate Management:**

   - Keep private keys secure (appropriate file permissions)
   - Rotate certificates before expiration
   - Use separate CA certificates for development and production

**Cryptography Dependency:**
Self-signed certificate generation requires the `cryptography` package:

```bash
pip install cryptography
```

### Transaction Model

Transactions work through the Connection:

- `connection.commit()`: Writes changes to storage, raises `ConflictError` on conflicts
- `connection.abort()`: Discards changes, syncs with storage, manages cache
- Changes to `Persistent` subclass attributes are automatically tracked
- Changes to regular Python containers must use `_p_note_change()` manually

### Object State Management

Persistent objects transition between three states:

- `UNSAVED`: New or modified, not yet stored
- `SAVED`: State matches storage
- `GHOST`: State not loaded (empty `__dict__`, loaded on attribute access)

Accessing attributes on GHOST objects triggers automatic state loading via the Connection.

## Key Implementation Details

### Non-Persistent Container Pattern

When using regular Python containers (dict, list) as attributes of Persistent objects, changes are NOT automatically tracked. You must call `_p_note_change()`:

```python
from dhruva import Persistent

class MyObject(Persistent):
    def __init__(self):
        self.tags = {}  # Regular dict, not persistent

    def add_tag(self, key, value):
        self._p_note_change()  # Must call this!
        self.tags[key] = value
```

Alternatively, use `PersistentDict`, `PersistentList`, or `PersistentSet` which handle this automatically.

### B-Tree Implementation

The `BTree` class (in `dhruva/collections/btree.py`) implements a B-tree data structure:

- Minimum degree (t) = 2
- Supports `collections.abc.MutableMapping` interface
- O(log n) lookups, inserts, deletes
- Maintains `_count` attribute for O(1) `len()` operation

### Serialization Choice

**Recommendations:**

- Use `msgspec` for new databases (fastest, safest, type-safe)
- Use `pickle` only for backward compatibility with Durus 4.x
- Use `dill` only when you need to serialize functions/lambdas
- Never deserialize untrusted data with pickle or dill

### C Extension vs Pure Python

- CPython: Uses `dhruva/_persistent.c` for `PersistentBase` and `ConnectionBase`
- PyPy: Uses pure Python fallback (C extensions are slower on PyPy)
- The C extension optimizes the hot path: `__getattribute__`, `__setattr__`, ghost state transitions

### Cache Management

- Cache uses weak references (`ObjectDictionary` wrapper around `WeakValueDictionary`)
- LRU eviction based on `transaction_serial` timestamp
- Recent objects held in hard references during active transactions
- Automatic shrinking when cache size exceeds 2× target

## Common Patterns

### Creating Persistent Classes

```python
from dhruva import Persistent, Connection, FileStorage

class User(Persistent):
    def __init__(self, name: str):
        self.name = name
        self.email = None

# Usage
connection = Connection(FileStorage("users.dhruva"))
root = connection.get_root()
root["users"] = {}
root["users"]["john"] = User("John Doe")
connection.commit()
```

### Working with Direct File Access

```python
from dhruva import Connection

# Connection can take a string path directly
connection = Connection("mydata.dhruva")
root = connection.get_root()
```

### Using Different Storage Backends

```python
from dhruva import Connection
from dhruva.storage import FileStorage, SqliteStorage, ClientStorage

# File storage (default)
connection = Connection(FileStorage("data.dhruva"))

# SQLite storage
connection = Connection(SqliteStorage("data.db"))

# Network storage
connection = Connection(ClientStorage(address=("localhost", 2972)))
```

### Garbage Collection

```python
# Manual packing (removes unreachable objects)
connection.pack()

# Server-side automatic GC
dhruva -s --gcbytes 1000000  # Pack after 1MB of changes
```

### Using Persistent Collections

```python
from dhruva import Connection, PersistentDict, PersistentList

connection = Connection("data.dhruva")
root = connection.get_root()

# These handle change tracking automatically
root["users"] = PersistentDict()
root["logs"] = PersistentList()

root["users"]["alice"] = {"email": "alice@example.com"}
root["logs"].append("User alice created")

connection.commit()
```

## Testing

Tests use pytest with shared fixtures from `test/conftest.py`:

```python
import pytest
from dhruva import Connection, Persistent

def test_something(connection):
    """Uses memory_storage fixture by default."""
    root = connection.get_root()
    root["test"] = "value"
    connection.commit()
    assert root["test"] == "value"

def test_with_file_storage(file_connection):
    """Uses temp_file_storage fixture."""
    root = file_connection.get_root()
    # Test with file-based persistence
```

### Available Fixtures

- `memory_storage`: Fresh MemoryStorage instance
- `temp_file_storage`: Temporary FileStorage (auto-cleanup)
- `connection`: Connection with MemoryStorage
- `file_connection`: Connection with FileStorage

### Test Markers

Tests use pytest markers:

- `unit`: Unit tests
- `integration`: Integration tests
- `e2e`: End-to-end tests
- `security`: Security-focused tests
- `performance`: Performance tests
- `slow`: Slow tests (>2s)
- `benchmark`: Benchmark tests

## Configuration

dhruva uses Oneiric for configuration management. Configuration is loaded from:

1. Environment variables
1. Configuration files (YAML/TOML)
1. Runtime defaults

### Example Configuration

```yaml
# dhruva.yaml
storage:
  backend: file
  path: /var/lib/dhruva/data.dhruva

server:
  host: localhost
  port: 2972
  gcbytes: 1000000

serialization:
  backend: msgspec  # or pickle, dill

logging:
  level: INFO
  format: structured
```

## Security Considerations

### Serialization Security

- **msgspec**: Safe for untrusted data (default)
- **pickle**: Vulnerable to arbitrary code execution - use only with trusted data
- **dill**: Even more vulnerable - avoid with untrusted data

### Secret Management

dhruva integrates with Oneiric for secret management:

- Secrets are loaded from environment variables or secret stores
- Never hardcode secrets in configuration files
- Use `dhruva.config.security` for secure configuration handling

### Network Security

When using ClientStorage:

- Use Unix domain sockets for local communication (faster, more secure)
- Use TLS/SSL for TCP sockets in production
- Implement proper authentication via the MCP server

## MCP Integration

dhruva includes an MCP (Model Context Protocol) server for AI/agent workflows:

```python
from dhruva.mcp import create_server

server = create_server(config="dhruva.yaml")
server.run()
```

The MCP server provides:

- Query operations
- Transaction management
- Schema inspection
- Authentication and authorization

## Migration from Durus 4.x

Key changes in dhruva 5.0:

1. **Package structure**: Flat `durus/` → Layered `dhruva/` with subpackages
1. **Imports**: `from durus.X` → `from dhruva.X` or `from dhruva.subpackage.X`
1. **Serialization**: Pickle-only → msgspec default (pickle still available)
1. **Configuration**: No config → Oneiric-based configuration
1. **Testing**: sancho.utest → pytest
1. **Type hints**: None → Full type hints (Python 3.13+)

### Import Migration

```python
# Old (Durus 4.x)
from durus.connection import Connection
from durus.file_storage import FileStorage
from durus.persistent import Persistent

# New (dhruva 5.0)
from dhruva import Connection, Persistent
from dhruva.storage import FileStorage

# Or more explicit
from dhruva.core import Connection, Persistent
from dhruva.storage.file import FileStorage
```

## Troubleshooting

### Common Issues

**Import Error**: Ensure you've built the C extension if using CPython:

```bash
python setup.py build_ext --inplace
```

**Cache Size**: Adjust cache size for large datasets:

```python
connection = Connection(storage, cache_size=100000)
```

**Transaction Conflicts**: Use `abort()` to sync and retry on `ConflictError`:

```python
try:
    connection.commit()
except ConflictError:
    connection.abort()
    # retry transaction
```

**Performance**: Use msgspec serialization for better performance:

```python
from dhruva.serialize import MsgspecSerializer
storage = FileStorage("data.dhruva", serializer=MsgspecSerializer())
```

<!-- CRACKERJACK_START -->

## Crackerjack Quality Tools

This project uses crackerjack for automated quality checks and code standards.

### Running Quality Checks

```bash
# Run all quality checks
python -m crackerjack check

# Run specific checks
python -m crackerjack lint          # Ruff linting
python -m crackerjack format        # Ruff formatting
python -m crackerjack test          # Pytest with coverage
python -m crackerjack typecheck     # Pyright type checking
python -m crackerjack security      # Bandit security scan
python -m crackerjack complexity    # Complexipy complexity check

# Fix issues automatically
python -m crackerjack lint --fix
python -m crackerjack format --fix

# Run all checks with AI auto-fix
python -m crackerjack run --ai-fix
```

### Configuration

Quality tools are configured in `pyproject.toml`:

- **Ruff**: Linting and formatting (line-length 88, Python 3.13)
- **Pytest**: Testing with parallel coverage support
- **Pyright**: Type checking (strict mode, Python 3.13)
- **Bandit**: Security scanning
- **Codespell**: Typo detection
- **Creosote**: Unused dependency detection
- **Refurb**: Modernization suggestions
- **Complexipy**: Complexity analysis (max 15)

### Test Markers

Tests use pytest markers for categorization:

- `unit`: Unit tests
- `integration`: Integration tests
- `e2e`: End-to-end tests
- `security`: Security-focused tests
- `performance`: Performance and load tests
- `slow`: Slow tests (>2s)
- `benchmark`: Benchmark tests
- `smoke`: Quick smoke tests
- `regression`: Regression tests
- `api`: API endpoint tests

Example usage:

```bash
# Run only unit tests
pytest -m unit

# Run unit and integration tests
pytest -m "unit or integration"

# Exclude slow tests
pytest -m "not slow"
```

### Coverage Requirements

Parallel coverage is enabled for faster test execution:

- Branch coverage enabled
- Reports: terminal, HTML (htmlcov/), JSON
- Excludes tests, `__pycache__`, `__init__.py`

<!-- CRACKERJACK_END -->
