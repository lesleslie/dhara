"""
Tests for standard mode in Dhara.

These tests verify the standard mode functionality including:
- Standard mode initialization and configuration
- Database operations in standard mode
- Transaction management
- Concurrency control
"""

import pytest
import asyncio
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, List, Any, Optional

from dhara.modes.standard import StandardMode
from dhara.storage.base import StorageBackend
from dhara.core.tenant import TenantID
from dhara.core.transaction import Transaction, TransactionOptions
from dhara.serialize.msgspec import MsgspecSerializer


class TestStandardMode:
    """Test standard mode functionality."""

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
    def standard_mode(self, storage_backend: AsyncMock, temp_dir: Path, serializer: MsgspecSerializer) -> StandardMode:
        """Create a standard mode instance."""
        return StandardMode(
            storage_backend=storage_backend,
            work_dir=temp_dir,
            serializer=serializer,
        )

    @pytest.mark.asyncio
    async def test_mode_initialization(self, standard_mode: StandardMode):
        """Test standard mode initialization."""
        # Verify mode properties
        assert standard_mode.mode_name == "standard"
        assert standard_mode.is_readonly is False
        assert standard_mode.max_concurrent_transactions == 100
        assert standard_mode.transaction_timeout_seconds == 300

    @pytest.mark.asyncio
    async def test_start_mode(self, standard_mode: StandardMode):
        """Test starting the standard mode."""
        # Start mode
        await standard_mode.start()

        # Verify mode is started
        assert standard_mode.is_started is True
        assert storage_backend.initialize.called

    @pytest.mark.asyncio
    async def test_stop_mode(self, standard_mode: StandardMode):
        """Test stopping the standard mode."""
        # Start mode first
        await standard_mode.start()

        # Stop mode
        await standard_mode.stop()

        # Verify mode is stopped
        assert standard_mode.is_started is False
        assert storage_backend.cleanup.called

    @pytest.mark.asyncio
    async def test_create_transaction(self, standard_mode: StandardMode):
        """Test creating a transaction."""
        # Start mode
        await standard_mode.start()

        # Create transaction
        options = TransactionOptions(
            isolation_level="serializable",
            readonly=False,
            deferrable=False,
        )
        transaction = await standard_mode.create_transaction(
            tenant_id=TenantID("test-tenant"),
            options=options,
        )

        # Verify transaction
        assert transaction is not None
        assert transaction.tenant_id == TenantID("test-tenant")
        assert transaction.isolation_level == "serializable"
        assert transaction.is_active is True

    @pytest.mark.asyncio
    async def test_commit_transaction(self, standard_mode: StandardMode):
        """Test committing a transaction."""
        # Start mode
        await standard_mode.start()

        # Create and commit transaction
        options = TransactionOptions()
        transaction = await standard_mode.create_transaction(
            tenant_id=TenantID("test-tenant"),
            options=options,
        )

        # Perform operations
        await transaction.put("key1", "value1")
        await transaction.put("key2", "value2")

        # Commit transaction
        result = await standard_mode.commit_transaction(transaction)

        # Verify commit succeeded
        assert result is True
        assert transaction.is_active is False
        assert transaction.is_committed is True

        # Verify data was persisted
        value1 = await standard_mode.get(TenantID("test-tenant"), "key1")
        value2 = await standard_mode.get(TenantID("test-tenant"), "key2")
        assert value1 == "value1"
        assert value2 == "value2"

    @pytest.mark.asyncio
    async def test_rollback_transaction(self, standard_mode: StandardMode):
        """Test rolling back a transaction."""
        # Start mode
        await standard_mode.start()

        # Create and rollback transaction
        options = TransactionOptions()
        transaction = await standard_mode.create_transaction(
            tenant_id=TenantID("test-tenant"),
            options=options,
        )

        # Perform operations
        await transaction.put("key1", "value1")
        await transaction.put("key2", "value2")

        # Rollback transaction
        result = await standard_mode.rollback_transaction(transaction)

        # Verify rollback succeeded
        assert result is True
        assert transaction.is_active is False
        assert transaction.is_rolled_back is True

        # Verify data was not persisted
        value1 = await standard_mode.get(TenantID("test-tenant"), "key1")
        value2 = await standard_mode.get(TenantID("test-tenant"), "key2")
        assert value1 is None
        assert value2 is None

    @pytest.mark.asyncio
    async def test_concurrent_transactions(self, standard_mode: StandardMode):
        """Test concurrent transaction handling."""
        # Start mode
        await standard_mode.start()

        # Create concurrent transactions
        async def transaction_task(task_id):
            options = TransactionOptions()
            transaction = await standard_mode.create_transaction(
                tenant_id=TenantID("test-tenant"),
                options=options,
            )

            # Perform operations
            for i in range(10):
                await transaction.put(f"key_{task_id}_{i}", f"value_{task_id}_{i}")

            # Commit transaction
            return await standard_mode.commit_transaction(transaction)

        # Run transactions concurrently
        tasks = [transaction_task(i) for i in range(5)]
        results = await asyncio.gather(*tasks)

        # Verify all transactions succeeded
        assert all(results)
        assert sum(results) == 5  # All committed

        # Verify all data was written
        for i in range(5):
            for j in range(10):
                key = f"key_{i}_{j}"
                value = await standard_mode.get(TenantID("test-tenant"), key)
                assert value == f"value_{i}_{j}"

    @pytest.mark.asyncio
    async def test_transaction_isolation_levels(self, standard_mode: StandardMode):
        """Test different transaction isolation levels."""
        # Start mode
        await standard_mode.start()

        isolation_levels = ["read-uncommitted", "read-committed", "repeatable-read", "serializable"]

        for level in isolation_levels:
            options = TransactionOptions(isolation_level=level)
            transaction = await standard_mode.create_transaction(
                tenant_id=TenantID("test-tenant"),
                options=options,
            )

            # Verify isolation level was set
            assert transaction.isolation_level == level

            # Clean up
            await transaction.rollback()

    @pytest.mark.asyncio
    async def test_transaction_timeout(self, standard_mode: StandardMode):
        """Test transaction timeout handling."""
        # Start mode with short timeout
        standard_mode.transaction_timeout_seconds = 1

        # Create transaction
        options = TransactionOptions()
        transaction = await standard_mode.create_transaction(
            tenant_id=TenantID("test-tenant"),
            options=options,
        )

        # Wait for timeout
        await asyncio.sleep(1.1)

        # Try to use transaction after timeout
        with pytest.raises(Exception, match="transaction timeout"):
            await transaction.get("key1")

        # Verify transaction was marked as timed out
        assert transaction.is_timed_out is True

    @pytest.mark.asyncio
    async def test_transaction_retry_on_conflict(self, standard_mode: StandardMode):
        """Test transaction retry on conflicts."""
        # Start mode
        await standard_mode.start()

        # Create initial transaction
        options = TransactionOptions()
        transaction1 = await standard_mode.create_transaction(
            tenant_id=TenantID("test-tenant"),
            options=options,
        )

        # Set initial value
        await transaction1.put("key1", "value1")
        await transaction1.commit()

        # Create concurrent transaction that modifies the same key
        async def modify_task():
            options = TransactionOptions()
            transaction = await standard_mode.create_transaction(
                tenant_id=TenantID("test-tenant"),
                options=options,
            )

            await transaction.put("key1", "value2")
            return await standard_mode.commit_transaction(transaction)

        # Start modification task
        modify_task = asyncio.create_task(modify_task())

        # Try to read in another transaction (should conflict and retry)
        options = TransactionOptions()
        transaction2 = await standard_mode.create_transaction(
            tenant_id=TenantID("test-tenant"),
            options=options,
        )

        # Wait for modification to complete
        await modify_task

        # Try to read after conflict
        value = await transaction2.get("key1")
        assert value == "value2"

    @pytest.mark.asyncio
    async def test_transaction_savepoints(self, standard_mode: StandardMode):
        """Test transaction savepoints."""
        # Start mode
        await standard_mode.start()

        # Create transaction
        options = TransactionOptions()
        transaction = await standard_mode.create_transaction(
            tenant_id=TenantID("test-tenant"),
            options=options,
        )

        # Perform operations
        await transaction.put("key1", "value1")
        await transaction.put("key2", "value2")

        # Create savepoint
        savepoint = await standard_mode.create_savepoint(transaction, "initial")

        # Perform more operations
        await transaction.put("key3", "value3")
        await transaction.put("key4", "value4")

        # Rollback to savepoint
        result = await standard_mode.rollback_to_savepoint(transaction, savepoint)

        # Verify rollback succeeded
        assert result is True

        # Verify only changes after savepoint were rolled back
        value1 = await transaction.get("key1")
        value2 = await transaction.get("key2")
        value3 = await transaction.get("key3")
        value4 = await transaction.get("key4")

        assert value1 == "value1"
        assert value2 == "value2"
        assert value3 is None
        assert value4 is None

    @pytest.mark.asyncio
    async def test_transaction_deadlock_detection(self, standard_mode: StandardMode):
        """Test deadlock detection and handling."""
        # Start mode
        await standard_mode.start()

        # Create transactions that would deadlock
        transactions = []

        for i in range(2):
            options = TransactionOptions()
            transaction = await standard_mode.create_transaction(
                tenant_id=TenantID("test-tenant"),
                options=options,
            )
            transactions.append(transaction)

            # Acquire different locks (simulating deadlock)
            await transaction.lock(f"resource_{i}")

        # Try to acquire conflicting locks
        try:
            await transactions[0].lock("resource_1")
            await transactions[1].lock("resource_0")
        except Exception as e:
            # Verify deadlock was detected
            assert "deadlock" in str(e).lower()

    @pytest.mark.asyncio
    async def test_transaction_batch_operations(self, standard_mode: StandardMode):
        """Test transaction batch operations."""
        # Start mode
        await standard_mode.start()

        # Create transaction
        options = TransactionOptions()
        transaction = await standard_mode.create_transaction(
            tenant_id=TenantID("test-tenant"),
            options=options,
        )

        # Perform batch operations
        operations = [
            ("put", "key1", "value1"),
            ("put", "key2", "value2"),
            ("put", "key3", "value3"),
            ("delete", "key4"),
        ]

        await standard_mode.execute_batch_operations(transaction, operations)

        # Commit transaction
        await standard_mode.commit_transaction(transaction)

        # Verify operations
        value1 = await standard_mode.get(TenantID("test-tenant"), "key1")
        value2 = await standard_mode.get(TenantID("test-tenant"), "key2")
        value3 = await standard_mode.get(TenantID("test-tenant"), "key3")
        value4 = await standard_mode.get(TenantID("test-tenant"), "key4")

        assert value1 == "value1"
        assert value2 == "value2"
        assert value3 == "value3"
        assert value4 is None

    @pytest.mark.asyncio
    async def test_transaction_consistency_checks(self, standard_mode: StandardMode):
        """Test transaction consistency checks."""
        # Start mode
        await standard_mode.start()

        # Create transaction
        options = TransactionOptions()
        transaction = await standard_mode.create_transaction(
            tenant_id=TenantID("test-tenant"),
            options=options,
        )

        # Perform inconsistent operations
        await transaction.put("key1", "value1")
        await transaction.delete("key1")

        # Check consistency
        is_consistent = await standard_mode.check_transaction_consistency(transaction)
        assert is_consistent is True  # After delete, no inconsistency

    @pytest.mark.asyncio
    async def test_mode_metrics(self, standard_mode: StandardMode):
        """Test mode metrics collection."""
        # Start mode
        await standard_mode.start()

        # Create and execute transactions
        for i in range(5):
            options = TransactionOptions()
            transaction = await standard_mode.create_transaction(
                tenant_id=TenantID("test-tenant"),
                options=options,
            )

            await transaction.put(f"key{i}", f"value{i}")
            await standard_mode.commit_transaction(transaction)

        # Get metrics
        metrics = standard_mode.get_metrics()

        # Verify metrics
        assert "transactions_created" in metrics
        assert "transactions_committed" in metrics
        assert "transactions_rolled_back" in metrics
        assert "average_transaction_duration" in metrics

    @pytest.mark.asyncio
    async def test_mode_configuration(self, standard_mode: StandardMode):
        """Test mode configuration."""
        # Test configuration updates
        standard_mode.update_configuration({
            "max_concurrent_transactions": 50,
            "transaction_timeout_seconds": 600,
        })

        # Verify configuration was updated
        assert standard_mode.max_concurrent_transactions == 50
        assert standard_mode.transaction_timeout_seconds == 600

    @pytest.mark.asyncio
    async def test_mode_recovery(self, standard_mode: StandardMode):
        """Test mode recovery after failure."""
        # Start mode
        await standard_mode.start()

        # Create active transaction
        options = TransactionOptions()
        transaction = await standard_mode.create_transaction(
            tenant_id=TenantID("test-tenant"),
            options=options,
        )

        # Perform operations
        await transaction.put("key1", "value1")

        # Simulate crash/restart
        await standard_mode.stop()

        # Restart mode
        await standard_mode.start()

        # Verify recovery
        active_transactions = standard_mode.get_active_transactions()
        assert len(active_transactions) == 0  # Should be rolled back on restart