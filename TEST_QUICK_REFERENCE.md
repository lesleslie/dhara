# Dhruva Test Quick Reference

## Quick Start

```bash
cd /Users/les/Projects/dhruva

# Run all new tests
pytest test/unit/test_adapter_registry.py test/unit/test_mcp_server.py test/unit/test_config.py test/unit/test_cli.py -v

# Run with coverage
pytest test/unit/ --cov=dhruva --cov-report=html --cov-report=term-missing

# Run specific test file
pytest test/unit/test_adapter_registry.py -v

# Run only async tests
pytest test/unit/ -m asyncio -v

# Automated coverage audit
bash scripts/run_coverage_audit.sh
```

## Test Files Created

| File | Lines | Purpose |
|------|-------|---------|
| `test/unit/test_adapter_registry.py` | 730 | Adapter registry & MCP tool implementations |
| `test/unit/test_mcp_server.py` | 335 | FastMCP server & tool registration |
| `test/unit/test_config.py` | 370 | Configuration management |
| `test/unit/test_cli.py` | 390 | CLI commands |
| **Total** | **1,825** | Comprehensive test coverage |

## Coverage Targets

- **Overall**: 60%+
- **Adapter Registry**: 70%+
- **MCP Server**: 70%+
- **Configuration**: 70%+
- **CLI**: 70%+

## Test Organization

```
test/
├── conftest.py (existing fixtures)
└── unit/
    ├── test_adapter_registry.py (NEW)
    ├── test_mcp_server.py (NEW)
    ├── test_config.py (NEW)
    └── test_cli.py (NEW)
```

## Key Fixtures (from existing conftest.py)

- `memory_storage` - In-memory storage
- `temp_file_storage` - Temporary file storage
- `connection` - Connection with MemoryStorage
- `file_connection` - Connection with FileStorage

## Test Markers

- `@pytest.mark.unit` - Unit tests
- `@pytest.mark.asyncio` - Async tests
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.slow` - Slow tests (>2s)

## Running Specific Tests

### Adapter Registry Tests
```bash
pytest test/unit/test_adapter_registry.py -v
pytest test/unit/test_adapter_registry.py::TestAdapter::test_adapter_creation -v
pytest test/unit/test_adapter_registry.py -k "test_store_adapter" -v
```

### MCP Server Tests
```bash
pytest test/unit/test_mcp_server.py -v
pytest test/unit/test_mcp_server.py -k "asyncio" -v
```

### Configuration Tests
```bash
pytest test/unit/test_config.py -v
pytest test/unit/test_config.py::TestStorageConfig -v
```

### CLI Tests
```bash
pytest test/unit/test_cli.py -v
pytest test/unit/test_cli.py -k "adapters_command" -v
```

## Coverage Reports

### Generate HTML Report
```bash
pytest test/unit/ --cov=dhruva --cov-report=html
open htmlcov/index.html
```

### Generate JSON Report
```bash
pytest test/unit/ --cov=dhruva --cov-report=json
cat coverage.json | python -m json.tool
```

### Terminal Report
```bash
pytest test/unit/ --cov=dhruva --cov-report=term-missing:skip-covered
```

## Troubleshooting

### Import Errors
```bash
# Ensure dhruva is installed in development mode
cd /Users/les/Projects/dhruva
pip install -e .
```

### Missing Dependencies
```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov pytest-mock
```

### Path Issues
```bash
# Run from project root
cd /Users/les/Projects/dhruva
pytest test/unit/
```

## Test Execution Tips

### Verbose Output
```bash
pytest test/unit/ -vv -s
```

### Stop on First Failure
```bash
pytest test/unit/ -x
```

### Run Failed Tests Only
```bash
pytest test/unit/ --lf
```

### Parallel Execution
```bash
pytest test/unit/ -n auto
```

## Coverage Workflow

1. **Initial Baseline**
   ```bash
   bash scripts/run_coverage_audit.sh
   ```

2. **Run New Tests**
   ```bash
   pytest test/unit/test_adapter_registry.py test/unit/test_mcp_server.py test/unit/test_config.py test/unit/test_cli.py --cov=dhruva --cov-report=html
   ```

3. **Review Coverage**
   ```bash
   open htmlcov/index.html
   ```

4. **Identify Gaps**
   - Look for red modules (<50%)
   - Check yellow modules (50-80%)
   - Review missed lines

5. **Fill Gaps**
   - Add tests for uncovered functions
   - Test edge cases
   - Add error handling tests

## Success Metrics

After running tests:
- ✅ Overall coverage ≥ 60%
- ✅ All new tests pass
- ✅ No test failures or errors
- ✅ Coverage report shows improvement

## Documentation

- **Test Plan**: `DHRUVA_TEST_COVERAGE_PLAN.md`
- **Summary**: `TEST_COVERAGE_EXPANSION_SUMMARY.md`
- **Quick Reference**: This file

## Contact

For questions about test implementation or coverage, refer to the test plan document.
