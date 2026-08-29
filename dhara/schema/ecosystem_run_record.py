"""Ecosystem run record — Phase 1 substrate for ``session-buddy://runs/{workflow_id}.json``.

Persisted by Session-Buddy's ``ecosystem_run_history`` tool. Each record
captures one component's contribution to a given workflow execution,
plus the synthesis block produced by the aggregator.

D-RUN-HISTORY (Phase 1)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

import msgspec

from dhara.schema._base import SchemaEntry
from dhara.schema._registry import register

SCHEMA_VERSION: str = "1.0.0"
MIGRATIONS: dict[str, Callable[..., Any]] = {}


RunStatus = Literal[
    "unknown",
    "pending",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "error",
]


class ComponentRunEntry(msgspec.Struct, frozen=True):
    """One component's run record for a workflow."""

    repo: str
    workflow_id: str
    status: RunStatus
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    source: str = "phase1_stub"
    error: str | None = None
    steps: list[dict[str, Any]] = msgspec.field(default_factory=list)
    metadata: dict[str, Any] = msgspec.field(default_factory=dict)


class EcosystemRunRecord(msgspec.Struct, frozen=True):
    """Aggregated ecosystem run record persisted at ``session-buddy://runs/{workflow_id}.json``.

    The ``components`` list carries one :class:`ComponentRunEntry` per
    contributing Bodai component. The ``summary`` block mirrors the
    shape returned by ``Session-Buddy.aggregate_run_history`` so the
    consumer side does not need a second translation pass.
    """

    workflow_id: str
    components: list[ComponentRunEntry] = msgspec.field(default_factory=list)
    summary: dict[str, Any] = msgspec.field(default_factory=dict)
    mode: str = "phase1_stub"


STRUCT = EcosystemRunRecord


register(
    "ecosystem_run_record",
    SchemaEntry(
        name="ecosystem_run_record",
        version=SCHEMA_VERSION,
        struct=STRUCT,
        migrations=MIGRATIONS,
    ),
)
