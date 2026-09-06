"""Targeted coverage tests for ``dhara.mcp.ecosystem_state``.

The module exposes ``AsyncEcosystemStateStore`` plus a handful of
helpers (``_utcnow``, ``_normalize_service_record``,
``_normalize_event_record``, ``_prune_events``, ``EventRetention``).
Backed by ``AsyncConnection`` + ``AsyncMemoryStorage`` — see
``tests/conftest.py::async_connection`` for the canonical fixture.

These tests exercise every public surface (services/events upsert/get/
list/record + pruning) plus the internal helpers and the
``EcosystemStateStore`` backward-compatible alias.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from dhara.collections.dict import PersistentDict
from dhara.collections.list import PersistentList
from dhara.core.connection import AsyncConnection
from dhara.mcp.ecosystem_state import (
    AsyncEcosystemStateStore,
    EcosystemStateStore,
    EventRetention,
    _normalize_event_record,
    _normalize_service_record,
    _prune_events,
    _utcnow,
)
from dhara.storage import AsyncMemoryStorage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def store(async_connection: AsyncConnection) -> AsyncEcosystemStateStore:
    """An ``AsyncEcosystemStateStore`` rooted at a fresh ``async_connection``.

    Pre-initialises the root collections so direct ``_services()`` /
    ``_events()`` access works in tests that bypass the public upsert/record
    surface.
    """
    s = AsyncEcosystemStateStore(async_connection)
    await s._ensure_root_async()
    return s


# ---------------------------------------------------------------------------
# _utcnow / EventRetention
# ---------------------------------------------------------------------------


def test_utcnow_returns_aware_utc_datetime() -> None:
    """``_utcnow`` must return a timezone-aware UTC ``datetime``."""
    now = _utcnow()
    assert isinstance(now, datetime)
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_event_retention_default_30_days() -> None:
    """Default retention should be 30 days."""
    retention = EventRetention()
    assert retention.retention_days == 30


def test_event_retention_custom_days() -> None:
    """``retention_days`` should be reflected in ``cutoff()``."""
    retention = EventRetention(retention_days=7)
    cutoff = retention.cutoff()
    delta = _utcnow() - cutoff
    # Allow a tiny fudge factor for the call taking a moment.
    assert 6.9 <= delta.total_seconds() / 86400 <= 7.1


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def test_normalize_service_record_defaults() -> None:
    """Missing schema_version/capabilities/metadata/status should be filled in."""
    payload = _normalize_service_record({"service_id": "svc-1"})
    assert payload == {
        "service_id": "svc-1",
        "schema_version": 1,
        "capabilities": [],
        "metadata": {},
        "status": "unknown",
    }


def test_normalize_service_record_preserves_existing_fields() -> None:
    """Existing schema fields should be preserved verbatim."""
    payload = _normalize_service_record(
        {
            "service_id": "svc-2",
            "schema_version": 3,
            "capabilities": ["x", "y"],
            "metadata": {"k": "v"},
            "status": "healthy",
            "custom_extra": "kept",
        }
    )
    assert payload["schema_version"] == 3
    assert payload["capabilities"] == ["x", "y"]
    assert payload["metadata"] == {"k": "v"}
    assert payload["status"] == "healthy"
    assert payload["custom_extra"] == "kept"


def test_normalize_service_record_does_not_mutate_input() -> None:
    """``setdefault`` semantics: the input dict must not gain the new keys."""
    original = {"service_id": "svc-3"}
    snapshot = dict(original)
    _normalize_service_record(original)
    assert original == snapshot


def test_normalize_event_record_defaults() -> None:
    """Missing schema_version/payload should default to safe values."""
    payload = _normalize_event_record({"event_type": "evt", "source_service": "s"})
    assert payload == {
        "event_type": "evt",
        "source_service": "s",
        "schema_version": 1,
        "payload": {},
    }


def test_normalize_event_record_preserves_existing_fields() -> None:
    """Existing event fields must be preserved verbatim."""
    payload = _normalize_event_record(
        {
            "event_type": "deploy",
            "source_service": "mahavishnu",
            "schema_version": 7,
            "payload": {"region": "us-east-1"},
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
    )
    assert payload["schema_version"] == 7
    assert payload["payload"] == {"region": "us-east-1"}
    assert payload["timestamp"] == "2026-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# _prune_events — direct test (the helper is private but a critical path)
# ---------------------------------------------------------------------------


def _build_persistent_event(timestamp: str) -> PersistentDict:
    return PersistentDict(
        {
            "event_type": "x",
            "source_service": "s",
            "timestamp": timestamp,
            "payload": {},
            "schema_version": 1,
        }
    )


def test_prune_events_keeps_recent_with_aware_timestamp() -> None:
    """Recent events with timezone-aware timestamps are kept."""
    events = PersistentList(
        [
            _build_persistent_event(
                (_utcnow() - timedelta(hours=1)).isoformat()
            ),
        ]
    )
    retention = EventRetention(retention_days=30)
    _prune_events(events, retention)
    assert len(events) == 1


def test_prune_events_drops_old_with_aware_timestamp() -> None:
    """Old events with timezone-aware timestamps are pruned in place."""
    events = PersistentList(
        [
            _build_persistent_event(
                (_utcnow() - timedelta(days=60)).isoformat()
            ),
        ]
    )
    retention = EventRetention(retention_days=30)
    _prune_events(events, retention)
    assert len(events) == 0


def test_prune_events_treats_naive_timestamp_as_utc() -> None:
    """Naive timestamps should be normalised to UTC and re-evaluated."""
    # Naive timestamp 1 hour ago — should be kept.
    one_hour_ago = (_utcnow() - timedelta(hours=1)).replace(tzinfo=None).isoformat()
    # Naive timestamp 60 days ago — should be pruned.
    sixty_days_ago = (_utcnow() - timedelta(days=60)).replace(tzinfo=None).isoformat()

    events = PersistentList(
        [
            _build_persistent_event(one_hour_ago),
            _build_persistent_event(sixty_days_ago),
        ]
    )
    retention = EventRetention(retention_days=30)
    _prune_events(events, retention)
    assert len(events) == 1


def test_prune_events_keeps_when_timestamp_unparseable() -> None:
    """An unparseable timestamp should not be pruned (defensive default)."""
    events = PersistentList(
        [
            _build_persistent_event("not-a-date"),
            _build_persistent_event(""),
        ]
    )
    retention = EventRetention(retention_days=30)
    _prune_events(events, retention)
    assert len(events) == 2


def test_prune_events_keeps_when_timestamp_missing() -> None:
    """An event without a timestamp key should not be pruned."""
    events = PersistentList(
        [PersistentDict({"event_type": "x", "source_service": "s"})]
    )
    retention = EventRetention(retention_days=30)
    _prune_events(events, retention)
    assert len(events) == 1


def test_prune_events_keeps_when_timestamp_not_a_string() -> None:
    """Non-string timestamps (e.g. None) should fall through unpruned."""
    events = PersistentList(
        [
            PersistentDict(
                {"event_type": "x", "source_service": "s", "timestamp": None}
            ),
        ]
    )
    retention = EventRetention(retention_days=30)
    _prune_events(events, retention)
    assert len(events) == 1


def test_prune_events_no_op_when_lengths_match() -> None:
    """If nothing is pruned, the in-place slice assignment should still execute
    without errors (and length should be preserved)."""
    events = PersistentList(
        [_build_persistent_event(_utcnow().isoformat())]
    )
    retention = EventRetention(retention_days=30)
    _prune_events(events, retention)
    assert len(events) == 1


# ---------------------------------------------------------------------------
# AsyncEcosystemStateStore — root initialisation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_root_initialises_collections(store: AsyncEcosystemStateStore) -> None:
    """First call should create ``ecosystem_services`` and ``ecosystem_events``."""
    root = await store.connection.get_root()
    assert "ecosystem_services" in root
    assert "ecosystem_events" in root
    assert isinstance(root["ecosystem_services"], PersistentDict)
    assert isinstance(root["ecosystem_events"], PersistentList)
    assert store._initialized is True


@pytest.mark.asyncio
async def test_ensure_root_idempotent(store: AsyncEcosystemStateStore) -> None:
    """A second call to ``_ensure_root_async`` should be a no-op (no commit)."""
    # The fixture already calls _ensure_root_async once; a second call
    # should not re-commit or mutate state.
    await store._ensure_root_async()
    services = await store._services()
    events = await store._events()
    assert len(services) == 0
    assert len(events) == 0


@pytest.mark.asyncio
async def test_ensure_root_preserves_existing_data(
    async_connection: AsyncConnection,
) -> None:
    """If collections already exist, ``_ensure_root_async`` must not reset them."""
    root = await async_connection.get_root()
    root["ecosystem_services"] = PersistentDict({"existing": {"service_id": "x"}})
    root["ecosystem_events"] = PersistentList([{"event_type": "y"}])
    await async_connection.commit()

    store = AsyncEcosystemStateStore(async_connection)
    await store._ensure_root_async()

    services = await store._services()
    assert "existing" in services
    assert services["existing"]["service_id"] == "x"


# ---------------------------------------------------------------------------
# upsert_service_async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_service_creates_new_record(
    store: AsyncEcosystemStateStore,
) -> None:
    """First upsert should create the record with all default fields populated."""
    record = await store.upsert_service_async(
        service_id="svc-1",
        service_type="worker",
        capabilities=["x", "y"],
        metadata={"region": "us-east-1"},
        status="healthy",
    )

    assert record["service_id"] == "svc-1"
    assert record["service_type"] == "worker"
    assert record["capabilities"] == ["x", "y"]
    assert record["metadata"] == {"region": "us-east-1"}
    assert record["status"] == "healthy"
    assert record["schema_version"] == 1
    assert record["created_at"] == record["updated_at"]
    assert record["heartbeat_at"] is not None

    # And the store should be queryable.
    fetched = await store.get_service_async("svc-1")
    assert fetched is not None
    assert fetched["service_id"] == "svc-1"


@pytest.mark.asyncio
async def test_upsert_service_preserves_created_at_on_update(
    store: AsyncEcosystemStateStore,
) -> None:
    """Subsequent upserts must NOT touch the original ``created_at``."""
    first = await store.upsert_service_async(
        service_id="svc-2", service_type="worker"
    )
    second = await store.upsert_service_async(
        service_id="svc-2",
        service_type="worker",
        status="degraded",
        capabilities=["z"],
    )
    assert second["created_at"] == first["created_at"]
    assert second["status"] == "degraded"
    assert second["capabilities"] == ["z"]


@pytest.mark.asyncio
async def test_upsert_service_default_capabilities_and_metadata(
    store: AsyncEcosystemStateStore,
) -> None:
    """When capabilities/metadata are None, store an empty list/dict."""
    record = await store.upsert_service_async(
        service_id="svc-3", service_type="worker"
    )
    assert record["capabilities"] == []
    assert record["metadata"] == {}


@pytest.mark.asyncio
async def test_upsert_service_lease_expires_at_round_trips(
    store: AsyncEcosystemStateStore,
) -> None:
    """``lease_expires_at`` should round-trip through the store."""
    lease = "2026-12-01T00:00:00+00:00"
    record = await store.upsert_service_async(
        service_id="svc-lease",
        service_type="worker",
        lease_expires_at=lease,
    )
    assert record["lease_expires_at"] == lease
    fetched = await store.get_service_async("svc-lease")
    assert fetched is not None
    assert fetched["lease_expires_at"] == lease


@pytest.mark.asyncio
async def test_upsert_service_explicit_heartbeat(
    store: AsyncEcosystemStateStore,
) -> None:
    """Explicit ``heartbeat_at`` should be stored verbatim."""
    hb = "2026-06-01T00:00:00+00:00"
    record = await store.upsert_service_async(
        service_id="svc-hb",
        service_type="worker",
        heartbeat_at=hb,
    )
    assert record["heartbeat_at"] == hb


# ---------------------------------------------------------------------------
# get_service_async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_service_returns_none_when_missing(
    store: AsyncEcosystemStateStore,
) -> None:
    """``get_service_async`` returns None for unknown service IDs."""
    assert await store.get_service_async("does-not-exist") is None


@pytest.mark.asyncio
async def test_get_service_fills_missing_defaults(
    store: AsyncEcosystemStateStore,
) -> None:
    """A persisted record lacking default fields should be normalised on read."""
    services = await store._services()
    services["legacy"] = PersistentDict({"service_id": "legacy"})
    await store.connection.commit()

    fetched = await store.get_service_async("legacy")
    assert fetched is not None
    assert fetched["schema_version"] == 1
    assert fetched["capabilities"] == []
    assert fetched["metadata"] == {}
    assert fetched["status"] == "unknown"


# ---------------------------------------------------------------------------
# list_services_async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_services_returns_empty_when_no_records(
    store: AsyncEcosystemStateStore,
) -> None:
    """Empty store returns an empty list."""
    assert await store.list_services_async() == []


@pytest.mark.asyncio
async def test_list_services_sorted_by_service_id(
    store: AsyncEcosystemStateStore,
) -> None:
    """Results should be sorted by ``service_id`` for deterministic output."""
    for sid in ("b", "a", "c"):
        await store.upsert_service_async(service_id=sid, service_type="worker")

    services = await store.list_services_async()
    assert [s["service_id"] for s in services] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_list_services_filter_by_type(
    store: AsyncEcosystemStateStore,
) -> None:
    """``service_type`` filter should narrow results."""
    await store.upsert_service_async(service_id="w1", service_type="worker")
    await store.upsert_service_async(service_id="w2", service_type="worker")
    await store.upsert_service_async(service_id="r1", service_type="router")

    workers = await store.list_services_async(service_type="worker")
    assert {s["service_id"] for s in workers} == {"w1", "w2"}
    assert all(s["service_type"] == "worker" for s in workers)


@pytest.mark.asyncio
async def test_list_services_filter_by_status(
    store: AsyncEcosystemStateStore,
) -> None:
    """``status`` filter should narrow results."""
    await store.upsert_service_async(
        service_id="h1", service_type="worker", status="healthy"
    )
    await store.upsert_service_async(
        service_id="d1", service_type="worker", status="degraded"
    )

    healthy = await store.list_services_async(status="healthy")
    assert [s["service_id"] for s in healthy] == ["h1"]


@pytest.mark.asyncio
async def test_list_services_filter_by_capability(
    store: AsyncEcosystemStateStore,
) -> None:
    """``capability`` filter should keep services whose capabilities include it."""
    await store.upsert_service_async(
        service_id="c1", service_type="worker", capabilities=["a", "b"]
    )
    await store.upsert_service_async(
        service_id="c2", service_type="worker", capabilities=["b"]
    )
    await store.upsert_service_async(
        service_id="c3", service_type="worker", capabilities=["c"]
    )

    has_b = await store.list_services_async(capability="b")
    assert {s["service_id"] for s in has_b} == {"c1", "c2"}


@pytest.mark.asyncio
async def test_list_services_combined_filters(
    store: AsyncEcosystemStateStore,
) -> None:
    """Multiple filters should all be applied."""
    await store.upsert_service_async(
        service_id="m1",
        service_type="worker",
        status="healthy",
        capabilities=["x"],
    )
    await store.upsert_service_async(
        service_id="m2",
        service_type="worker",
        status="degraded",
        capabilities=["x"],
    )
    await store.upsert_service_async(
        service_id="m3",
        service_type="router",
        status="healthy",
        capabilities=["x"],
    )

    matched = await store.list_services_async(
        service_type="worker", status="healthy", capability="x"
    )
    assert [s["service_id"] for s in matched] == ["m1"]


# ---------------------------------------------------------------------------
# record_event_async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_event_persists_with_defaults(
    store: AsyncEcosystemStateStore,
) -> None:
    """A bare event should be persisted with all default fields populated."""
    event = await store.record_event_async(
        event_type="deploy",
        source_service="mahavishnu",
        payload={"region": "us-east-1"},
    )

    assert event["event_type"] == "deploy"
    assert event["source_service"] == "mahavishnu"
    assert event["payload"] == {"region": "us-east-1"}
    assert event["schema_version"] == 1
    assert event["timestamp"] is not None
    assert event["related_service"] is None

    events = await store._events()
    assert len(events) == 1


@pytest.mark.asyncio
async def test_record_event_with_related_service(
    store: AsyncEcosystemStateStore,
) -> None:
    """``related_service`` should be stored on the event."""
    event = await store.record_event_async(
        event_type="invoke",
        source_service="mahavishnu",
        related_service="akosha",
    )
    assert event["related_service"] == "akosha"


@pytest.mark.asyncio
async def test_record_event_with_explicit_timestamp(
    store: AsyncEcosystemStateStore,
) -> None:
    """An explicit ``timestamp`` should be stored verbatim."""
    ts = "2026-09-06T12:00:00+00:00"
    event = await store.record_event_async(
        event_type="snapshot",
        source_service="dhara",
        timestamp=ts,
    )
    assert event["timestamp"] == ts


@pytest.mark.asyncio
async def test_record_event_prunes_old_events(
    async_connection: AsyncConnection,
) -> None:
    """Recording an event should call ``_prune_events`` and drop stale entries.

    Uses an aggressive 1-day retention so the seeded "old" event gets pruned.
    """
    store = AsyncEcosystemStateStore(
        async_connection, event_retention=EventRetention(retention_days=1)
    )
    await store._ensure_root_async()
    # Seed an old event manually.
    events = await store._events()
    events.append(
        PersistentDict(
            {
                "event_type": "old",
                "source_service": "s",
                "timestamp": (_utcnow() - timedelta(days=2)).isoformat(),
                "payload": {},
                "schema_version": 1,
            }
        )
    )
    await async_connection.commit()

    # Recording a new event triggers the prune helper.
    await store.record_event_async(event_type="new", source_service="s")

    remaining = await store._events()
    kept_types = [e["event_type"] for e in remaining]
    assert kept_types == ["new"]


# ---------------------------------------------------------------------------
# list_events_async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_events_default_limit(
    store: AsyncEcosystemStateStore,
) -> None:
    """Without ``limit``, the most recent 100 events should be returned."""
    for i in range(3):
        await store.record_event_async(event_type=f"e{i}", source_service="s")

    events = await store.list_events_async()
    assert len(events) == 3


@pytest.mark.asyncio
async def test_list_events_with_custom_limit(
    store: AsyncEcosystemStateStore,
) -> None:
    """``limit`` should cap the returned slice to the most recent N entries."""
    for i in range(5):
        await store.record_event_async(event_type=f"e{i}", source_service="s")

    events = await store.list_events_async(limit=2)
    assert len(events) == 2
    # Newest events come last (sliced from the tail).
    assert [e["event_type"] for e in events] == ["e3", "e4"]


@pytest.mark.asyncio
async def test_list_events_limit_none_returns_all(
    store: AsyncEcosystemStateStore,
) -> None:
    """``limit=None`` should return every retained event."""
    for i in range(3):
        await store.record_event_async(event_type=f"e{i}", source_service="s")

    events = await store.list_events_async(limit=None)
    assert len(events) == 3


@pytest.mark.asyncio
async def test_list_events_filter_by_event_type(
    store: AsyncEcosystemStateStore,
) -> None:
    """``event_type`` should narrow the results."""
    await store.record_event_async(event_type="deploy", source_service="s")
    await store.record_event_async(event_type="invoke", source_service="s")
    await store.record_event_async(event_type="deploy", source_service="s")

    deploys = await store.list_events_async(event_type="deploy")
    assert all(e["event_type"] == "deploy" for e in deploys)
    assert len(deploys) == 2


@pytest.mark.asyncio
async def test_list_events_filter_by_source_service(
    store: AsyncEcosystemStateStore,
) -> None:
    """``source_service`` should narrow the results."""
    await store.record_event_async(event_type="x", source_service="alpha")
    await store.record_event_async(event_type="y", source_service="beta")

    alpha = await store.list_events_async(source_service="alpha")
    assert [e["source_service"] for e in alpha] == ["alpha"]


@pytest.mark.asyncio
async def test_list_events_filter_by_related_service(
    store: AsyncEcosystemStateStore,
) -> None:
    """``related_service`` should narrow the results."""
    await store.record_event_async(
        event_type="x", source_service="s", related_service="target-1"
    )
    await store.record_event_async(
        event_type="y", source_service="s", related_service="target-2"
    )

    matches = await store.list_events_async(related_service="target-1")
    assert len(matches) == 1
    assert matches[0]["related_service"] == "target-1"


@pytest.mark.asyncio
async def test_list_events_combined_filters(
    store: AsyncEcosystemStateStore,
) -> None:
    """All filters should be combined (AND semantics)."""
    await store.record_event_async(
        event_type="deploy",
        source_service="alpha",
        related_service="akosha",
    )
    await store.record_event_async(
        event_type="deploy", source_service="beta", related_service="akosha"
    )
    await store.record_event_async(
        event_type="invoke",
        source_service="alpha",
        related_service="akosha",
    )

    matched = await store.list_events_async(
        event_type="deploy", source_service="alpha", related_service="akosha"
    )
    assert len(matched) == 1


@pytest.mark.asyncio
async def test_list_events_drops_old_beyond_retention(
    async_connection: AsyncConnection,
) -> None:
    """Events with timestamps older than the cutoff should be filtered out."""
    store = AsyncEcosystemStateStore(
        async_connection, event_retention=EventRetention(retention_days=7)
    )
    old_ts = (_utcnow() - timedelta(days=30)).isoformat()
    new_ts = _utcnow().isoformat()

    await store.record_event_async(
        event_type="old", source_service="s", timestamp=old_ts
    )
    await store.record_event_async(
        event_type="new", source_service="s", timestamp=new_ts
    )

    events = await store.list_events_async()
    assert [e["event_type"] for e in events] == ["new"]


@pytest.mark.asyncio
async def test_list_events_handles_naive_old_timestamp(
    async_connection: AsyncConnection,
) -> None:
    """Naive (no tzinfo) old timestamps should still be filtered out."""
    store = AsyncEcosystemStateStore(
        async_connection, event_retention=EventRetention(retention_days=7)
    )
    naive_old = (_utcnow() - timedelta(days=30)).replace(tzinfo=None).isoformat()

    await store.record_event_async(
        event_type="naive-old", source_service="s", timestamp=naive_old
    )

    events = await store.list_events_async()
    assert events == []


@pytest.mark.asyncio
async def test_list_events_keeps_event_with_unparseable_timestamp(
    store: AsyncEcosystemStateStore,
) -> None:
    """An event with an unparseable timestamp stays in the list (defensive).

    The cutoff check uses ``event_dt is not None and event_dt < cutoff``,
    so a ``None`` event_dt (from a bad timestamp string) skips the cutoff
    branch entirely and the event is preserved.
    """
    events = await store._events()
    events.append(
        PersistentDict(
            {
                "event_type": "broken",
                "source_service": "s",
                "timestamp": "not-a-date",
                "payload": {},
                "schema_version": 1,
            }
        )
    )
    await store.connection.commit()

    result = await store.list_events_async()
    assert len(result) == 1
    assert result[0]["event_type"] == "broken"


@pytest.mark.asyncio
async def test_list_events_keeps_event_with_non_string_timestamp(
    store: AsyncEcosystemStateStore,
) -> None:
    """An event with ``timestamp=None`` should also stay in the list."""
    events = await store._events()
    events.append(
        PersistentDict(
            {
                "event_type": "broken",
                "source_service": "s",
                "timestamp": None,
                "payload": {},
                "schema_version": 1,
            }
        )
    )
    await store.connection.commit()

    result = await store.list_events_async()
    assert len(result) == 1
    assert result[0]["event_type"] == "broken"


@pytest.mark.asyncio
async def test_list_events_keeps_event_with_missing_timestamp(
    store: AsyncEcosystemStateStore,
) -> None:
    """An event missing the timestamp key entirely should also stay."""
    events = await store._events()
    events.append(
        PersistentDict(
            {
                "event_type": "broken",
                "source_service": "s",
                "payload": {},
                "schema_version": 1,
            }
        )
    )
    await store.connection.commit()

    result = await store.list_events_async()
    assert len(result) == 1
    assert result[0]["event_type"] == "broken"


@pytest.mark.asyncio
async def test_list_events_drops_old_event_with_aware_timestamp(
    async_connection: AsyncConnection,
) -> None:
    """Explicitly cover the ``event_dt < cutoff`` skip path with an aware timestamp.

    A naive timestamp would also exercise the ``tzinfo is None`` replace
    branch on line 215; this test pins the aware-timestamp branch of
    line 215 + the ``continue`` on line 217 together.
    """
    store = AsyncEcosystemStateStore(
        async_connection, event_retention=EventRetention(retention_days=7)
    )
    await store._ensure_root_async()
    old_ts = (_utcnow() - timedelta(days=30)).isoformat()
    new_ts = _utcnow().isoformat()

    await store.record_event_async(
        event_type="stale", source_service="s", timestamp=old_ts
    )
    await store.record_event_async(
        event_type="fresh", source_service="s", timestamp=new_ts
    )

    kept = await store.list_events_async()
    assert [e["event_type"] for e in kept] == ["fresh"]


@pytest.mark.asyncio
async def test_list_events_naive_old_timestamp_skipped(
    async_connection: AsyncConnection,
) -> None:
    """Pins the line 215 tz-replace + line 217 ``continue`` branches together.

    A naive timestamp older than the retention cutoff must:
      * be normalised to UTC (line 215 — ``event_dt.replace(tzinfo=UTC)``)
      * then compared against the cutoff and skipped (line 217 — ``continue``).

    Without this test, coverage reports ``BrPart`` because the production
    code's two-line skip sequence isn't directly observed.

    The naive-old event is inserted directly into the events list (bypassing
    ``record_event_async``) so the inline ``_prune_events`` call at record
    time doesn't drop it before we can observe the list-time behaviour.
    """
    store = AsyncEcosystemStateStore(
        async_connection, event_retention=EventRetention(retention_days=7)
    )
    await store._ensure_root_async()
    events = await store._events()
    naive_old = (_utcnow() - timedelta(days=30)).replace(tzinfo=None).isoformat()
    events.append(
        PersistentDict(
            {
                "event_type": "naive-old",
                "source_service": "s",
                "timestamp": naive_old,
                "payload": {},
                "schema_version": 1,
            }
        )
    )
    await async_connection.commit()

    kept = await store.list_events_async()
    assert kept == []


# ---------------------------------------------------------------------------
# Backward-compatible alias
# ---------------------------------------------------------------------------


def test_ecosystem_state_store_alias_points_to_async_class() -> None:
    """The unprefixed ``EcosystemStateStore`` should be the async class."""
    assert EcosystemStateStore is AsyncEcosystemStateStore


# ---------------------------------------------------------------------------
# AsyncConnection wiring sanity check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_connection_built_from_memory_storage() -> None:
    """``AsyncConnection.new`` should work against ``AsyncMemoryStorage`` directly.

    This is a smoke test for the storage path the rest of the suite
    exercises — it pins the wiring so that if ``AsyncConnection.new``
    drifts, the ecosystem_state tests fail loudly.
    """
    storage = AsyncMemoryStorage()
    conn = await AsyncConnection.new(storage)
    root = await conn.get_root()
    # The default root class is PersistentDict; ensure it's usable.
    root["k"] = "v"
    await conn.commit()
    assert root["k"] == "v"
