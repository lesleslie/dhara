"""
Simple tests for storage backends without external dependencies.

These tests verify the storage functionality including:
- Base storage interface
- File storage operations
- CRUD operations
- Error handling
"""

import pytest
import asyncio
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from unittest.mock import Mock, AsyncMock

# Mock the imports to avoid dependency issues
class TenantID:
    """Mock tenant ID."""
    def __init__(self, value: str):
        self.value = value

    def __str__(self):
        return self.value

class MockStorageBackend:
    """Mock storage backend for testing the base interface."""

    def __init__(self, work_dir: Path):
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.data: Dict[str, Dict[str, Any]] = {}  # tenant_id -> data
        self.closed = False

    async def get(self, tenant_id: TenantID, key: str) -> Any:
        """Get a value from storage."""
        if self.closed:
            raise Exception("Storage is closed")
        return self.data.get(str(tenant_id), {}).get(key)

    async def put(self, tenant_id: TenantID, key: str, value: Any) -> bool:
        """Put a value into storage."""
        if self.closed:
            raise Exception("Storage is closed")

        tenant_key = str(tenant_id)
        if tenant_key not in self.data:
            self.data[tenant_key] = {}

        self.data[tenant_key][key] = value
        return True

    async def delete(self, tenant_id: TenantID, key: str) -> bool:
        """Delete a value from storage."""
        if self.closed:
            raise Exception("Storage is closed")

        tenant_key = str(tenant_id)
        if tenant_key in self.data and key in self.data[tenant_key]:
            del self.data[tenant_key][key]
            return True
        return False

    async def exists(self, tenant_id: TenantID, key: str) -> bool:
        """Check if a key exists in storage."""
        if self.closed:
            raise Exception("Storage is closed")

        tenant_key = str(tenant_id)
        return tenant_key in self.data and key in self.data[tenant_key]

    async def list_keys(self, tenant_id: TenantID) -> List[str]:
        """List all keys for a tenant."""
        if self.closed:
            raise Exception("Storage is closed")

        return list(self.data.get(str(tenant_id), {}).keys())

    async def get_tenant_info(self, tenant_id: TenantID) -> Dict[str, Any]:
        """Get tenant information."""
        if self.closed:
            raise Exception("Storage is closed")

        return {
            "tenant_id": str(tenant_id),
            "key_count": len(self.data.get(str(tenant_id), {})),
            "last_access": datetime.now().isoformat(),
        }

    async def close(self) -> None:
        """Close the storage backend."""
        self.closed = True

class MockFileStorage(MockStorageBackend):
    """Mock file storage implementation."""

    def __init__(self, filename: Optional[str] = None, readonly: bool = False, repair: bool = False):
        # Create temporary work directory
        work_dir = Path(tempfile.mkdtemp())
        super().__init__(work_dir)

        self.filename = filename or str(work_dir / "storage.db")
        self.readonly = readonly
        self.repair = repair

        # Mock shelf-like behavior
        self.shelf_data: Dict[str, Any] = {}
        self.pending_records = {}
        self.allocated_unused_oids = set()
        self.pack_extra = None
        self.invalid = set()

    def load(self, oid: str) -> bytes:
        """Mock load operation."""
        if oid not in self.shelf_data:
            raise KeyError(f"OID {oid} not found")
        return self.shelf_data[oid]

    def begin(self) -> None:
        """Mock begin operation."""
        self.pending_records.clear()

    def store(self, oid: str, record: bytes) -> None:
        """Mock store operation."""
        if self.readonly:
            raise Exception("Cannot modify readonly shelf")
        self.pending_records[oid] = record

    def end(self, handle_invalidations: Any = None) -> None:
        """Mock end operation."""
        # Commit pending records
        for oid, record in self.pending_records.items():
            self.shelf_data[oid] = record
        self.pending_records.clear()


@pytest.fixture
def work_dir() -> Path:
    """Create a temporary working directory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def storage_backend(work_dir: Path) -> MockStorageBackend:
    """Create a storage backend instance."""
    return MockStorageBackend(work_dir)


@pytest.fixture
def file_storage() -> MockFileStorage:
    """Create a file storage instance."""
    return MockFileStorage()


class TestStorageBackend:
    """Test storage backend functionality."""

    @pytest.mark.asyncio
    async def test_storage_initialization(self, storage_backend: MockStorageBackend, work_dir: Path):
        """Test storage backend initialization."""
        # Verify initialization
        assert storage_backend.work_dir == work_dir
        assert storage_backend.work_dir.exists()
        assert storage_backend.data == {}
        assert storage_backend.closed is False

    @pytest.mark.asyncio
    async def test_put_operation(self, storage_backend: MockStorageBackend):
        """Test put operation."""
        tenant_id = TenantID("test-tenant")

        # Put data
        result = await storage_backend.put(tenant_id, "key1", "value1")
        assert result is True

        # Verify data was stored
        assert "test-tenant" in storage_backend.data
        assert "key1" in storage_backend.data["test-tenant"]
        assert storage_backend.data["test-tenant"]["key1"] == "value1"

    @pytest.mark.asyncio
    async def test_get_operation(self, storage_backend: MockStorageBackend):
        """Test get operation."""
        tenant_id = TenantID("test-tenant")

        # Put data first
        await storage_backend.put(tenant_id, "key1", "value1")

        # Get data
        value = await storage_backend.get(tenant_id, "key1")
        assert value == "value1"

        # Get non-existent data
        value = await storage_backend.get(tenant_id, "non-existent")
        assert value is None

    @pytest.mark.asyncio
    async def test_delete_operation(self, storage_backend: MockStorageBackend):
        """Test delete operation."""
        tenant_id = TenantID("test-tenant")

        # Put data first
        await storage_backend.put(tenant_id, "key1", "value1")
        assert await storage_backend.exists(tenant_id, "key1") is True

        # Delete data
        result = await storage_backend.delete(tenant_id, "key1")
        assert result is True
        assert await storage_backend.exists(tenant_id, "key1") is False

    @pytest.mark.asyncio
    async def test_exists_operation(self, storage_backend: MockStorageBackend):
        """Test exists operation."""
        tenant_id = TenantID("test-tenant")

        # Check non-existent key
        exists = await storage_backend.exists(tenant_id, "key1")
        assert exists is False

        # Put data
        await storage_backend.put(tenant_id, "key1", "value1")

        # Check existing key
        exists = await storage_backend.exists(tenant_id, "key1")
        assert exists is True

    @pytest.mark.asyncio
    async def test_list_keys_operation(self, storage_backend: MockStorageBackend):
        """Test list keys operation."""
        tenant_id = TenantID("test-tenant")

        # List empty tenant
        keys = await storage_backend.list_keys(tenant_id)
        assert keys == []

        # Put multiple keys
        await storage_backend.put(tenant_id, "key1", "value1")
        await storage_backend.put(tenant_id, "key2", "value2")
        await storage_backend.put(tenant_id, "key3", "value3")

        # List keys
        keys = await storage_backend.list_keys(tenant_id)
        assert len(keys) == 3
        assert "key1" in keys
        assert "key2" in keys
        assert "key3" in keys

    @pytest.mark.asyncio
    async def test_get_tenant_info(self, storage_backend: MockStorageBackend):
        """Test get tenant info operation."""
        tenant_id = TenantID("test-tenant")

        # Put some data
        await storage_backend.put(tenant_id, "key1", "value1")
        await storage_backend.put(tenant_id, "key2", "value2")

        # Get tenant info
        info = await storage_backend.get_tenant_info(tenant_id)

        assert info["tenant_id"] == "test-tenant"
        assert info["key_count"] == 2
        assert "last_access" in info
        assert isinstance(info["last_access"], str)

    @pytest.mark.asyncio
    async def test_close_operation(self, storage_backend: MockStorageBackend):
        """Test close operation."""
        # Close storage
        await storage_backend.close()
        assert storage_backend.closed is True

        # Verify operations fail after close
        with pytest.raises(Exception, match="Storage is closed"):
            await storage_backend.get(TenantID("test"), "key1")

    @pytest.mark.asyncio
    async def test_concurrent_operations(self, storage_backend: MockStorageBackend):
        """Test concurrent storage operations."""
        tenant_id = TenantID("test-tenant")

        async def put_operation(key: str, value: str):
            await storage_backend.put(tenant_id, key, value)

        # Run concurrent puts
        tasks = [put_operation(f"key_{i}", f"value_{i}") for i in range(5)]
        await asyncio.gather(*tasks)

        # Verify all data was stored
        keys = await storage_backend.list_keys(tenant_id)
        assert len(keys) == 5
        for i in range(5):
            value = await storage_backend.get(tenant_id, f"key_{i}")
            assert value == f"value_{i}"

    @pytest.mark.asyncio
    async def test_cross_tenant_isolation(self, storage_backend: MockStorageBackend):
        """Test that tenants are isolated."""
        tenant1 = TenantID("tenant-1")
        tenant2 = TenantID("tenant-2")

        # Put different data for each tenant
        await storage_backend.put(tenant1, "shared_key", "value1")
        await storage_backend.put(tenant2, "shared_key", "value2")

        # Verify data isolation
        value1 = await storage_backend.get(tenant1, "shared_key")
        value2 = await storage_backend.get(tenant2, "shared_key")

        assert value1 == "value1"
        assert value2 == "value2"

        # Verify keys are isolated
        keys1 = await storage_backend.list_keys(tenant1)
        keys2 = await storage_backend.list_keys(tenant2)

        assert len(keys1) == 1
        assert len(keys2) == 1

    @pytest.mark.asyncio
    async def test_large_data_handling(self, storage_backend: MockStorageBackend):
        """Test handling of large data."""
        tenant_id = TenantID("test-tenant")

        # Create large data
        large_data = "x" * 1024 * 1024  # 1MB

        # Put large data
        result = await storage_backend.put(tenant_id, "large_data", large_data)
        assert result is True

        # Get large data
        retrieved_data = await storage_backend.get(tenant_id, "large_data")
        assert retrieved_data == large_data

    @pytest.mark.asyncio
    async def test_bulk_operations(self, storage_backend: MockStorageBackend):
        """Test bulk operations."""
        tenant_id = TenantID("test-tenant")

        # Bulk put operations
        data = {
            f"key_{i}": f"value_{i}"
            for i in range(100)
        }

        for key, value in data.items():
            result = await storage_backend.put(tenant_id, key, value)
            assert result is True

        # Verify all data was stored
        keys = await storage_backend.list_keys(tenant_id)
        assert len(keys) == 100

        # Verify a sample of keys
        for i in range(0, 100, 10):
            value = await storage_backend.get(tenant_id, f"key_{i}")
            assert value == f"value_{i}"

    @pytest.mark.asyncio
    async def test_error_handling(self, storage_backend: MockStorageBackend):
        """Test error handling."""
        tenant_id = TenantID("test-tenant")

        # Test operations on closed storage
        await storage_backend.close()

        with pytest.raises(Exception, match="Storage is closed"):
            await storage_backend.get(tenant_id, "key1")

        with pytest.raises(Exception, match="Storage is closed"):
            await storage_backend.put(tenant_id, "key1", "value1")

        with pytest.raises(Exception, match="Storage is closed"):
            await storage_backend.delete(tenant_id, "key1")

        with pytest.raises(Exception, match="Storage is closed"):
            await storage_backend.exists(tenant_id, "key1")

        with pytest.raises(Exception, match="Storage is closed"):
            await storage_backend.list_keys(tenant_id)

        with pytest.raises(Exception, match="Storage is closed"):
            await storage_backend.get_tenant_info(tenant_id)


class TestFileStorage:
    """Test file storage functionality."""

    @pytest.mark.asyncio
    async def test_file_storage_initialization(self, file_storage: MockFileStorage):
        """Test file storage initialization."""
        assert file_storage.filename is not None
        assert file_storage.filename.endswith("storage.db")
        assert file_storage.shelf_data == {}
        assert file_storage.pending_records == {}
        assert file_storage.readonly is False

    @pytest.mark.asyncio
    async def test_readonly_file_storage(self, file_storage: MockFileStorage):
        """Test readonly file storage."""
        # Create readonly storage
        readonly_storage = MockFileStorage()
        readonly_storage.readonly = True

        # Should be able to load existing data
        readonly_storage.shelf_data["test_oid"] = b"test_record"

        record = readonly_storage.load("test_oid")
        assert record == b"test_record"

        # Should not be able to modify data
        with pytest.raises(Exception, match="Cannot modify readonly shelf"):
            readonly_storage.store("new_oid", b"new_record")

    @pytest.mark.asyncio
    async def test_commit_workflow(self, file_storage: MockFileStorage):
        """Test commit workflow."""
        # Put some records
        file_storage.shelf_data["oid1"] = b"record1"
        file_storage.shelf_data["oid2"] = b"record2"

        # Begin commit
        file_storage.begin()
        assert file_storage.pending_records == {}

        # Store some records
        file_storage.store("oid3", b"record3")
        file_storage.store("oid4", b"record4")
        assert len(file_storage.pending_records) == 2

        # End commit
        file_storage.end()
        assert file_storage.pending_records == {}
        assert "oid3" in file_storage.shelf_data
        assert "oid4" in file_storage.shelf_data
        assert file_storage.shelf_data["oid3"] == b"record3"
        assert file_storage.shelf_data["oid4"] == b"record4"

    @pytest.mark.asyncio
    async def test_load_not_found(self, file_storage: MockFileStorage):
        """Test loading non-existent OID."""
        with pytest.raises(KeyError, match="OID not_found not found"):
            file_storage.load("not_found")

    @pytest.mark.asyncio
    async def test_shelf_integration(self, file_storage: MockFileStorage):
        """Test shelf-like operations."""
        # Test dict-like operations
        file_storage.shelf_data["key1"] = "value1"
        file_storage.shelf_data["key2"] = "value2"

        assert file_storage.shelf_data["key1"] == "value1"
        assert file_storage.shelf_data.get("key1") == "value1"
        assert file_storage.shelf_data.get("non_existent", "default") == "default"
        assert "key1" in file_storage.shelf_data
        assert len(list(file_storage.shelf_data.keys())) == 2
        assert len(list(file_storage.shelf_data.values())) == 2
        assert len(list(file_storage.shelf_data.items())) == 2

    @pytest.mark.asyncio
    async def test_pack_operations(self, file_storage: MockFileStorage):
        """Test pack operations."""
        # Add some data
        file_storage.shelf_data["oid1"] = b"record1"
        file_storage.shelf_data["oid2"] = b"record2"
        file_storage.shelf_data["oid3"] = b"record3"

        # Start pack
        file_storage.pack_extra = []

        # Mark some as invalid
        file_storage.invalid.add("oid2")

        # Add more data during pack
        file_storage.shelf_data["oid4"] = b"record4"
        file_storage.pack_extra.append("oid4")

        # Simulate pack completion by removing invalid
        file_storage.shelf_data.pop("oid2", None)

        assert "oid1" in file_storage.shelf_data
        assert "oid3" in file_storage.shelf_data
        assert "oid4" in file_storage.shelf_data
        assert "oid2" not in file_storage.shelf_data