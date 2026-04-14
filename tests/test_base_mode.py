"""
Tests for base mode in Dhara.

These tests verify the base mode functionality including:
- Base mode initialization and configuration
- Core database operations
- Mode switching capabilities
- Common functionality across all modes
"""

import pytest
import asyncio
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, List, Any, Optional

from dhara.modes.base import BaseMode
from dhara.storage.base import StorageBackend
from dhara.core.tenant import TenantID
from dhara.core.transaction import Transaction, TransactionOptions
from dhara.serialize.msgspec import MsgspecSerializer


class TestBaseMode:
    """Test base mode functionality."""

    @pytest.fixture
    def temp_dir(self) -> Path:
        """Create a temporary directory for the mode."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    @pytest.fixture
    def storage_backend(self) -> AsyncMock:
        """Mock storage backend."""
        mock = AsyncMock(spec=StorageBackend)
        mock.exists = AsyncMock(return_value=True)
        mock.list = AsyncMock(return_value=[])
        return mock

    @pytest.fixture
    def serializer(self) -> MsgspecSerializer:
        """Create a serializer instance."""
        return MsgspecSerializer()

    @pytest.fixture
    def base_mode(self, storage_backend: AsyncMock, temp_dir: Path, serializer: MsgspecSerializer) -> BaseMode:
        """Create a base mode instance."""
        return BaseMode(
            storage_backend=storage_backend,
            work_dir=temp_dir,
            serializer=serializer,
        )

    @pytest.mark.asyncio
    async def test_mode_initialization(self, base_mode: BaseMode):
        """Test base mode initialization."""
        # Verify mode properties
        assert base_mode.mode_name == "base"
        assert base_mode.is_readonly is False
        assert base_mode.is_started is False
        assert base_mode.storage_backend is storage_backend
        assert base_mode.work_dir == temp_dir
        assert base_mode.serializer is serializer

    @pytest.mark.asyncio
    async def test_start_mode(self, base_mode: BaseMode):
        """Test starting the base mode."""
        # Start mode
        await base_mode.start()

        # Verify mode is started
        assert base_mode.is_started is True
        assert storage_backend.initialize.called

    @pytest.mark.asyncio
    async def test_stop_mode(self, base_mode: BaseMode):
        """Test stopping the base mode."""
        # Start mode first
        await base_mode.start()

        # Stop mode
        await base_mode.stop()

        # Verify mode is stopped
        assert base_mode.is_started is False
        assert storage_backend.cleanup.called

    @pytest.mark.asyncio
    async def test_basic_operations(self, base_mode: BaseMode):
        """Test basic database operations."""
        # Start mode
        await base_mode.start()

        # Test put operation
        result = await base_mode.put(TenantID("test-tenant"), "key1", "value1")
        assert result is True

        # Test get operation
        value = await base_mode.get(TenantID("test-tenant"), "key1")
        assert value == "value1"

        # Test delete operation
        result = await base_mode.delete(TenantID("test-tenant"), "key1")
        assert result is True

        # Test get after delete
        value = await base_mode.get(TenantID("test-tenant"), "key1")
        assert value is None

    @pytest.mark.asyncio
    async def test_list_keys(self, base_mode: BaseMode):
        """Test listing keys for a tenant."""
        # Start mode
        await base_mode.start()

        # Put some data
        await base_mode.put(TenantID("test-tenant"), "key1", "value1")
        await base_mode.put(TenantID("test-tenant"), "key2", "value2")
        await base_mode.put(TenantID("other-tenant"), "key3", "value3")

        # List keys for specific tenant
        keys = await base_mode.list_keys(TenantID("test-tenant"))
        assert len(keys) == 2
        assert "key1" in keys
        assert "key2" in keys

        # Verify other tenant keys are not listed
        assert "key3" not in keys

    @pytest.mark.asyncio
    async def test_exists_check(self, base_mode: BaseMode):
        """Test key existence check."""
        # Start mode
        await base_mode.start()

        # Put data
        await base_mode.put(TenantID("test-tenant"), "key1", "value1")

        # Check existence
        exists = await base_mode.exists(TenantID("test-tenant"), "key1")
        assert exists is True

        # Check non-existent key
        exists = await base_mode.exists(TenantID("test-tenant"), "non_existent")
        assert exists is False

    @pytest.mark.asyncio
    async def test_statistics(self, base_mode: BaseMode):
        """Test mode statistics."""
        # Start mode
        await base_mode.start()

        # Perform operations
        for i in range(5):
            await base_mode.put(TenantID("test-tenant"), f"key{i}", f"value{i}")
            await base_mode.get(TenantID("test-tenant"), f"key{i}")

        # Get statistics
        stats = base_mode.get_statistics()

        # Verify statistics
        assert "operations_count" in stats
        assert "read_operations" in stats
        assert "write_operations" in stats
        assert "bytes_processed" in stats
        assert stats["operations_count"] == 10  # 5 put + 5 get

    @pytest.mark.asyncio
    async def test_error_handling(self, base_mode: BaseMode):
        """Test error handling."""
        # Start mode
        await base_mode.start()

        # Test error handling for invalid operations
        with pytest.raises(Exception):
            await base_mode.get(TenantID("invalid-tenant"), "key")

        with pytest.raises(Exception):
            await base_mode.put(TenantID("test-tenant"), None, "value")

    @pytest.mark.asyncio
    async def test_configuration(self, base_mode: BaseMode):
        """Test mode configuration."""
        # Test configuration updates
        config = {
            "timeout_seconds": 60,
            "max_retries": 3,
            "enable_logging": True,
        }
        base_mode.update_configuration(config)

        # Verify configuration was updated
        assert base_mode.timeout_seconds == 60
        assert base_mode.max_retries == 3
        assert base_mode.enable_logging is True

    @pytest.mark.asyncio
    async def test_health_check(self, base_mode: BaseMode):
        """Test mode health check."""
        # Start mode
        await base_mode.start()

        # Check health
        health = await base_mode.check_health()
        assert health is not None
        assert hasattr(health, 'is_healthy')

    @pytest.mark.asyncio
    async def test_metrics_collection(self, base_mode: BaseMode):
        """Test metrics collection."""
        # Start mode
        await base_mode.start()

        # Perform operations
        await base_mode.put(TenantID("test-tenant"), "key1", "value1")
        await base_mode.get(TenantID("test-tenant"), "key1")

        # Get metrics
        metrics = base_mode.get_metrics()

        # Verify metrics
        assert "total_operations" in metrics
        assert "read_operations" in metrics
        assert "write_operations" in metrics
        assert "average_latency_ms" in metrics
        assert metrics["total_operations"] == 2

    @pytest.mark.asyncio
    async def test_mode_switching(self, base_mode: BaseMode):
        """Test mode switching capabilities."""
        # Start mode
        await base_mode.start()

        # Perform some operations
        await base_mode.put(TenantID("test-tenant"), "key1", "value1")

        # Get initial state
        initial_stats = base_mode.get_statistics()

        # Reset mode
        await base_mode.reset()

        # Verify mode was reset
        reset_stats = base_mode.get_statistics()
        assert reset_stats["operations_count"] == 0
        assert reset_stats != initial_stats

    @pytest.mark.asyncio
    async def test_concurrent_operations(self, base_mode: BaseMode):
        """Test concurrent operations."""
        # Start mode
        await base_mode.start()

        async def concurrent_operation(task_id):
            for i in range(5):
                await base_mode.put(TenantID("test-tenant"), f"key_{task_id}_{i}", f"value_{task_id}_{i}")

        # Run operations concurrently
        tasks = [concurrent_operation(i) for i in range(3)]
        await asyncio.gather(*tasks)

        # Verify all operations completed
        stats = base_mode.get_statistics()
        assert stats["operations_count"] == 15  # 3 tasks * 5 operations each

    @pytest.mark.asyncio
    async def test_transaction_support(self, base_mode: BaseMode):
        """Test basic transaction support."""
        # Start mode
        await base_mode.start()

        # Create transaction
        options = TransactionOptions()
        transaction = await base_mode.create_transaction(
            tenant_id=TenantID("test-tenant"),
            options=options,
        )

        # Verify transaction
        assert transaction is not None
        assert transaction.tenant_id == TenantID("test-tenant")

        # Perform transaction operations
        await transaction.put("key1", "value1")
        value = await transaction.get("key1")
        assert value == "value1"

        # Clean up
        await transaction.rollback()

    @pytest.mark.asyncio
    async def test_backup_integration(self, base_mode: BaseMode):
        """Test backup integration."""
        # Start mode
        await base_mode.start()

        # Put some data
        await base_mode.put(TenantID("test-tenant"), "key1", "value1")

        # Test backup
        backup_result = await base_mode.create_backup(TenantID("test-tenant"))
        assert backup_result is not None
        assert "backup_id" in backup_result

    @pytest.mark.asyncio
    async def test_restore_integration(self, base_mode: BaseMode):
        """Test restore integration."""
        # Start mode
        await base_mode.start()

        # Create backup
        backup = await base_mode.create_backup(TenantID("test-tenant"))

        # Clear data
        await base_mode.delete(TenantID("test-tenant"), "key1")

        # Restore from backup
        restore_result = await base_mode.restore_backup(backup["backup_id"])
        assert restore_result is True

        # Verify data was restored
        value = await base_mode.get(TenantID("test-tenant"), "key1")
        assert value == "value1"

    @pytest.mark.asyncio
    async def test_performance_monitoring(self, base_mode: BaseMode):
        """Test performance monitoring."""
        # Start mode
        await base_mode.start()

        # Enable performance monitoring
        base_mode.enable_performance_monitoring()

        # Perform operations
        for i in range(10):
            await base_mode.put(TenantID("test-tenant"), f"key{i}", f"value{i}")

        # Get performance metrics
        perf_metrics = base_mode.get_performance_metrics()

        # Verify metrics
        assert "operation_count" in perf_metrics
        assert "average_latency" in perf_metrics
        assert "max_latency" in perf_metrics
        assert perf_metrics["operation_count"] == 10

    @pytest.mark.asyncio
    async def test_resource_monitoring(self, base_mode: BaseMode):
        """Test resource monitoring."""
        # Start mode
        await base_mode.start()

        # Enable resource monitoring
        base_mode.enable_resource_monitoring()

        # Perform operations
        await base_mode.put(TenantID("test-tenant"), "key1", "value1")

        # Get resource usage
        usage = base_mode.get_resource_usage()

        # Verify usage
        assert "memory_mb" in usage
        assert "cpu_percent" in usage
        assert "disk_bytes" in usage
        assert usage["memory_mb"] > 0

    @pytest.mark.asyncio
    async def test_mode_logging(self, base_mode: BaseMode):
        """Test mode logging."""
        # Enable logging
        base_mode.enable_logging()

        # Start mode
        await base_mode.start()

        # Perform operations
        await base_mode.put(TenantID("test-tenant"), "key1", "value1")

        # Get logs
        logs = base_mode.get_logs()

        # Verify logging
        assert len(logs) > 0
        assert any("put" in log["operation"] for log in logs)
        assert any(log["tenant_id"] == "test-tenant" for log in logs)

    @pytest.mark.asyncio
    async def test_mode_shutdown(self, base_mode: BaseMode):
        """Test mode shutdown."""
        # Start mode
        await base_mode.start()

        # Perform operations
        await base_mode.put(TenantID("test-tenant"), "key1", "value1")

        # Shutdown gracefully
        await base_mode.shutdown()

        # Verify mode is stopped
        assert base_mode.is_started is False

        # Verify cleanup was performed
        assert storage_backend.cleanup.called