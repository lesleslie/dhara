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
        items = self._outbox.drain()
        if not items:
            return 0
        rows = [
            (
                entity_type,
                entity_id,
                json.dumps(
                    {
                        "audit_id": record.audit_id,
                        "event_type": record.event_type,
                        "actor": record.actor,
                        "at": record.at.isoformat(),
                        "subject": record.subject,
                        "metadata": dict(record.metadata),
                    }
                ),
            )
            for entity_type, entity_id, record in items
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
