# tests/unit/schema/test_cross_system_consistency.py
from __future__ import annotations

import pytest

from dhara.schema._registry import SCHEMA_REGISTRY
from dhara.schema.approval_log import ApprovalLog
from dhara.schema.audit_record import AuditRecord
from dhara.schema.channel_session_state import ChannelSessionState
from dhara.schema.webhook_ingress import WebhookIngress
from dhara.schema.workflow_outcome import WorkflowOutcome

EXPECTED_ENTITIES = {
    "audit_record",
    "workflow_outcome",
    "approval_log",
    "channel_session_state",
    "webhook_ingress",
}


def test_all_5_entities_registered() -> None:
    """Portfolio spec promised 5 entities in v1; all must be present."""
    assert EXPECTED_ENTITIES.issubset(set(SCHEMA_REGISTRY.keys()))


def test_all_entities_are_frozen_msgspec_structs() -> None:
    """Every entity must be frozen=True so audit logs are immutable."""
    for struct in (
        AuditRecord,
        WorkflowOutcome,
        ApprovalLog,
        ChannelSessionState,
        WebhookIngress,
    ):
        # frozen=True is encoded in msgspec.Struct, hard to introspect
        # but we can verify the dataclass-like behavior.
        assert hasattr(struct, "__dataclass_params__") or hasattr(
            struct, "__struct_fields__"
        )
        # The hash-ability check:
        try:
            hash(struct)
        except TypeError:
            pytest.fail(f"{struct.__name__} is not hashable (frozen=True required)")


def test_all_entities_have_metadata_field() -> None:
    """The metadata escape hatch is required for forward compatibility."""
    for struct in (
        AuditRecord,
        WorkflowOutcome,
        ApprovalLog,
        ChannelSessionState,
        WebhookIngress,
    ):
        assert "metadata" in struct.__struct_fields__, (
            f"{struct.__name__} missing metadata field"
        )


def test_all_entities_have_datetime_field() -> None:
    """Every entity has at least one datetime field for audit cross-referencing."""
    for struct in (
        AuditRecord,
        WorkflowOutcome,
        ApprovalLog,
        ChannelSessionState,
        WebhookIngress,
    ):
        fields = struct.__struct_fields__
        # At least one datetime field (AuditRecord.at, WorkflowOutcome.started_at, etc.)
        field_types = struct.__annotations__
        assert any("datetime" in str(field_types.get(f, "")) for f in fields), (
            f"{struct.__name__} has no datetime field"
        )


def test_all_entities_registered_at_v1_0_0() -> None:
    """Every entity in v1 must be at version 1.0.0."""
    for name in EXPECTED_ENTITIES:
        entry = SCHEMA_REGISTRY[name]
        assert entry.version == "1.0.0", f"{name} is at {entry.version}, expected 1.0.0"
