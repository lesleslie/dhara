"""OutboxFlusher — drains MemoryOutbox into the audit_log table."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from oneiric.core.logging import get_logger

if TYPE_CHECKING:
    import duckdb

    from dhara.audit.outbox import MemoryOutbox

logger = get_logger(__name__)


async def periodic_flush_loop(
    flusher: OutboxFlusher,
    interval_seconds: float = 0.1,
) -> None:
    """Continuously drain the outbox into the audit_log table.

    The loop calls :meth:`OutboxFlusher.flush_once` and sleeps for
    ``interval_seconds`` between ticks. Per the G6 contract, the loop
    never raises: any exception escaping :meth:`flush_once` is logged via
    :func:`logger.exception` and the loop continues, so a transient DB
    failure cannot break the audit substrate or crash the host server.

    Args:
        flusher: OutboxFlusher wired to a MemoryOutbox and DuckDB
            connection.
        interval_seconds: Seconds to sleep between flush ticks. Defaults
            to 0.1s for snappy test feedback and low production latency.
    """
    while True:
        try:
            await flusher.flush_once()
        except Exception as exc:  # G6 contract: never raise
            logger.exception(
                "periodic_flush_loop_unhandled_error",
                extra={"exception_type": type(exc).__name__},
            )
        await asyncio.sleep(interval_seconds)


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
                        "metadata": record.metadata.copy(),
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
