# tests/unit/schema/test_workflow_outcome.py
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dhara.schema._registry import SCHEMA_REGISTRY, to_dict, validate
from dhara.schema.workflow_outcome import SCHEMA_VERSION, WorkflowOutcome


def test_schema_version_is_1_0_0() -> None:
    assert SCHEMA_VERSION == "1.0.0"


def test_workflow_outcome_is_registered() -> None:
    assert "workflow_outcome" in SCHEMA_REGISTRY


def test_construct_succeeded() -> None:
    started = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    finished = datetime(2026, 8, 5, 10, 5, tzinfo=UTC)
    w = WorkflowOutcome(
        workflow_id="wf-1",
        status="succeeded",
        started_at=started,
        finished_at=finished,
    )
    assert w.workflow_id == "wf-1"
    assert w.status == "succeeded"
    assert w.metadata == {}


def test_status_literal_is_validated() -> None:
    """msgspec.Strict enforces the Literal — invalid status raises on validate."""
    payload = {
        "workflow_id": "wf-1",
        "status": "bogus",  # not in {succeeded, failed, cancelled}
        "started_at": "2026-08-05T10:00:00+00:00",
        "finished_at": "2026-08-05T10:05:00+00:00",
        "metadata": {},
    }
    from dhara.schema._base import SchemaValidationError

    with pytest.raises(SchemaValidationError):
        validate("workflow_outcome", payload)


def test_to_dict_roundtrip() -> None:
    started = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    finished = datetime(2026, 8, 5, 10, 5, tzinfo=UTC)
    w = WorkflowOutcome(
        workflow_id="wf-1",
        status="failed",
        started_at=started,
        finished_at=finished,
        metadata={"error": "boom"},
    )
    d = to_dict(w)
    assert d["status"] == "failed"
    w2 = validate("workflow_outcome", d)
    assert w2 == w
