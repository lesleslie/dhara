"""Approval log — durable approval history entry (M-INFRA).

Persisted by Mahavishnu's M-APPROVAL-LOG consumer. Records are
append-only; history is exposed via ``list_approval_history``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import msgspec

from dhara.schema._base import SchemaEntry
from dhara.schema._registry import register

SCHEMA_VERSION: str = "1.0.0"
MIGRATIONS: dict[str, callable] = {}


class ApprovalLog(msgspec.Struct, frozen=True):
    """Approval history entry."""

    approval_id: str
    actor: str
    action: Literal["approved", "denied", "requested"]
    at: datetime
    metadata: dict[str, Any] = msgspec.field(default_factory=dict)


STRUCT = ApprovalLog


register(
    "approval_log",
    SchemaEntry(
        name="approval_log",
        version=SCHEMA_VERSION,
        struct=STRUCT,
        migrations=MIGRATIONS,
    ),
)
