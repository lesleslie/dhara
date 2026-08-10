"""Verify OutboxFlusher drains the outbox and inserts audit_log rows."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import duckdb
import pytest

from dhara.audit.flusher import OutboxFlusher
from dhara.audit.outbox import MemoryOutbox
from dhara.audit.subscriber import AuditLogSubscriber, WriteEvent

_MIGRATION_0004 = (
    Path(__file__).parents[3] / "dhara" / "migrations" / "sql" / "0004_audit_log.sql"
).read_text()


@pytest.fixture
def conn() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    c.execute(_MIGRATION_0004)
    yield c
    c.close()


@pytest.mark.asyncio
async def test_flusher_inserts_drained_records(conn: duckdb.DuckDBPyConnection) -> None:
    outbox = MemoryOutbox()
    subscriber = AuditLogSubscriber(outbox=outbox)
    subscriber.on_put(
        WriteEvent(
            entity_type="foo",
            entity_id="bar",
            payload={
                "audit_id": "audit-1",
                "event_type": "create",
                "actor": "alice",
                "at": datetime.now(UTC),
                "subject": "thing",
                "metadata": {"action": "create", "target": "thing"},
            },
        )
    )
    flusher = OutboxFlusher(outbox=outbox, conn=conn)
    flushed = await flusher.flush_once()
    assert flushed == 1
    rows = conn.execute(
        "SELECT entity_type, entity_id, payload FROM audit_log"
    ).fetchall()
    assert len(rows) == 1
    # NOTE: entity_type/entity_id wiring is refined in Task 5; the Task 3
    # placeholder returns "unknown" for both until the integration glue
    # is in place.
    assert rows[0][0] == "unknown"
    assert rows[0][1] == "unknown"


@pytest.mark.asyncio
async def test_flush_once_swallows_db_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """G6 contract: DB errors during executemany are absorbed and logged.

    Simulates a duckdb.Error from executemany and asserts:
    - flush_once returns 0 (does not propagate)
    - warning/error is logged with structured context
    """
    outbox = MemoryOutbox()
    subscriber = AuditLogSubscriber(outbox=outbox)
    subscriber.on_put(
        WriteEvent(
            entity_type="foo",
            entity_id="bar",
            payload={
                "audit_id": "audit-1",
                "event_type": "create",
                "actor": "alice",
                "at": datetime.now(UTC),
                "subject": "thing",
                "metadata": {},
            },
        )
    )

    mock_conn = MagicMock()
    mock_conn.executemany.side_effect = duckdb.Error("simulated DB failure")

    flusher = OutboxFlusher(outbox=outbox, conn=mock_conn)

    with caplog.at_level(logging.ERROR, logger="dhara.audit.flusher"):
        flushed = await flusher.flush_once()

    assert flushed == 0
    assert mock_conn.executemany.call_count == 1
    failure_records = [
        record
        for record in caplog.records
        if "audit flush failed" in record.getMessage()
    ]
    assert failure_records, (
        "expected a log record containing 'audit flush failed' "
        f"but got: {[r.getMessage() for r in caplog.records]}"
    )
