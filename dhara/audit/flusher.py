"""OutboxFlusher — drains MemoryOutbox into the audit_log table."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from oneiric.core.logging import get_logger

if TYPE_CHECKING:
    import duckdb

    from dhara.audit.outbox import MemoryOutbox

logger = get_logger(__name__)


class OutboxFlusher:
    """Drains MemoryOutbox into audit_log; async per audit-record emission.

    G6 contract: never raises. All DB failures are absorbed and logged so the
    substrate cannot break the caller. Records drained from the outbox but
    not successfully inserted are lost on this flush; durable replay is a
    Task 5/6 concern.
    """

    def __init__(self, outbox: MemoryOutbox, conn: duckdb.DuckDBPyConnection) -> None:
        self._outbox = outbox
        self._conn = conn

    async def flush_once(self) -> int:
        """Atomically drain outbox and insert rows; returns count flushed.

        G6 contract: never raises. Errors logged via logger.exception with
        structured fields (count_attempted, exception_type); returns 0 on
        failure so the caller observes a no-op rather than a crash.
        """
        records = self._outbox.drain()
        if not records:
            return 0
        rows = [
            (
                self._entity_type_for(record),
                self._entity_id_for(record),
                json.dumps(
                    {
                        "actor": record.actor,
                        "event_type": record.event_type,
                        "subject": record.subject,
                        "metadata": dict(record.metadata),
                    }
                ),
            )
            for record in records
        ]
        try:
            self._conn.executemany(
                "INSERT INTO audit_log (entity_type, entity_id, payload) VALUES (?, ?, ?)",
                rows,
            )
        except Exception as exc:
            logger.exception(
                "audit flush failed",
                extra={
                    "count_attempted": len(rows),
                    "exception_type": type(exc).__name__,
                },
            )
            return 0
        return len(rows)

    @staticmethod
    def _entity_type_for(record: object) -> str:
        # Placeholder; entity_type is set by the WriteEvent, not the
        # audit_record. We use 'unknown' as a placeholder until the
        # integration glue (Task 5) wires event metadata into flusher.
        return getattr(record, "entity_type", "unknown") or "unknown"

    @staticmethod
    def _entity_id_for(record: object) -> str:
        return getattr(record, "entity_id", "unknown") or "unknown"
