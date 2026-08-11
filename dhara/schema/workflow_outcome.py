"""Workflow outcome — durable result of a workflow execution (M-INFRA).

Persisted by Mahavishnu's M-WORKFLOW-OUTCOME consumer to
``workflow-results/{workflow_id}/`` in Dhara.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

import msgspec

from dhara.schema._base import SchemaEntry
from dhara.schema._registry import register

SCHEMA_VERSION: str = "1.0.0"
MIGRATIONS: dict[str, Callable[..., Any]] = {}


class WorkflowOutcome(msgspec.Struct, frozen=True):
    """Structured ``WorkflowOutcome`` model + Dhara persistence."""

    workflow_id: str
    status: Literal["succeeded", "failed", "cancelled"]
    started_at: datetime
    finished_at: datetime
    metadata: dict[str, Any] = msgspec.field(default_factory=dict)


STRUCT = WorkflowOutcome


register(
    "workflow_outcome",
    SchemaEntry(
        name="workflow_outcome",
        version=SCHEMA_VERSION,
        struct=STRUCT,
        migrations=MIGRATIONS,
    ),
)
