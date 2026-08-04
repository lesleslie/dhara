"""Verify migration 0003 creates substrate_locks table with correct schema."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

_MIGRATION_0003 = (
    Path(__file__).parents[3] / "dhara" / "migrations" / "sql" / "0003_locks.sql"
).read_text()


@pytest.fixture
def conn() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    yield c
    c.close()


def test_0003_creates_substrate_locks_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(_MIGRATION_0003)
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name = 'substrate_locks'"
    ).fetchall()
    assert rows, "substrate_locks table not created"


def test_0003_columns_present(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(_MIGRATION_0003)
    cols = {
        row[0]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'substrate_locks'"
        ).fetchall()
    }
    assert {"lock_key", "owner_token", "acquired_at", "expires_at",
            "is_permanent", "original_ttl_seconds", "metadata"}.issubset(cols)


def test_0003_lock_key_is_primary_key(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(_MIGRATION_0003)
    pk = conn.execute(
        "SELECT column_name FROM information_schema.table_constraints "
        "WHERE table_name = 'substrate_locks' AND constraint_type = 'PRIMARY KEY'"
    ).fetchall()
    assert ("lock_key",) in pk


def test_0003_is_idempotent(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(_MIGRATION_0003)
    conn.execute(_MIGRATION_0003)  # must not raise
