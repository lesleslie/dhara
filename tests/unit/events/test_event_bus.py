from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from dhara.events.bus import EventBus
from dhara.events.events import (
    ContextVersionPublished,
    ProgressSnapshotRecorded,
    SettingsVersionActivated,
)


class TrackingSubscriber:
    """Test subscriber that records every event it receives."""

    def __init__(self, name: str = "tracker") -> None:
        self.name = name
        self.received: list[BaseModel] = []

    async def handle(self, event: BaseModel) -> None:
        self.received.append(event)


class FailingSubscriber:
    """Test subscriber that always raises."""

    def __init__(self) -> None:
        self.attempts = 0

    async def handle(self, event: BaseModel) -> None:
        self.attempts += 1
        raise RuntimeError("subscriber failed on purpose")


class SlowSubscriber:
    """Test subscriber that sleeps so we can observe concurrency."""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.received: list[BaseModel] = []

    async def handle(self, event: BaseModel) -> None:
        await asyncio.sleep(self.delay)
        self.received.append(event)


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.mark.unit
async def test_publish_invokes_subscribed_handler(
    bus: EventBus,
) -> None:
    """A single subscriber receives the published event."""
    tracker = TrackingSubscriber()
    bus.subscribe(SettingsVersionActivated, tracker)

    event = SettingsVersionActivated(
        version_id="v1",
        tenant_id="t1",
        activated_by="alice",
    )
    await bus.publish(event)

    assert len(tracker.received) == 1
    assert tracker.received[0] == event


@pytest.mark.unit
async def test_publish_fans_out_to_multiple_subscribers(
    bus: EventBus,
) -> None:
    """Multiple subscribers all receive the same event."""
    a = TrackingSubscriber("a")
    b = TrackingSubscriber("b")
    c = TrackingSubscriber("c")

    bus.subscribe(SettingsVersionActivated, a)
    bus.subscribe(SettingsVersionActivated, b)
    bus.subscribe(SettingsVersionActivated, c)

    event = SettingsVersionActivated(
        version_id="v2",
        tenant_id="t1",
        activated_by="bob",
    )
    await bus.publish(event)

    for sub in (a, b, c):
        assert sub.received == [event]


@pytest.mark.unit
async def test_publish_routes_by_event_type(
    bus: EventBus,
) -> None:
    """A subscriber for one event type does NOT receive a different type."""
    settings_sub = TrackingSubscriber("settings")
    context_sub = TrackingSubscriber("context")
    progress_sub = TrackingSubscriber("progress")

    bus.subscribe(SettingsVersionActivated, settings_sub)
    bus.subscribe(ContextVersionPublished, context_sub)
    bus.subscribe(ProgressSnapshotRecorded, progress_sub)

    await bus.publish(
        SettingsVersionActivated(
            version_id="v3", tenant_id="t1", activated_by="carol"
        )
    )

    assert len(settings_sub.received) == 1
    assert context_sub.received == []
    assert progress_sub.received == []


@pytest.mark.unit
async def test_publish_with_no_subscribers_is_noop(bus: EventBus) -> None:
    """Publishing with no subscribers completes without error."""
    await bus.publish(
        SettingsVersionActivated(
            version_id="v4", tenant_id="t1", activated_by="dan"
        )
    )


@pytest.mark.unit
async def test_subscriber_failure_does_not_block_others(
    bus: EventBus,
) -> None:
    """If one subscriber raises, the others still receive the event."""
    ok_a = TrackingSubscriber("ok_a")
    bad = FailingSubscriber()
    ok_b = TrackingSubscriber("ok_b")

    bus.subscribe(SettingsVersionActivated, ok_a)
    bus.subscribe(SettingsVersionActivated, bad)
    bus.subscribe(SettingsVersionActivated, ok_b)

    event = SettingsVersionActivated(
        version_id="v5", tenant_id="t1", activated_by="erin"
    )

    # The bad subscriber's failure must be isolated — not propagated.
    await bus.publish(event)

    assert ok_a.received == [event]
    assert ok_b.received == [event]
    assert bad.attempts == 1


@pytest.mark.unit
async def test_publish_dispatches_to_subscribers_concurrently(
    bus: EventBus,
) -> None:
    """Subscribers run concurrently, not serially."""
    # Two slow subscribers, each sleeping 100 ms.
    # Serial would take ~200 ms; concurrent should be ~100 ms.
    s1 = SlowSubscriber(delay=0.1)
    s2 = SlowSubscriber(delay=0.1)
    bus.subscribe(SettingsVersionActivated, s1)
    bus.subscribe(SettingsVersionActivated, s2)

    event = SettingsVersionActivated(
        version_id="v6", tenant_id="t1", activated_by="frank"
    )

    start = asyncio.get_event_loop().time()
    await bus.publish(event)
    elapsed = asyncio.get_event_loop().time() - start

    # Allow generous slack for scheduling on CI.
    assert elapsed < 0.18, f"expected concurrent dispatch, took {elapsed:.3f}s"
    assert s1.received == [event]
    assert s2.received == [event]


@pytest.mark.unit
async def test_unsubscribe_stops_delivery(bus: EventBus) -> None:
    """After unsubscribe, the subscriber no longer receives events."""
    tracker = TrackingSubscriber()
    bus.subscribe(SettingsVersionActivated, tracker)

    event = SettingsVersionActivated(
        version_id="v7", tenant_id="t1", activated_by="greta"
    )
    await bus.publish(event)
    assert tracker.received == [event]

    bus.unsubscribe(SettingsVersionActivated, tracker)
    await bus.publish(event)
    # Still exactly one — the second publish didn't reach the subscriber.
    assert tracker.received == [event]


@pytest.mark.unit
async def test_event_payload_validation() -> None:
    """Event payloads enforce their typed shape (rejects bad data)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SettingsVersionActivated(
            version_id="v8",
            tenant_id="t1",
            activated_by="",  # empty is invalid
        )


@pytest.mark.unit
async def test_audit_log_subscriber_writes_row(tmp_path: Any) -> None:
    """The bundled AuditLogSubscriber persists every event as an audit row."""
    import duckdb

    from dhara.events.subscribers.audit_log_subscriber import AuditLogSubscriber

    db_path = tmp_path / "audit.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        # Create the audit table the subscriber writes to.
        conn.execute(
            """
            CREATE TABLE dhara_audit_log (
                id INTEGER PRIMARY KEY,
                event_type TEXT NOT NULL,
                event_id TEXT NOT NULL,
                occurred_at TIMESTAMP NOT NULL,
                tenant_id TEXT,
                payload TEXT NOT NULL
            )
            """
        )

        sub = AuditLogSubscriber(conn)
        bus = EventBus()
        bus.subscribe(SettingsVersionActivated, sub)
        bus.subscribe(ContextVersionPublished, sub)
        bus.subscribe(ProgressSnapshotRecorded, sub)

        await bus.publish(
            SettingsVersionActivated(
                version_id="v9",
                tenant_id="t1",
                activated_by="henry",
            )
        )
        await bus.publish(
            ContextVersionPublished(
                version_id="ctx-1",
                tenant_id="t1",
                published_by="henry",
                context={"region": "us-east-1"},
            )
        )
        await bus.publish(
            ProgressSnapshotRecorded(
                workflow_id="wf-1",
                tenant_id="t1",
                step="done",
                progress_percent=1.0,
            )
        )

        rows = conn.execute(
            "SELECT event_type, tenant_id FROM dhara_audit_log ORDER BY id"
        ).fetchall()
        assert [r[0] for r in rows] == [
            "SettingsVersionActivated",
            "ContextVersionPublished",
            "ProgressSnapshotRecorded",
        ]
        assert all(r[1] == "t1" for r in rows)
    finally:
        conn.close()
