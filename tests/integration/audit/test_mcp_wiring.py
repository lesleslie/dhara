"""Verify DharaMCPServer registers the audit subscriber and query tool."""

from __future__ import annotations

import duckdb

from dhara.audit.outbox import MemoryOutbox
from dhara.audit.subscriber import AuditLogSubscriber
from dhara.mcp.server_core import DharaMCPServer


def test_dhara_mcp_server_registers_audit_subscriber_and_query_tool() -> None:
    conn = duckdb.connect(":memory:")
    outbox = MemoryOutbox()
    server = DharaMCPServer(storage_conn=conn, audit_outbox=outbox)
    server._register_tools()
    # The subscriber should be the registered singleton after server boot
    assert AuditLogSubscriber.get_instance() is not None
    # The query tool should be registered as an MCP tool
    assert "audit_record_query" in server._registered_tools
