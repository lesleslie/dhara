"""Verify DharaMCPServer wires OutboxFlusher into a periodic background loop.

Without the periodic loop, the MemoryOutbox fills up unbounded (modulo the
bounded-FIFO drop-oldest behavior) and ``audit_log`` never receives rows.
This test asserts the production caller wires ``periodic_flush_loop`` into
the server startup path so audit reads return what producers enqueue.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from dhara.audit.outbox import MemoryOutbox
from dhara.audit.subscriber import AuditLogSubscriber, WriteEvent
from dhara.mcp.server_core import DharaMCPServer

_MIGRATION_0004 = (
    Path(__file__).parents[3] / "dhara" / "migrations" / "sql" / "0004_audit_log.sql"
).read_text()


@pytest.fixture
def conn() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    c.execute(_MIGRATION_0004)
    yield c
    c.close()


def _make_event(audit_id: str) -> WriteEvent:
    return WriteEvent(
        entity_type="foo",
        entity_id=audit_id,
        payload={
            "audit_id": audit_id,
            "event_type": "create",
            "actor": "alice",
            "at": datetime.now(UTC),
            "subject": "thing",
            "metadata": {"action": "create", "target": "thing"},
        },
    )


@pytest.mark.asyncio
async def test_periodic_flush_loop_drains_outbox_into_audit_log(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """G6 contract: D-AUDIT substrate must drain outbox into audit_log.

    Without periodic_flush_loop scheduled at server startup, ``audit_log``
    stays empty. This test fails until the loop is wired in
    ``_register_tools`` and runs as a background task on the server.
    """
    outbox = MemoryOutbox()
    server = DharaMCPServer(storage_conn=conn, audit_outbox=outbox)
    server._register_tools()

    subscriber = AuditLogSubscriber.get_instance()
    assert subscriber is not None, "subscriber must be registered after _register_tools"

    for i in range(3):
        subscriber.on_put(_make_event(f"audit-{i}"))

    # Give the periodic flush loop enough cycles to drain. The default
    # interval is 0.1s; 0.5s leaves headroom for several ticks even on
    # slow CI machines.
    await asyncio.sleep(0.5)

    rows = conn.execute(
        "SELECT entity_type, entity_id FROM audit_log ORDER BY id"
    ).fetchall()
    assert len(rows) == 3, (
        f"expected 3 rows drained from outbox into audit_log, got {len(rows)}: {rows}"
    )
    assert {row[1] for row in rows} == {"audit-0", "audit-1", "audit-2"}


@pytest.mark.asyncio
async def test_periodic_flush_loop_task_is_stored_on_server(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """The background task must be retained on the server for shutdown.

    ``_register_tools`` schedules ``periodic_flush_loop`` via
    ``asyncio.create_task``; the task handle must be stored on the server
    instance so a future shutdown hook can cancel it cleanly.
    """
    outbox = MemoryOutbox()
    server = DharaMCPServer(storage_conn=conn, audit_outbox=outbox)
    server._register_tools()

    task = getattr(server, "_audit_flush_task", None)
    assert task is not None, (
        "expected server._audit_flush_task to be set after _register_tools; "
        "scheduled periodic flush loop must be retained for cancellation"
    )
    # Cancel so the test process exits cleanly regardless of loop state.
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
