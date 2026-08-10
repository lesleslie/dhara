# tests/unit/schema/test_approval_log.py
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dhara.schema._base import SchemaValidationError
from dhara.schema._registry import SCHEMA_REGISTRY, to_dict, validate
from dhara.schema.approval_log import SCHEMA_VERSION, ApprovalLog


def test_schema_version_is_1_0_0() -> None:
    assert SCHEMA_VERSION == "1.0.0"


def test_approval_log_is_registered() -> None:
    assert "approval_log" in SCHEMA_REGISTRY


def test_construct_approved() -> None:
    at = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    log = ApprovalLog(
        approval_id="apr-1",
        actor="user:les",
        action="approved",
        at=at,
    )
    assert log.action == "approved"
    assert log.metadata == {}


def test_invalid_action_raises() -> None:
    payload = {
        "approval_id": "apr-1",
        "actor": "user:les",
        "action": "vetoed",  # not in {approved, denied, requested}
        "at": "2026-08-05T12:00:00+00:00",
        "metadata": {},
    }
    with pytest.raises(SchemaValidationError):
        validate("approval_log", payload)


def test_to_dict_roundtrip() -> None:
    at = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    log = ApprovalLog(
        approval_id="apr-1",
        actor="user:les",
        action="denied",
        at=at,
        metadata={"reason": "out of scope"},
    )
    d = to_dict(log)
    assert d["action"] == "denied"
    log2 = validate("approval_log", d)
    assert log2 == log
