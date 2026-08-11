"""Smoke test: confirm `substrate_locks` table is present in pg_schema.sql.

This test runs without asyncpg or a live Postgres instance. It guards
against regressions when the D-LOCK v1.1 Postgres translation is renamed
or accidentally removed.

Brief reference: D-LOCK v1.1 Task 1, optional smoke test.
"""
from __future__ import annotations

from pathlib import Path

import pytest

PG_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "dhara" / "storage" / "pg_schema.sql"


@pytest.fixture(scope="module")
def pg_schema_text() -> str:
    assert PG_SCHEMA_PATH.is_file(), f"pg_schema.sql missing at {PG_SCHEMA_PATH}"
    return PG_SCHEMA_PATH.read_text(encoding="utf-8")


def test_pg_schema_creates_substrate_locks(pg_schema_text: str) -> None:
    """The substrate_locks CREATE TABLE statement must be present."""
    assert "CREATE TABLE IF NOT EXISTS substrate_locks" in pg_schema_text


def test_pg_schema_substrate_locks_has_lock_key_pk(pg_schema_text: str) -> None:
    """The substrate_locks table must declare lock_key as PRIMARY KEY (TEXT)."""
    assert "lock_key" in pg_schema_text
    assert "TEXT PRIMARY KEY" in pg_schema_text


def test_pg_schema_substrate_locks_uses_postgres_types(pg_schema_text: str) -> None:
    """Native Postgres types only — TIMESTAMPTZ, BOOLEAN, TEXT (not VARCHAR)."""
    table_section = pg_schema_text.split("substrate_locks", 1)[1]
    assert "VARCHAR" not in table_section, "Use TEXT, not VARCHAR, for Postgres substrate_locks"
    assert "TIMESTAMPTZ" in table_section, "substrate_locks must use TIMESTAMPTZ"
    assert "BOOLEAN" in table_section, "substrate_locks must use BOOLEAN"


def test_pg_schema_substrate_locks_has_supporting_indexes(pg_schema_text: str) -> None:
    """The supporting indexes from 0003_locks.sql must also be present."""
    assert "idx_substrate_locks_expires_at" in pg_schema_text
    assert "idx_substrate_locks_is_permanent" in pg_schema_text
