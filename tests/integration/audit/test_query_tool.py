"""Verify AuditLogQueryTool returns validated audit_record structs."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from dhara.audit.query_tool import AuditLogQueryTool
from dhara.schema.audit_record import AuditRecord

_MIGRATION_0004 = (
    Path(__file__).parents[3] / "dhara" / "migrations" / "sql" / "0004_audit_log.sql"
).read_text()


@pytest.fixture
def conn() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    c.execute(_MIGRATION_0004)
    c.execute(
        "INSERT INTO audit_log (entity_type, entity_id, payload) VALUES (?, ?, ?)",
        (
            "workflow_outcome",
            "wf-1",
            (
                '{"audit_id": "audit-1", "event_type": "run", "actor": "alice", '
                '"at": "2026-08-10T00:00:00+00:00", "subject": "wf-1", "metadata": {}}'
            ),
        ),
    )
    yield c
    c.close()


def test_query_filters_by_entity_type(conn: duckdb.DuckDBPyConnection) -> None:
    tool = AuditLogQueryTool(conn)
    results = tool.query(entity_type="workflow_outcome")
    assert len(results) == 1
    assert isinstance(results[0], AuditRecord)
    assert results[0].actor == "alice"
    assert results[0].audit_id == "audit-1"
    assert results[0].event_type == "run"


def test_query_respects_limit(conn: duckdb.DuckDBPyConnection) -> None:
    tool = AuditLogQueryTool(conn)
    results = tool.query(entity_type="workflow_outcome", limit=0)
    assert results == []


def test_query_skips_invalid_payload(conn: duckdb.DuckDBPyConnection) -> None:
    """Schema-drift tolerance: rows whose payload fails validation are dropped."""
    conn.execute(
        "INSERT INTO audit_log (entity_type, entity_id, payload) VALUES (?, ?, ?)",
        (
            "workflow_outcome",
            "wf-bad",
            '{"actor": 12345}',  # actor must be str — validation will fail
        ),
    )
    tool = AuditLogQueryTool(conn)
    results = tool.query(entity_type="workflow_outcome", limit=100)
    # Only the well-formed row is returned; the malformed one is skipped.
    assert len(results) == 1
    assert results[0].audit_id == "audit-1"
