"""Audit record — substrate audit log entry.

The canonical entity for D-AUDIT. Every durable primitive emits
``AuditRecord`` instances via the registry; consumers (D-AUDIT,
A-EVENT-LOG, precommit CLI on ``permanent=True``) write these to
their own storage.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import msgspec

from dhara.schema._base import SchemaEntry
from dhara.schema._registry import register

SCHEMA_VERSION: str = "1.0.0"
MIGRATIONS: dict[str, callable] = {}


class AuditRecord(msgspec.Struct, frozen=True):
    """Substrate audit log entry. Written by every durable primitive."""

    audit_id: str
    event_type: str
    actor: str
    at: datetime
    subject: str
    metadata: dict[str, Any] = msgspec.field(default_factory=dict)


STRUCT = AuditRecord


register(
    "audit_record",
    SchemaEntry(
        name="audit_record",
        version=SCHEMA_VERSION,
        struct=STRUCT,
        migrations=MIGRATIONS,
    ),
)
