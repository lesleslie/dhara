"""Tests for dhara/mcp/ecosystem_state.py — service and event persistence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from dhara.collections.dict import PersistentDict
from dhara.collections.list import PersistentList
from dhara.mcp.ecosystem_state import (
    AsyncEcosystemStateStore,
    EventRetention,
    _prune_events,
)


def _ts(hours_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


class TestEventRetention:
    def test_default(self):
        assert EventRetention().retention_days == 30

    def test_cutoff(self):
        r = EventRetention(retention_days=14)
        cutoff = r.cutoff()
        now = datetime.now(timezone.utc)
        assert (now - cutoff).days >= 13


class TestEcosystemStateInitialization:
    async def test_existing_root_skips_commit(self, async_connection):
        root = await async_connection.get_root()
        root["ecosystem_services"] = PersistentDict()
        root["ecosystem_events"] = PersistentList()
        original_commit = async_connection.commit
        called: list[int] = []

        async def tracking_commit() -> None:
            called.append(1)

        async_connection.commit = tracking_commit  # type: ignore[method-assign]

        try:
            store = AsyncEcosystemStateStore(async_connection)
            assert await store._services() is root["ecosystem_services"]
            assert await store._events() is root["ecosystem_events"]
            assert called == []
        finally:
            async_connection.commit = original_commit  # type: ignore[method-assign]


class TestEcosystemStateService:
    async def test_upsert_and_get(self, async_connection):
        store = AsyncEcosystemStateStore(async_connection)
        record = await store.upsert_service_async(
            "s1", "adapter", capabilities=["storage"]
        )
        assert record["service_id"] == "s1"
        assert record["capabilities"] == ["storage"]

        fetched = await store.get_service_async("s1")
        assert fetched is not None
        assert fetched["service_type"] == "adapter"

    async def test_get_missing(self, async_connection):
        store = AsyncEcosystemStateStore(async_connection)
        assert await store.get_service_async("nope") is None

    async def test_upsert_preserves_created_at(self, async_connection):
        store = AsyncEcosystemStateStore(async_connection)
        r1 = await store.upsert_service_async("s1", "type1")
        created = r1["created_at"]
        await store.upsert_service_async("s1", "type2")
        fetched = await store.get_service_async("s1")
        assert fetched is not None
        assert fetched["created_at"] == created

    async def test_upsert_updates_timestamps(self, async_connection):
        store = AsyncEcosystemStateStore(async_connection)
        r1 = await store.upsert_service_async("s1", "type1")
        r2 = await store.upsert_service_async("s1", "type1")
        assert r2["updated_at"] >= r1["updated_at"]

    async def test_list_all(self, async_connection):
        store = AsyncEcosystemStateStore(async_connection)
        await store.upsert_service_async("a", "t1")
        await store.upsert_service_async("b", "t2")
        services = await store.list_services_async()
        assert len(services) == 2

    async def test_list_filter_by_type(self, async_connection):
        store = AsyncEcosystemStateStore(async_connection)
        await store.upsert_service_async("a", "adapter")
        await store.upsert_service_async("b", "tool")
        assert len(await store.list_services_async(service_type="adapter")) == 1

    async def test_list_filter_by_status(self, async_connection):
        store = AsyncEcosystemStateStore(async_connection)
        await store.upsert_service_async("a", "t", status="healthy")
        await store.upsert_service_async("b", "t", status="unhealthy")
        assert len(await store.list_services_async(status="healthy")) == 1

    async def test_list_filter_by_capability(self, async_connection):
        store = AsyncEcosystemStateStore(async_connection)
        await store.upsert_service_async("a", "t", capabilities=["storage", "cache"])
        await store.upsert_service_async("b", "t", capabilities=["cache"])
        assert len(await store.list_services_async(capability="storage")) == 1

    async def test_list_sorted_by_id(self, async_connection):
        store = AsyncEcosystemStateStore(async_connection)
        await store.upsert_service_async("z", "t")
        await store.upsert_service_async("a", "t")
        services = await store.list_services_async()
        assert services[0]["service_id"] == "a"

    async def test_normalize_adds_defaults(self, async_connection):
        store = AsyncEcosystemStateStore(async_connection)
        await store.upsert_service_async("s1", "t")
        record = await store.get_service_async("s1")
        assert record is not None
        assert record["schema_version"] == 1
        assert record["status"] == "unknown"
        assert record["capabilities"] == []
        assert record["metadata"] == {}

    async def test_heartbeat_at_defaults_to_now(self, async_connection):
        store = AsyncEcosystemStateStore(async_connection)
        record = await store.upsert_service_async("s1", "t")
        assert record["heartbeat_at"] is not None


class TestEcosystemStateEvents:
    async def test_record_and_list(self, async_connection):
        store = AsyncEcosystemStateStore(
            async_connection,
            event_retention=EventRetention(retention_days=365),
        )
        await store.record_event_async(
            "deploy", "mahavishnu", payload={"repo": "akosha"}
        )
        events = await store.list_events_async()
        assert len(events) == 1
        assert events[0]["event_type"] == "deploy"

    async def test_record_with_custom_timestamp(self, async_connection):
        store = AsyncEcosystemStateStore(
            async_connection,
            event_retention=EventRetention(retention_days=365),
        )
        ts = _ts(hours_ago=1)
        await store.record_event_async("e", "src", timestamp=ts)
        events = await store.list_events_async()
        assert len(events) == 1
        assert events[0]["timestamp"] == ts

    async def test_list_filter_by_type(self, async_connection):
        store = AsyncEcosystemStateStore(
            async_connection,
            event_retention=EventRetention(retention_days=365),
        )
        await store.record_event_async("deploy", "s1")
        await store.record_event_async("error", "s1")
        assert len(await store.list_events_async(event_type="deploy")) == 1

    async def test_list_filter_by_source(self, async_connection):
        store = AsyncEcosystemStateStore(
            async_connection,
            event_retention=EventRetention(retention_days=365),
        )
        await store.record_event_async("e", "src_a")
        await store.record_event_async("e", "src_b")
        assert len(await store.list_events_async(source_service="src_a")) == 1

    async def test_list_filter_by_related(self, async_connection):
        store = AsyncEcosystemStateStore(
            async_connection,
            event_retention=EventRetention(retention_days=365),
        )
        await store.record_event_async("e", "s1", related_service="target")
        await store.record_event_async("e", "s1", related_service="other")
        assert len(await store.list_events_async(related_service="target")) == 1

    async def test_list_limit(self, async_connection):
        store = AsyncEcosystemStateStore(
            async_connection,
            event_retention=EventRetention(retention_days=365),
        )
        for i in range(10):
            await store.record_event_async("e", "s")
        events = await store.list_events_async(limit=3)
        assert len(events) == 3

    async def test_prune_old_events(self, async_connection):
        store = AsyncEcosystemStateStore(
            async_connection,
            event_retention=EventRetention(retention_days=1),
        )
        await store.record_event_async("old", "s", timestamp=_ts(48))
        await store.record_event_async("new", "s", timestamp=_ts(1))
        events = await store.list_events_async()
        assert len(events) == 1
        assert events[0]["event_type"] == "new"

    async def test_normalize_event(self, async_connection):
        store = AsyncEcosystemStateStore(
            async_connection,
            event_retention=EventRetention(retention_days=365),
        )
        await store.record_event_async("e", "s")
        events = await store.list_events_async()
        assert len(events) == 1
        event = events[0]
        assert event["schema_version"] == 1
        assert event["payload"] == {}

    async def test_list_events_handles_invalid_and_naive_timestamps(self, async_connection):
        store = AsyncEcosystemStateStore(
            async_connection,
            event_retention=EventRetention(retention_days=365),
        )
        # Force initialization so _events() returns the underlying list
        await store._ensure_root_async()
        events = await store._events()
        events.append(
            PersistentDict(
                {
                    "event_type": "broken",
                    "source_service": "s",
                    "timestamp": "not-a-timestamp",
                }
            )
        )
        events.append(
            PersistentDict(
                {
                    "event_type": "naive",
                    "source_service": "s",
                    "timestamp": datetime.now().isoformat(),
                }
            )
        )

        results = await store.list_events_async(limit=None)
        assert [event["event_type"] for event in results] == ["broken", "naive"]

    async def test_list_events_skips_old_manual_event(self, async_connection):
        store = AsyncEcosystemStateStore(
            async_connection,
            event_retention=EventRetention(retention_days=1),
        )
        await store._ensure_root_async()
        events = await store._events()
        events.append(
            PersistentDict(
                {
                    "event_type": "old",
                    "source_service": "s",
                    "timestamp": _ts(48),
                }
            )
        )

        assert await store.list_events_async(limit=None) == []

    async def test_prune_events_handles_invalid_and_naive_timestamps(self, async_connection):
        store = AsyncEcosystemStateStore(
            async_connection,
            event_retention=EventRetention(retention_days=365),
        )
        await store._ensure_root_async()
        events = await store._events()
        events.append(
            PersistentDict(
                {
                    "event_type": "broken",
                    "source_service": "s",
                    "timestamp": "not-a-timestamp",
                }
            )
        )
        events.append(
            PersistentDict(
                {
                    "event_type": "naive",
                    "source_service": "s",
                    "timestamp": datetime.now().isoformat(),
                }
            )
        )

        _prune_events(events, store.event_retention)

        assert [event["event_type"] for event in events] == ["broken", "naive"]