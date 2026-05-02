# Changelog

All notable changes to dhara will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
