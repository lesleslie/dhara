"""Cross-system: dhara.put emits audit_record; query tool returns it.

End-to-end integration test exercising the assembled audit substrate
(Tasks 1-5): ``DharaMCPServer`` → ``AuditLogSubscriber`` →
``MemoryOutbox`` → ``OutboxFlusher`` → ``audit_log`` table →
``AuditLogQueryTool``.

The brief shipped non-existent ``action``/``target`` fields; this test
uses the real ``AuditRecord`` schema (``audit_id``, ``event_type``,
``actor``, ``at``, ``subject``, ``metadata``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pytest

from dhara.audit.flusher import OutboxFlusher
from dhara.audit.outbox import MemoryOutbox
from dhara.audit.subscriber import AuditLogSubscriber, WriteEvent
from dhara.mcp.server_core import DharaMCPServer

_MIGRATION_0004 = (
    Path(__file__).parents[3] / "dhara" / "migrations" / "sql" / "0004_audit_log.sql"
).read_text()


@pytest.mark.asyncio
async def test_dhara_put_emits_queryable_audit_record() -> None:
    conn = duckdb.connect(":memory:")
    conn.execute(_MIGRATION_0004)
    outbox = MemoryOutbox()
    server = DharaMCPServer(storage_conn=conn, audit_outbox=outbox)
    server._register_tools()  # mirrors D-LOCK's register_lock_routes pattern

    subscriber = AuditLogSubscriber.get_instance()
    assert subscriber is not None
    subscriber.on_put(
        WriteEvent(
            entity_type="test_entity",
            entity_id="abc-123",
            payload={
                "audit_id": "audit-001",
                "event_type": "create",
                "actor": "system",
                "at": datetime(2026, 8, 10, 0, 0, 0, tzinfo=timezone.utc),
                "subject": "abc-123",
                "metadata": {"key": "value"},
            },
        )
    )

    flusher = OutboxFlusher(outbox=outbox, conn=conn)
    flushed = await flusher.flush_once()
    assert flushed == 1

    query_tool = server._registered_tools["audit_record_query"]  # type: ignore[attr-defined]
    results = query_tool(entity_type="test_entity")
    assert len(results) == 1
    assert results[0].actor == "system"
    assert results[0].event_type == "create"
    assert results[0].audit_id == "audit-001"
    assert results[0].subject == "abc-123"
