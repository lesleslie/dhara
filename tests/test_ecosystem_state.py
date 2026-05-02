"""Tests for dhara/mcp/ecosystem_state.py — service and event persistence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dhara.mcp.ecosystem_state import (
    EcosystemStateStore,
    EventRetention,
    _utcnow,
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


class TestEcosystemStateService:
    def test_upsert_and_get(self, connection):
        store = EcosystemStateStore(connection)
        record = store.upsert_service("s1", "adapter", capabilities=["storage"])
        assert record["service_id"] == "s1"
        assert record["capabilities"] == ["storage"]

        fetched = store.get_service("s1")
        assert fetched is not None
        assert fetched["service_type"] == "adapter"

    def test_get_missing(self, connection):
        store = EcosystemStateStore(connection)
        assert store.get_service("nope") is None

    def test_upsert_preserves_created_at(self, connection):
        store = EcosystemStateStore(connection)
        r1 = store.upsert_service("s1", "type1")
        created = r1["created_at"]
        store.upsert_service("s1", "type2")
        assert store.get_service("s1")["created_at"] == created

    def test_upsert_updates_timestamps(self, connection):
        store = EcosystemStateStore(connection)
        r1 = store.upsert_service("s1", "type1")
        r2 = store.upsert_service("s1", "type1")
        assert r2["updated_at"] >= r1["updated_at"]

    def test_list_all(self, connection):
        store = EcosystemStateStore(connection)
        store.upsert_service("a", "t1")
        store.upsert_service("b", "t2")
        services = store.list_services()
        assert len(services) == 2

    def test_list_filter_by_type(self, connection):
        store = EcosystemStateStore(connection)
        store.upsert_service("a", "adapter")
        store.upsert_service("b", "tool")
        assert len(store.list_services(service_type="adapter")) == 1

    def test_list_filter_by_status(self, connection):
        store = EcosystemStateStore(connection)
        store.upsert_service("a", "t", status="healthy")
        store.upsert_service("b", "t", status="unhealthy")
        assert len(store.list_services(status="healthy")) == 1

    def test_list_filter_by_capability(self, connection):
        store = EcosystemStateStore(connection)
        store.upsert_service("a", "t", capabilities=["storage", "cache"])
        store.upsert_service("b", "t", capabilities=["cache"])
        assert len(store.list_services(capability="storage")) == 1

    def test_list_sorted_by_id(self, connection):
        store = EcosystemStateStore(connection)
        store.upsert_service("z", "t")
        store.upsert_service("a", "t")
        services = store.list_services()
        assert services[0]["service_id"] == "a"

    def test_normalize_adds_defaults(self, connection):
        store = EcosystemStateStore(connection)
        store.upsert_service("s1", "t")
        record = store.get_service("s1")
        assert record["schema_version"] == 1
        assert record["status"] == "unknown"
        assert record["capabilities"] == []
        assert record["metadata"] == {}

    def test_heartbeat_at_defaults_to_now(self, connection):
        store = EcosystemStateStore(connection)
        record = store.upsert_service("s1", "t")
        assert record["heartbeat_at"] is not None


class TestEcosystemStateEvents:
    def test_record_and_list(self, connection):
        store = EcosystemStateStore(
            connection,
            event_retention=EventRetention(retention_days=365),
        )
        store.record_event("deploy", "mahavishnu", payload={"repo": "akosha"})
        events = store.list_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "deploy"

    def test_record_with_custom_timestamp(self, connection):
        store = EcosystemStateStore(
            connection,
            event_retention=EventRetention(retention_days=365),
        )
        ts = _ts(hours_ago=1)
        store.record_event("e", "src", timestamp=ts)
        events = store.list_events()
        assert len(events) == 1
        assert events[0]["timestamp"] == ts

    def test_list_filter_by_type(self, connection):
        store = EcosystemStateStore(
            connection,
            event_retention=EventRetention(retention_days=365),
        )
        store.record_event("deploy", "s1")
        store.record_event("error", "s1")
        assert len(store.list_events(event_type="deploy")) == 1

    def test_list_filter_by_source(self, connection):
        store = EcosystemStateStore(
            connection,
            event_retention=EventRetention(retention_days=365),
        )
        store.record_event("e", "src_a")
        store.record_event("e", "src_b")
        assert len(store.list_events(source_service="src_a")) == 1

    def test_list_filter_by_related(self, connection):
        store = EcosystemStateStore(
            connection,
            event_retention=EventRetention(retention_days=365),
        )
        store.record_event("e", "s1", related_service="target")
        store.record_event("e", "s1", related_service="other")
        assert len(store.list_events(related_service="target")) == 1

    def test_list_limit(self, connection):
        store = EcosystemStateStore(
            connection,
            event_retention=EventRetention(retention_days=365),
        )
        for i in range(10):
            store.record_event("e", "s")
        events = store.list_events(limit=3)
        assert len(events) == 3

    def test_prune_old_events(self, connection):
        store = EcosystemStateStore(
            connection,
            event_retention=EventRetention(retention_days=1),
        )
        store.record_event("old", "s", timestamp=_ts(48))
        store.record_event("new", "s", timestamp=_ts(1))
        events = store.list_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "new"

    def test_normalize_event(self, connection):
        store = EcosystemStateStore(
            connection,
            event_retention=EventRetention(retention_days=365),
        )
        store.record_event("e", "s")
        event = store.list_events()[0]
        assert event["schema_version"] == 1
        assert event["payload"] == {}
