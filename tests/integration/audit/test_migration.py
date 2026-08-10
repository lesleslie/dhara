"""Verify migration 0004 creates audit_log table with correct schema."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

_MIGRATION_0004 = (
    Path(__file__).parents[3] / "dhara" / "migrations" / "sql" / "0004_audit_log.sql"
).read_text()


@pytest.fixture
def conn() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    yield c
    c.close()


def test_0004_creates_audit_log_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(_MIGRATION_0004)
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name = 'audit_log'"
    ).fetchall()
    assert rows == [("audit_log",)]


def test_0004_audit_log_columns(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(_MIGRATION_0004)
    rows = conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = 'audit_log' ORDER BY ordinal_position"
    ).fetchall()
    # NOTE: DuckDB normalizes TEXT → VARCHAR in information_schema.
    # The schema uses TEXT in the SQL; both are SQL-standard aliases.
    assert rows == [
        ("id", "BIGINT"),
        ("entity_type", "VARCHAR"),
        ("entity_id", "VARCHAR"),
        ("recorded_at", "TIMESTAMP WITH TIME ZONE"),
        ("payload", "VARCHAR"),
    ]


def test_0004_creates_entity_type_index(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(_MIGRATION_0004)
    rows = conn.execute(
        "SELECT indexname FROM pg_indexes WHERE tablename = 'audit_log'"
    ).fetchall()
    assert any("entity_type_recorded_at" in r[0] for r in rows)
