# Changelog

All notable changes to dhara will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.11.2] - 2026-06-15

### Internal

- gitignore: Add backup file patterns to silence checkpoint tool artifacts

## [0.11.0] - 2026-06-03

### Changed

- Complete durus elimination and fix msgspec root causes
- Dhara (quality: 63/100) - 2026-06-03 03:29:44
- Dhara (quality: 63/100) - 2026-06-03 08:22:10
- Dhara (quality: 63/100) - 2026-06-03 09:20:47
- Dhara (quality: 63/100) - 2026-06-03 12:40:08

## [0.11.0] - 2026-06-03

### Removed (0.11.0)

- `dhara.serialize_legacy` module (pickle-based on-disk record format reader/writer)
- `dhara.serialize.adapter` module (re-export shim wrapping the legacy reader)
- `dhara.serialize.dill` module (`DillSerializer` and dill-backed wrapper)
- `dhara.serialize.fallback` module (`FallbackSerializer` and the msgspec/pickle/dill fallback chain)
- `dhara.file_storage2` module (DFS20/Durus 4.x file format reader/writer)
- `PickleSerializer` class (replaced by `MsgpackSerializer`)
- `DillSerializer` class (deleted entirely)
- `FallbackSerializer` class (deleted entirely)
- The DFS20/Durus 4.x on-disk file format (opening one now raises `ValueError`)
- The CWE-502 pickle deserialization attack surface is closed.

## [0.10.0] - 2026-06-02

### Added

- Add async CLI handlers for MCP tool dispatch (Task 20)
- Add async methods to PersistentObject for AsyncConnection compatibility
- Add async-first implementation plan for Dhara
- Add AsyncAdapterRegistry and async adapter tool impls
- Add AsyncBackupCatalog for async backup catalog operations
- Add AsyncBackupScheduler for async scheduler operations (Task 18)
- Add AsyncBackupVerification for async backup verification
- Add AsyncConnection class with async persistence methods
- Add AsyncEcosystemStateStore and wire async KV/event tools
- Add AsyncKVTimeSeriesStore in kv_timeseries.py
- Add AsyncMemoryStorage (native async)
- Add AsyncPostgresStorage using asyncpg
- Add AsyncRestoreManager for async restore operations
- Add AsyncSqliteStorage using aiosqlite
- Add backend selection to DharaMCPServer
- Add BTree skeleton with get
- Add complete AsyncStorage protocol with all methods
- Add storage and cache backend config fields to DharaSettings
- btree: Add \_split_child and \_insert_nonfull for insertion
- btree: Add BNode dataclass with is_leaf helper
- btree: Add BNode is_full, is_big, \_find_position helpers
- btree: Add borrow-first case 3 deletion (borrow, merge, reduce height)
- btree: Add delete, update and leaf-only \_delete_from_node
- btree: Add error classes, is_full and height helpers
- btree: Add items, keys, values iteration
- Complete BTree redesign - passes all quality gates
- dhara: Add PostgresStorageAdapter implementing Storage interface
- dhara: Add RedisCacheAdapter implementing Cache interface
- dhara: Allow external cache injection in Connection
- Revise async-first plan — address 3-agent review findings
- Update storage exports — add AsyncMemoryStorage, AsyncSqliteStorage, AsyncStorage

### Changed

- Dhara (quality: 72/100) - 2026-05-29 05:10:12
- Dhara (quality: 72/100) - 2026-06-01 19:49:08
- Dhara (quality: 72/100) - 2026-06-02 20:25:00
- Dhara (quality: 85/100) - 2026-05-28

### Fixed

- Apply review findings — AsyncConnection factory, shrink_cache await, cache.clear, new_oid shadowing, protocol test, dependency edges
- dhara: Call cache.clear() on abort for uncommitted oids
- dhara: Code quality fixes to RedisCacheAdapter
- dhara: Correct get_stored_pickle() exception handling
- dhara: Correct tuple concatenation in btree.py
- dhara: Critical connection leak in begin() and dead parameter
- dhara: Fix token description and add missing env override tests
- dhara: Lazy adapter init and remove blocking run_until_complete
- dhara: Make AsyncSqliteStorage.new_oid() atomic with asyncio.Lock
- dhara: Prevent initialization race in AsyncConnection.new()
- dhara: Remove duplicate import in test_async_connection.py
- docs: Replace absolute path with relative path for README link
- security: Correct forward reference syntax for fallback_key

### Documentation

- Clarify async storage adapter scope in storage.py (Task 19)
- Confirm MCP tools fully async-wired (Task 22)

### Testing

- btree: Add hypothesis property-based tests
- dhara: Add missing PostgresStorageAdapter tests

### Internal

- Add build/ to gitignore

## [0.9.0] - 2026-05-02

### Added

- backup: Replace custom S3/GCS/Azure storage with Oneiric storage adapters
- Delegate Dhara MCP auth to mcp_common.auth, keep DharaPermission extensions

## [0.8.3] - 2026-04-14

### Internal

- repo: Ignore coverage artifacts

## [0.7.0] - 2026-03-25

### Added

- Unified CLI with security improvements

### Changed

- Rename project from Dhruva to Dhara
- Update core, deps

### Fixed

- Remove duplicate import of time module
- Update FastMCP HTTP transport and add MCP entry point

### Internal

- Add archive/backup directories to gitignore
- Rename dhruva.yaml to dhara.yaml
- Update LICENSE copyright to 2026
- Update mcp-common to 0.9.5

## [Unreleased]

### Added

- FallbackSerializer with whitelist-based security (msgspec → pickle → dill fallback chain)
- Whitelist-based auto-serialization with safety guarantees
- Statistics tracking for serialization method usage
- `__missing__` support to PersistentDict
- PyPy compatibility (pure Python fallback)
- O(1) `len()` implementation for BTree
- Python set method compatibility for BTree (`*args` handling)
- CHANGELOG.md for tracking version history and changes

### Changed

- Modernized `__iter__` to use `yield from` for better performance
- Improved BTree performance with cached length tracking
- Enhanced compatibility with Python 3.13
- Expanded test fixtures from 4 to 15+ in test/conftest.py

### Fixed

- Abstract socket startup logic
- 3.13 compatibility issues with subclassing
- Persistent dict inheritance from abstract base types
- FileStorage commit logging to include file size
- Pack queue ordering optimization

## [0.5.0] - 2025-02-08

### Added

- Complete architectural refactoring from Durus 4.x
- Layered package structure with clear separation of concerns
- Modern Python 3.13+ type hints throughout
- Multiple serialization backends (msgspec, pickle, dill)
- Oneiric integration for configuration and logging
- MCP server for modern AI/agent workflows
- Enhanced security with proper secret management
- Storage abstraction layer (FileStorage, MemoryStorage, ClientStorage, SqliteStorage)
- Persistent collection types (PersistentDict, PersistentList, PersistentSet, BTree)
- Comprehensive test suite with pytest (341 tests)
- Quality tooling (Ruff, Pyright, Bandit, Coverage)
- Expanded test fixtures for better test maintainability

### Changed

- **BREAKING**: Package renamed from `durus` to `dhara`
- **BREAKING**: Imports changed from `durus.*` to `dhara.*`
- **BREAKING**: Default serialization changed from pickle to msgspec
- Storage backends now use adapter pattern for pluggability
- Connection API improved with better cache management

### Migration from Durus 4.x

\`\`\`python

# Old (Durus 4.x)

from durus.connection import Connection
from durus.file_storage import FileStorage
from durus.persistent import Persistent

# New (dhara 5.0)

from dhara import Connection, Persistent
from dhara.storage import FileStorage
\`\`\`

See [CLAUDE.md](CLAUDE.md) for comprehensive migration guide.

### Performance

- 3x faster serialization with msgspec vs pickle
- O(1) BTree length queries (previously O(n))
- Improved connection caching with weak references
- Better memory management with automatic cache cleanup

## [0.4.3] - Legacy Durus Release

### Added

- Python 3.13 support
- Performance optimizations for persistent objects
- Enhanced garbage collection

### Changed

- Improved test coverage
- Updated documentation

## [0.4.2] - Legacy Durus Release

### Added

- Support for inherited server sockets
- Bug fixes and compatibility improvements

## Older Releases

For versions prior to 0.4.2, please refer to the git history.

## Version Numbering

- **Major version (X.0.0)**: Breaking changes, architectural refactors
- **Minor version (0.X.0)**: New features, backward-compatible additions
- **Patch version (0.0.X)**: Bug fixes, minor improvements

## Migration Notes

### From Durus 4.x to dhara 5.0

1. **Update imports**:
   \`\`\`python

   # Before

   from durus.connection import Connection
   from durus.persistent import Persistent

   # After

   from dhara import Connection, Persistent
   \`\`\`

1. **Serialization**:

   - Default is now msgspec (faster, safer)
   - Use `FallbackSerializer` for backward compatibility with pickle
   - Configure via Oneiric or explicit serializer selection

1. **Storage backends**:

   - FileStorage API remains compatible
   - New: SqliteStorage, ClientStorage, MemoryStorage
   - Use `Connection(storage)` or `Connection(filepath)` for convenience

1. **Testing**:

   - Migrated from sancho.utest to pytest
   - Fixtures now in `test/conftest.py` (15+ fixtures available)
   - Use `@pytest.mark.unit`, `@pytest.mark.integration`, etc.

## Test Fixtures

The following fixtures are available in `test/conftest.py`:

### Storage Fixtures

- `memory_storage` - Fresh MemoryStorage instance
- `temp_file_storage` - Temporary FileStorage with auto-cleanup
- `temp_storage_dir` - Temporary directory for storage operations
- `msgspec_serializer` - MsgspecSerializer instance
- `fallback_serializer` - FallbackSerializer with default whitelist

### Connection Fixtures

- `connection` - Connection with MemoryStorage (most commonly used)
- `file_connection` - Connection with FileStorage for persistence tests
- `connection_with_serializer` - Connection with explicit serializer

### Root Object Fixtures

- `empty_root` - Empty root object from connection
- `populated_root` - Root pre-populated with test data

### Test Data Fixtures

- `sample_data` - Sample data dictionary for testing
- `large_dataset` - Large dataset (1000 entries) for performance testing

### Other Fixtures

- `persistent_class` - Factory fixture for creating Persistent classes
- `persistent_object` - Creates and stores a persistent object
- `storage_comparison` - Creates both MemoryStorage and FileStorage for comparison
- `invalid_data` - Invalid/corrupt data for error handling tests
- `circular_reference` - Object with circular reference
- `is_unit_test` / `is_integration_test` - Markers for test type
- `performance_threshold` - Performance thresholds for benchmarking
- `benchmark_iterations` - Iteration count for benchmarks
- `auto_cleanup` - Automatic resource cleanup

## Contributing

See [CLAUDE.md](CLAUDE.md) for development guidelines.

## Security

For security issues, email: nas-dhara@arctrix.com

## License

MIT License - see LICENSE file for details
