# Changelog

All notable changes to dhara will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.15.1] - 2026-08-12

### Added

- Adopt coverage-ratchet at current coverage

### Internal

- dhara: Migrate .superprofits/sdd/ tracked files to .superpowers/sdd/
- Remove .superprofits/ scratch typo, add to .gitignore

## [0.15.0] - 2026-08-11

### Added

- Add substrate_locks table to pg_schema (v1.1 Postgres translation)
- Add typed object schema substrate (D-OBJ-SCHEMA)
- audit: Wire OutboxFlusher periodic flush into DharaMCPServer startup
- AuditLogQueryTool — read-back via from_dict with schema validation
- AuditLogSubscriber + MemoryOutbox (asynchronous, G6-safe)
- Migration 0004 — audit_log table + entity_type index
- OutboxFlusher drains MemoryOutbox into audit_log table
- PostgresBackendLock — asyncpg + Postgres-native $N placeholders
- Wire AuditLogSubscriber + query tool into DharaMCPServer
- Wire register_lock_routes into DharaMCPServer

### Documentation

- Add D-OBJ-SCHEMA typed object schema primitive implementation plan
- Completion report + portfolio status update for D-AUDIT
- contract: Define substrate put/get call-boundary as sync
- D-AUDIT implementation plan (7 tasks, Layer 0 audit substrate)
- plan: D-LOCK v1.1 — Postgres translation of substrate_locks
- Rewrite D-LOCK v1.1 Postgres translation plan
- spec: Add D-OBJ-SCHEMA typed object schema primitive design
- spec: D-AUDIT substrate design (Layer 0)

### Testing

- Cross-backend parity + completion report for D-LOCK v1.1
- Cross-system integration test — dhara.put → audit_record round-trip

## [0.14.0] - 2026-08-05

### Added

- Add acquire() with timeout=0 LockTimeout fix + symmetric jitter
- Add DharaLock Protocol, LockHandle, InMemoryDharaLock
- Add migration 0003 for substrate_locks table
- Add migration 0003 substrate_locks table + test
- Add SQLBackendLock.try_acquire with atomic UPSERT
- Emit audit:lock.{acquired,released,heartbeat,lost} events
- lock: Add get() and list_keys() for reapers/dashboards/precommit
- lock: Add release/try_release/heartbeat with is_permanent guard
- lock: Add REST routes with full 409 reason taxonomy

### Fixed

- deps: Add pytz for DuckDB TIMESTAMPTZ handling
- lock: Handle DuckDB transaction conflicts
- lock: Heartbeat handler returns JSONResponse on body-parse failure
- Mark DharaLock.acquire as async in Protocol
- Revert "feat(lock): add migration 0003 substrate_locks table + test"
- spec: Drop partial-index WHERE clauses for DuckDB compat
- spec: Fold multi-agent review findings into D-LOCK design
- spec: Resolve D-LOCK self-review ambiguities
- spec: Resolve D-LOCK self-review issues (round 2)
- substrate: Wire Workstream C routes through migration 0001 SQL tables

### Documentation

- spec: Add D-LOCK distributed lock primitive design

### Testing

- Add permanent-mode tests including LockPermanentError path
- lock: Add concurrency tests with per-thread connections (H3 fix)
- lock: Replace dynamic import and shorten long line in permanent tests

## [0.13.2] - 2026-07-28

### Fixed

- Add pid_path method to DharaSettings

### Documentation

- readme: Add Bodai Ecosystem Role section

### Internal

- Bump oneiric dep to >=0.16.0
- deps: Bump crackerjack>=0.70.0; remove duplicated validator script
- deps: Remove duplicated validate_document_frontmatter.py script
- dhara: Remove orphaned \_compat module
- Normalize LICENSE attribution to Robert Leslie and Wedgwood Web Works

## [0.13.0] - 2026-07-21

### Added

- dhara: Add AsyncFileStorage shim (drop-in for FileStorage path-arg pattern)
- dhara: Add registry-mediated cache-adapter lookup helper
- Initial dhara plugin manifest + starter commands

### Changed

- Delete dhara.storage.redis_cache (now unused)
- Delete dhara/storage/file.py (sub-task 1i completion)
- dhara: Add async Connection factory alongside sync (sub-task 1d)
- dhara: Drop deleted cache config fields, source from OneiricSettings
- dhara: Initialize async_adapter_registry before cache_backend block
- dhara: Port __main__.py FileStorage to AsyncFileStorage (sub-task 1h, partial)
- dhara: Port backup/ to AsyncFileStorage (sub-task 1b)
- dhara: Port benchmarks to AsyncConnection (sub-task 1l)
- dhara: Port cli.py FileStorage to AsyncFileStorage (sub-task 1g, partial)
- dhara: Port mcp/server_core.py to AsyncFileStorage (sub-task 1c)
- dhara: Remove FileStorage from re-exports and remaining docstrings
- dhara: Ruff format + F401/isort sweep
- dhara: Wire MCP-server cache through registry helper
- Extract Druva aliases to dhara.\_compat.druva

### Fixed

- dhara: Connection(path) raises TypeError; add AsyncConnection.new path coercion
- dhara: Preserve event loop during cache wiring
- dhara: Repair broken bin/db_renumber.py (async migration + ModuleNotFoundError fix)
- dhara: Repair iter() sentinel bug in backup/manager.py (1b completion)
- dhara: Update storage_backend default 'file' -> 'sqlite'
- dhara: Use builtin open() in __main__.py to fix 7 pre-existing test failures
- Make DharaMCPServer.__init__ survive post-async-migration storage
- Self-contained YAML loader in DharaSettings.load()

### Documentation

- Add cache-adapter consolidation spec (Dhara -> Oneiric)
- dhara: Add cache-adapter consolidation implementation plan
- dhara: Add Oneiric-side plan (factory-string fix, settings, consumer code)
- dhara: Align cache-adapter plan with post-review spec + split into companion Oneiric plan
- dhara: Apply plan-lifecycle-unification playbook (P7.B)
- dhara: Correct spec after multi-agent review
- dhara: Mark cache-adapter consolidation shipped; record as-built divergences
- dhara: Update FileStorage references in signing.py and shell docstrings
- Normalize markdown list numbering (mdformat)
- plans: Amend 2026-07-15-async-migration-cleanup plan with scope-audit corrections
- plans: Tick shipped checkboxes in oneiric cache-factory-and-settings
- Reconcile async-first and remediation plans
- Reconcile async-first and remediation plans

### Testing

- dhara: Add failing tests for cache-adapter lookup helper
- dhara: Cover \_wire_cache wiring through server_core
- dhara: Drop FileStorage test suite (sub-task 1j, group 1/5)
- dhara: Migrate backup test suite to AsyncFileStorage (sub-task 1j, group 2/5)
- dhara: Migrate cli and main tests to AsyncFileStorage (sub-task 1j, group 4/5)
- dhara: Migrate connection + conftest tests to AsyncFileStorage (sub-task 1j, group 5/5)
- dhara: Migrate MCP server tests to AsyncFileStorage (sub-task 1j, group 3/5)
- dhara: Remove deprecated event_loop fixture (asyncio_mode=auto covers it)
- dhara: Repoint server_core patches from local adapter to registry helper
- dhara: Skip test_resolves_redis_backend on coredis>=6
- dhara: Update test_modes.py to expect 'sqlite' default

### Internal

- dhara: Delete broken examples/backup_example.py and setup_backup_system.py
- dhara: Remove LICENSE (consolidated to root-level LICENSE)
- dhara: Remove orphaned files (test for deleted btree_node module, unused deployment script, btree redesign spec)
- dhara: Sync uv.lock to 0.12.1, gitignore benchmark scratch

## [0.12.1] - 2026-07-14

### Changed

- Dhara (quality: 66/100) - 2026-07-06 22:40:50
- settings: Migrate dhara to OneiricMCPConfig

## [0.12.0] - 2026-07-05

### Added

- Add async run_migrations runner + 0001/0002 sql
- dhara: Add 3 substrate HTTP CRUD routes (Workstream C)
- dhara: Plan 4 Phase B — Adapter env field
- dhara: Plan 7 Phase 2 — FastMCP 3.4 consumer bump
- In-process async event bus + pydantic events + audit_log subscriber
- sql-proxy: DuckDBAdapter with async execute/query
- sql-proxy: Register dhara_sql_execute and dhara_sql_query MCP tools

### Fixed

- dhara: Raise mcp-common floor to 0.17.0 (PyPI release ships fastmcp submodule)
- dhara: Resolve cross-checker (mypy, ty, refurb) errors
- gitignore: Match .lycheecache whether file or dir; add .pyscn/

### Testing

- dhara: Add failing HTTP CRUD route tests for Workstream C

### Internal

- dhara: Migrate [project.optional-dependencies] → [dependency-groups]
- gitignore: Track .worktrees/ to silence worktree add artifacts
- gitignore: Untrack .lycheecache

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
