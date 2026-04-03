# Dhara Test Coverage Expansion Plan

## Project Overview

**Dhara** is a persistent object database for Python with MCP server capabilities for adapter distribution. It's a modern continuation of Durus with Python 3.13+ support.

**Current Status:** Need to audit existing test coverage

## Test Coverage Goals

- **Overall Target**: 60%+ coverage (from unknown baseline)
- **Core Functionality**: 70%+ coverage
- **MCP Tools**: 70%+ coverage
- **CLI Commands**: 70%+ coverage

## Project Structure Analysis

### Core Modules to Test

1. **dhara/core/**
   - `connection.py` - Connection management, transactions, caching
   - `persistent.py` - Persistent object base classes
   - `config.py` - Configuration management

2. **dhara/collections/**
   - `dict.py` - PersistentDict
   - `list.py` - PersistentList
   - `set.py` - PersistentSet
   - `btree.py` - BTree implementation

3. **dhara/storage/**
   - `file.py` - FileStorage backend
   - `sqlite.py` - SqliteStorage backend
   - `client.py` - ClientStorage for server mode

4. **dhara/mcp/**
   - `server_core.py` - FastMCP server implementation
   - `adapter_tools.py` - Adapter registry and management

5. **dhara/cli.py** - CLI commands

## Phase 1: Audit Test Coverage (Day 1)

### Tasks

1. **Run coverage report**
   ```bash
   cd /Users/les/Projects/dhara
   pytest --cov=dhara --cov-report=html
   open htmlcov/index.html
   ```

2. **Identify low-coverage modules**
   - Check coverage report for modules below 40%
   - Prioritize critical paths (connection, storage, MCP tools)

3. **Analyze existing tests**
   - Review `test/test_file_storage.py` (legacy tests)
   - Identify test patterns and gaps

### Deliverables

- Coverage report with baseline metrics
- List of modules requiring immediate attention
- Test gap analysis document

## Phase 2: Core Database Tests (Days 2-3)

### Test Suites to Create

#### 2.1 Connection Management (`test/test_connection.py`)

```python
class TestConnection:
    """Test Connection class for transaction management."""

    def test_connection_initialization()
    def test_get_root()
    def test_commit_transaction()
    def test_abort_transaction()
    def test_cache_management()
    def test_invalid_oid_handling()
    def test_conflict_resolution()
```

#### 2.2 Persistent Collections (`test/test_collections.py`)

```python
class TestPersistentDict:
    """Test PersistentDict functionality."""

    def test_dict_operations()
    def test_persistence_across_commits()
    def test_nesting()

class TestPersistentList:
    """Test PersistentList functionality."""

    def test_list_operations()
    def test_persistence_across_commits()

class TestPersistentSet:
    """Test PersistentSet functionality."""

    def test_set_operations()
    def test_persistence_across_commits()
```

#### 2.3 Storage Backends (`test/test_storage_backends.py`)

```python
class TestFileStorage:
    """Test FileStorage backend."""

    def test_storage_creation()
    def test_record_storage()
    def test_storage_packing()
    def test_concurrent_access()
    def test_readonly_mode()

class TestSqliteStorage:
    """Test SqliteStorage backend."""

    def test_sqlite_backend()
    def test_transaction_handling()
```

## Phase 3: MCP Server Tests (Days 4-5)

### Test Suites to Create

#### 3.1 MCP Server Core (`test/test_mcp_server.py`)

```python
class TestDharaMCPServer:
    """Test DharaMCPServer with FastMCP."""

    @pytest.fixture
    def server(self):
        """Create test server instance."""
        # Create temp storage, initialize server

    def test_server_initialization(self, server)
    def test_tool_registration(self, server)
    def test_storage_path_expansion(self, server)
    def test_adapter_registry_init(self, server)

    @pytest.mark.asyncio
    async def test_store_adapter_tool(self, server)

    @pytest.mark.asyncio
    async def test_get_adapter_tool(self, server)

    @pytest.mark.asyncio
    async def test_list_adapters_tool(self, server)

    @pytest.mark.asyncio
    async def test_validate_adapter_tool(self, server)

    @pytest.mark.asyncio
    async def test_health_check_tool(self, server)
```

#### 3.2 Adapter Registry (`test/test_adapter_registry.py`)

```python
class TestAdapter:
    """Test Adapter persistent object."""

    def test_adapter_creation()
    def test_version_update()
    def test_rollback_to_version()
    def test_to_dict_conversion()

class TestAdapterRegistry:
    """Test AdapterRegistry operations."""

    @pytest.fixture
    def registry(self):
        """Create test registry with temp storage."""

    def test_registry_initialization(self, registry)
    def test_store_adapter(self, registry)
    def test_get_adapter(self, registry)
    def test_update_existing_adapter(self, registry)
    def test_list_adapters(self, registry)
    def test_list_adapter_versions(self, registry)
    def test_validate_adapter(self, registry)
    def test_check_adapter_health(self, registry)
    def test_count_adapters(self, registry)
```

## Phase 4: CLI Tests (Day 6)

### Test Suites to Create

#### 4.1 CLI Commands (`test/test_cli.py`)

```python
class TestDharaCLI:
    """Test Dhara CLI commands."""

    @pytest.fixture
    def temp_config(self):
        """Create temporary config for testing."""

    def test_create_cli(self)
    def test_adapters_command(self, temp_config)
    def test_storage_command(self, temp_config)
    def test_health_probe_handler(self)

    @pytest.mark.asyncio
    async def test_start_handler(self, temp_config)

    def test_stop_handler(self, temp_config)
```

## Phase 5: Integration Tests (Day 7)

### Test Suites to Create

#### 5.1 End-to-End Workflows (`test/test_integration.py`)

```python
class TestAdapterDistribution:
    """Test complete adapter distribution workflows."""

    def test_store_and_retrieve_adapter()
    def test_version_rollback_workflow()
    def test_health_check_workflow()
    def test_multiple_clients_concurrent_access()

class TestMCPE2E:
    """Test MCP server end-to-end."""

    @pytest.mark.asyncio
    async def test_full_mcp_workflow()
    @pytest.mark.asyncio
    async def test_concurrent_mcp_requests()
```

## Testing Strategy

### Test Organization

```
test/
├── unit/
│   ├── test_connection.py
│   ├── test_collections.py
│   ├── test_storage_backends.py
│   ├── test_adapter_persistent.py
│   ├── test_adapter_registry.py
│   ├── test_mcp_server.py
│   └── test_config.py
├── integration/
│   ├── test_mcp_e2e.py
│   └── test_adapter_workflows.py
└── conftest.py (shared fixtures)
```

### Fixtures to Create

```python
# conftest.py
@pytest.fixture
def temp_storage():
    """Create temporary FileStorage for testing."""
    # Create temp file, cleanup after test

@pytest.fixture
def connection(temp_storage):
    """Create Connection with temp storage."""
    # Return connection, cleanup after test

@pytest.fixture
def mcp_server(temp_storage):
    """Create DharaMCPServer for testing."""
    # Return server instance

@pytest.fixture
def adapter_registry(connection):
    """Create AdapterRegistry for testing."""
    # Return registry instance
```

### Test Markers

- `@pytest.mark.unit` - Unit tests
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.asyncio` - Async tests
- `@pytest.mark.slow` - Slow tests (>2s)
- `@pytest.mark.mcp` - MCP-specific tests

## Success Metrics

| Component | Target | Current |
|-----------|--------|---------|
| Overall Coverage | 60%+ | ? |
| Core (connection, persistent) | 70%+ | ? |
| Collections | 70%+ | ? |
| Storage | 70%+ | ? |
| MCP Server | 70%+ | ? |
| Adapter Registry | 70%+ | ? |
| CLI | 70%+ | ? |

## Implementation Order

1. **Phase 1**: Audit and baseline (Day 1)
2. **Phase 2**: Core database tests (Days 2-3)
3. **Phase 3**: MCP server tests (Days 4-5)
4. **Phase 4**: CLI tests (Day 6)
5. **Phase 5**: Integration tests (Day 7)
6. **Final Review**: Coverage validation and cleanup (Day 8)

## Risk Mitigation

### Potential Issues

1. **Legacy test compatibility**
   - Existing tests in `test/` use old patterns
   - Solution: Keep legacy tests separate, create new in `test/unit/`

2. **File system dependencies**
   - FileStorage creates actual files
   - Solution: Use pytest's `tmp_path` fixture for isolation

3. **Async test complexity**
   - MCP tools are async
   - Solution: Use pytest-asyncio with proper fixtures

4. **Concurrent access testing**
   - Connection has multi-threading support
   - Solution: Create dedicated concurrent test suite

## Next Steps

1. ✅ Create this plan
2. ⏭️ Run initial coverage audit
3. ⏭️ Create test infrastructure (fixtures, conftest.py)
4. ⏭️ Implement Phase 2 tests
5. ⏭️ Implement Phase 3 tests
6. ⏭️ Implement Phase 4 tests
7. ⏭️ Implement Phase 5 tests
8. ⏭️ Final coverage validation

## Documentation

All tests should include:

- Clear docstrings explaining what is being tested
- Comments explaining complex test scenarios
- References to issues or requirements being tested
- Examples of usage in test docstrings

---

**Created:** 2025-02-09
**Status:** Planning Phase
**Next Action:** Run coverage audit
