"""Tests for dhara.mcp.ecosystem_state.AsyncEcosystemStateStore async methods."""

from __future__ import annotations

import pytest

from dhara.mcp.ecosystem_state import AsyncEcosystemStateStore, EventRetention
from dhara.storage.memory import AsyncMemoryStorage
from dhara.core.connection import AsyncConnection


class TestUpsertServiceAsync:
    @pytest.mark.asyncio
    async def test_upsert_service_async(self):
        """upsert_service_async creates a service record."""
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        store = AsyncEcosystemStateStore(conn)

        result = await store.upsert_service_async(
            service_id="svc-1",
            service_type="test",
            capabilities=["read", "write"],
        )
        assert result["service_id"] == "svc-1"
        assert result["service_type"] == "test"
        assert result["capabilities"] == ["read", "write"]


class TestGetServiceAsync:
    @pytest.mark.asyncio
    async def test_get_service_async_existing(self):
        """get_service_async retrieves an existing service."""
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        store = AsyncEcosystemStateStore(conn)

        await store.upsert_service_async(
            service_id="svc-2",
            service_type="worker",
        )
        result = await store.get_service_async("svc-2")
        assert result is not None
        assert result["service_id"] == "svc-2"

    @pytest.mark.asyncio
    async def test_get_service_async_missing(self):
        """get_service_async returns None for missing service."""
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        store = AsyncEcosystemStateStore(conn)
        result = await store.get_service_async("nonexistent")
        assert result is None


class TestListServicesAsync:
    @pytest.mark.asyncio
    async def test_list_services_async(self):
        """list_services_async returns all services."""
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        store = AsyncEcosystemStateStore(conn)

        await store.upsert_service_async(service_id="svc-a", service_type="cache")
        await store.upsert_service_async(service_id="svc-b", service_type="cache")
        await store.upsert_service_async(service_id="svc-c", service_type="storage")

        all_services = await store.list_services_async()
        assert len(all_services) == 3

        cache_only = await store.list_services_async(service_type="cache")
        assert len(cache_only) == 2


class TestRecordEventAsync:
    @pytest.mark.asyncio
    async def test_record_event_async(self):
        """record_event_async appends an event."""
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        store = AsyncEcosystemStateStore(conn)

        result = await store.record_event_async(
            event_type="deployment",
            source_service="deployer",
            payload={"version": "1.0.0"},
        )
        assert result["event_type"] == "deployment"
        assert result["source_service"] == "deployer"


class TestListEventsAsync:
    @pytest.mark.asyncio
    async def test_list_events_async(self):
        """list_events_async returns recorded events."""
        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        store = AsyncEcosystemStateStore(conn)

        await store.record_event_async(event_type="start", source_service="svc-1")
        await store.record_event_async(event_type="stop", source_service="svc-1")
        await store.record_event_async(event_type="start", source_service="svc-2")

        all_events = await store.list_events_async()
        assert len(all_events) == 3

        svc1_events = await store.list_events_async(source_service="svc-1")
        assert len(svc1_events) == 2
