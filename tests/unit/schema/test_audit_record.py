# tests/unit/schema/test_audit_record.py
from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from dhara.schema._registry import SCHEMA_REGISTRY, to_dict, validate
from dhara.schema.audit_record import MIGRATIONS, SCHEMA_VERSION, AuditRecord


def test_schema_version_is_1_0_0() -> None:
    assert SCHEMA_VERSION == "1.0.0"


def test_migrations_is_empty_for_v1() -> None:
    assert MIGRATIONS == {}


def test_audit_record_is_registered() -> None:
    assert "audit_record" in SCHEMA_REGISTRY
    entry = SCHEMA_REGISTRY["audit_record"]
    assert entry.name == "audit_record"
    assert entry.version == "1.0.0"


def test_construct_with_required_fields() -> None:
    at = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    rec = AuditRecord(
        audit_id="a-1",
        event_type="lock.acquired",
        actor="user:les",
        at=at,
        subject="lock:foo",
    )
    assert rec.audit_id == "a-1"
    assert rec.metadata == {}


def test_metadata_default_is_empty_dict() -> None:
    """Each AuditRecord gets its own {} — no shared mutable default."""
    rec1 = AuditRecord(
        audit_id="a-1",
        event_type="x",
        actor="a",
        at=datetime(2026, 1, 1, tzinfo=UTC),
        subject="s",
    )
    rec2 = AuditRecord(
        audit_id="a-2",
        event_type="x",
        actor="a",
        at=datetime(2026, 1, 1, tzinfo=UTC),
        subject="s",
    )
    rec1.metadata["key"] = "value"
    assert rec2.metadata == {}


def test_frozen_rejects_mutation() -> None:
    rec = AuditRecord(
        audit_id="a-1",
        event_type="x",
        actor="a",
        at=datetime(2026, 1, 1, tzinfo=UTC),
        subject="s",
    )
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        rec.audit_id = "a-2"  # type: ignore[misc]


def test_validate_returns_struct() -> None:
    payload = {
        "audit_id": "a-1",
        "event_type": "lock.acquired",
        "actor": "user:les",
        "at": "2026-08-05T12:00:00+00:00",
        "subject": "lock:foo",
        "metadata": {"ttl": 60},
    }
    rec = validate("audit_record", payload)
    assert isinstance(rec, AuditRecord)
    assert rec.metadata == {"ttl": 60}


def test_to_dict_roundtrip() -> None:
    at = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    rec = AuditRecord(
        audit_id="a-1",
        event_type="lock.acquired",
        actor="user:les",
        at=at,
        subject="lock:foo",
        metadata={"k": "v"},
    )
    d = to_dict(rec)
    assert d["audit_id"] == "a-1"
    # Round-trip back through validate
    rec2 = validate("audit_record", d)
    assert rec2 == rec
