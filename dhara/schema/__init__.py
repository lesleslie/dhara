"""D-OBJ-SCHEMA — typed object schemas for cross-system durable entities.

This module exposes the canonical schemas for the five cross-system
durable entities defined in the 2026-08-03 portfolio spec:

- :class:`AuditRecord` (D-AUDIT consumer)
- :class:`WorkflowOutcome` (M-INFRA)
- :class:`ApprovalLog` (M-INFRA)
- :class:`ChannelSessionState` (S-MEM)
- :class:`WebhookIngress` (M-INFRA)

Plus the central registry (:func:`SCHEMA_REGISTRY`, :func:`validate`,
:func:`from_dict`, :func:`to_dict`) for runtime validation.
"""

from __future__ import annotations

from dhara.schema._base import SchemaEntry, SchemaValidationError
from dhara.schema._registry import (
    SCHEMA_REGISTRY,
    from_dict,
    register,
    to_dict,
    validate,
)

# Re-export entity Struct classes and STRUCT aliases for ergonomic imports.
from dhara.schema.approval_log import STRUCT as approval_log
from dhara.schema.approval_log import ApprovalLog
from dhara.schema.audit_record import STRUCT as audit_record
from dhara.schema.audit_record import AuditRecord
from dhara.schema.channel_session_state import (
    STRUCT as channel_session_state,
)
from dhara.schema.channel_session_state import (
    ChannelSessionState,
)
from dhara.schema.webhook_ingress import STRUCT as webhook_ingress
from dhara.schema.webhook_ingress import WebhookIngress
from dhara.schema.workflow_outcome import STRUCT as workflow_outcome
from dhara.schema.workflow_outcome import WorkflowOutcome

__all__ = [
    "SCHEMA_REGISTRY",
    "ApprovalLog",
    "AuditRecord",
    "ChannelSessionState",
    "SchemaEntry",
    "SchemaValidationError",
    "WebhookIngress",
    "WorkflowOutcome",
    "approval_log",
    "audit_record",
    "channel_session_state",
    "from_dict",
    "register",
    "to_dict",
    "validate",
    "webhook_ingress",
    "workflow_outcome",
]
