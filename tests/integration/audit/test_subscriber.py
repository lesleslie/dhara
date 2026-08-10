"""Verify AuditLogSubscriber enqueues validated audit_record on dhara.put."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from dhara.audit.outbox import MemoryOutbox
from dhara.audit.subscriber import AuditLogSubscriber
from dhara.schema.audit_record import AuditRecord


@pytest.fixture
def outbox() -> MemoryOutbox:
    return MemoryOutbox(max_size=100)


@pytest.fixture
def subscriber(outbox: MemoryOutbox) -> AuditLogSubscriber:
    sub = AuditLogSubscriber(outbox=outbox)
    sub.register()
    yield sub
    sub.unregister()


def test_subscriber_enqueues_validated_record(
    subscriber: AuditLogSubscriber, outbox: MemoryOutbox
) -> None:
    payload = {
        "audit_id": "audit-1",
        "event_type": "test-action",
        "actor": "test-actor",
        "at": datetime.now(UTC),
        "subject": "test-target",
        "metadata": {"k": "v"},
    }
    write_event = MagicMock()
    write_event.entity_type = "test_entity"
    write_event.entity_id = "test-id-123"
    write_event.payload = payload
    subscriber.on_put(write_event)

    assert outbox.size == 1
    record = outbox.peek()
    assert isinstance(record, AuditRecord)
    assert record.actor == "test-actor"
    assert record.event_type == "test-action"
    assert record.subject == "test-target"


def test_subscriber_does_not_raise_on_invalid_payload(
    subscriber: AuditLogSubscriber, outbox: MemoryOutbox
) -> None:
    """G6 contract: substrate failures NEVER break the producer."""
    write_event = MagicMock()
    write_event.entity_type = "test_entity"
    write_event.entity_id = "test-id-456"
    write_event.payload = {"actor": 12345}  # actor must be str — validation will fail
    # MUST NOT raise
    subscriber.on_put(write_event)
    assert outbox.size == 0  # invalid record NOT enqueued, but producer is fine
