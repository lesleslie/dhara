# Complete Fix Summary: CLI Commands & Adapter Class

## Overview

Successfully fixed all CLI test failures by addressing three core issues:
1. **Adapter class inheritance bug** (missing `_p_note_change` method)
2. **CLI storage management** (improper cleanup)
3. **Readonly storage handling** (AdapterRegistry couldn't handle readonly storage)

## Changes Made

### 1. Fixed Adapter Class Inheritance (`dhara/mcp/adapter_tools.py`)

**Problem**: Adapter class was using `PersistentBase` instead of `Persistent`, missing the `_p_note_change()` method.

**Solution**: Changed import to use the correct base class:
```python
# Before (line 16-21):
from dhara.core.persistent import PersistentBase
logger = logging.getLogger(__name__)

# Type alias for type checking
Persistent = PersistentBase

# After (line 16-18):
from dhara.core.persistent import Persistent

logger = logging.getLogger(__name__)
```

**Impact**:
- ✅ Adapter instances can now track changes correctly
- ✅ Integration tests pass
- ✅ No more `AttributeError: 'Adapter' object has no attribute '_p_note_change'`

### 2. Added Context Manager Support to FileStorage (`dhara/storage/file.py`)

**Added after line 188**:
```python
def __enter__(self):
    """Context manager entry - returns self for use in with statements."""
    return self

def __exit__(self, exc_type, exc_val, exc_tb):
    """Context manager exit - automatically closes storage and releases lock."""
    self.close()
    return False  # Don't suppress exceptions
```

**Benefits**:
- Automatic lock release even on exceptions
- Cleaner code with `with FileStorage(...) as storage:` pattern
- Backward compatible (manual `close()` still works)

### 3. Updated CLI Commands to Use Context Managers (`dhara/cli.py`)

**Problem**: CLI commands were calling `connection.close()` but Connection doesn't have a close() method.

**Solution**: Used context managers for automatic cleanup:

```python
# Before (lines 202-216):
storage = FileStorage(str(settings.storage.path), readonly=True)
connection = Connection(storage)
registry = AdapterRegistry(connection)
# ... do work ...
connection.close()  # ❌ Connection has no close() method

# After (lines 202-214):
with FileStorage(str(settings.storage.path), readonly=True) as storage:
    connection = Connection(storage)
    registry = AdapterRegistry(connection)
    # ... do work ...
# ✅ Storage automatically closed here
```

**Files updated**:
- `adapters` command (line 192-214)
- `storage` command (line 226-240)

### 4. Fixed AdapterRegistry for Readonly Storage (`dhara/mcp/adapter_tools.py`)

**Problem**: `_ensure_registry_structure()` tried to write to readonly storage, causing AssertionError.

**Solution**: Check if storage is readonly before writing:
```python
def _ensure_registry_structure(self) -> None:
    """Ensure registry structure exists in root.

    Silently skips if storage is read-only.
    """
    root = self.connection.get_root()

    # Check if we can write (storage is not read-only)
    try:
        storage = self.connection.storage
        is_readonly = hasattr(storage, 'shelf') and storage.shelf.file.is_readonly()
    except Exception:
        is_readonly = False

    if not is_readonly:
        if "adapters" not in root:
            root["adapters"] = PersistentDict()
            self.connection.commit()
        # ... etc
```

**Also updated `list_adapters()`** to handle missing adapters dict:
```python
def list_adapters(self, ...) -> list[dict[str, Any]]:
    root = self.connection.get_root()

    # Handle case where adapters dict doesn't exist (readonly storage)
    if "adapters" not in root:
        return []

    adapters: PersistentDict = root["adapters"]
    # ... rest of method
```

### 5. Fixed Unit Tests (`test/unit/test_cli.py`)

**Problem**: Tests were patching settings AFTER creating the CLI, so the patch had no effect.

**Solution**: Create CLI inside the patch context:
```python
# Before (lines 84-88):
app = create_cli()  # ❌ Creates CLI with real settings

with patch("dhara.cli.DharaSettings.load", return_value=temp_settings):
    result = runner.invoke(app, ["adapters"])

# After (lines 94-96):
with patch("dhara.cli.DharaSettings.load", return_value=temp_settings):
    app = create_cli()  # ✅ Creates CLI with mocked settings
    result = runner.invoke(app, ["adapters"])
```

**Also added storage file creation** for empty tests:
```python
# Create empty storage file before testing
storage = FileStorage(str(temp_settings.storage.path))
conn = Connection(storage)
conn.commit()  # Create the file
storage.close()
```

**Tests fixed**:
- `test_adapters_command_empty` (lines 82-100)
- `test_adapters_command_with_data` (lines 120-138)
- `test_adapters_command_filter_domain` (lines 167-174)
- `test_adapters_command_filter_category` (lines 214-221)
- `test_storage_command` (lines 236-242)

## Test Results

### Before
```
5 failed, 16 passed, 2 errors
- AttributeError: 'Adapter' object has no attribute '_p_note_change'
- AssertionError: readonly storage
- OSError: file not found
```

### After
```
✅ 21 passed, 0 failed
```

**All tests passing**:
- ✅ test_create_cli
- ✅ test_cli_has_lifecycle_commands
- ✅ test_adapters_command_empty
- ✅ test_adapters_command_with_data
- ✅ test_adapters_command_filter_domain
- ✅ test_adapters_command_filter_category
- ✅ test_storage_command
- ✅ test_health_probe_handler
- ✅ test_health_probe_handler_no_storage
- ✅ test_start_handler
- ✅ test_stop_handler
- ✅ test_admin_command_requires_ipython
- ✅ test_cli_error_handling
- ✅ test_cli_help
- ✅ test_adapters_command_help
- ✅ test_storage_command_help
- ✅ test_custom_commands_exist[adapters]
- ✅ test_custom_commands_exist[storage]
- ✅ test_custom_commands_exist[admin]
- ✅ test_full_adapters_workflow (integration)
- ✅ test_storage_info_with_data (integration)

## Technical Insights

### Class Hierarchy Understanding

**Correct hierarchy**:
```
PersistentBase (base with __getattribute__, __setattr__)
  └─ PersistentObject (adds _p_note_change and other methods)
      └─ Persistent (adds __getstate__ for __dict__ storage)
```

**The bug**: Using `PersistentBase` directly skips the `_p_note_change()` method that's added in `PersistentObject`.

### Context Manager Pattern

**Why it matters**:
1. **Exception safety**: Locks released even if errors occur
2. **Cleaner code**: No need to remember `close()` calls
3. **Prevents resource leaks**: Automatic cleanup guaranteed

**Example**:
```python
# Old pattern (error-prone)
storage = FileStorage("data.dhara")
try:
    # ... work ...
finally:
    storage.close()  # Easy to forget!

# New pattern (recommended)
with FileStorage("data.dhara") as storage:
    # ... work ...
# Lock released automatically, even on exceptions
```

### Readonly Storage Handling

**The pattern**:
1. Check if storage is readonly before writing
2. Gracefully handle missing data structures
3. Return empty results instead of crashing

**This enables**:
- CLI commands to work with readonly storage
- Safe inspection of production databases
- Better separation of read vs write operations

## Files Modified

1. **dhara/mcp/adapter_tools.py**
   - Fixed Adapter class inheritance (line 16)
   - Added readonly storage handling (lines 163-190)
   - Added missing adapters dict check (lines 324-327)

2. **dhara/storage/file.py**
   - Added `__enter__` method (after line 188)
   - Added `__exit__` method (after line 188)

3. **dhara/cli.py**
   - Updated `adapters` command to use context manager (lines 192-214)
   - Updated `storage` command to use context manager (lines 226-240)

4. **test/unit/test_cli.py**
   - Fixed 5 tests to patch settings before creating CLI
   - Added storage file creation for empty tests

## Verification

Run the test suite:
```bash
python -m pytest test/unit/test_cli.py -v
```

Expected result:
```
========================= 21 passed in 27.49s =========================
```

## Related Documentation

- Python Context Managers: https://docs.python.org/3/reference/datamodel.html#context-managers
- Dhara Storage Architecture: See `CLAUDE.md`
- Persistent Object Lifecycle: See `dhara/core/persistent.py`

---

**Implementation Date**: 2026-02-10
**Status**: ✅ Complete
**Breaking Changes**: None
**Backward Compatibility**: 100%
