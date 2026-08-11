"""Integration test: apply pg_schema.sql to a live Postgres and assert
substrate_locks (and supporting indexes) are created.

Skipped when:
  * asyncpg is not importable (no asyncpg dep installed)
  * --pg-url was not passed to pytest (no live Postgres available)

Brief reference: D-LOCK v1.1 Task 1, integration test gated behind asyncpg / --pg-url.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

PG_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "dhara" / "storage" / "pg_schema.sql"

# Skip this entire module when asyncpg isn't importable. This is the
# pytest.importorskip gate from the brief.
asyncpg = pytest.importorskip("asyncpg")


def _pg_url(config: pytest.Config) -> str | None:
    return config.getoption("--pg-url") or os.environ.get("DHARA_TEST_PG_URL")


@pytest.fixture(scope="module")
async def pg_schema_sql() -> str:
    return PG_SCHEMA_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
async def pg_pool(request: pytest.FixtureRequest):
    url = _pg_url(request.config)
    if not url:
        pytest.skip("--pg-url / DHARA_TEST_PG_URL not set; skipping live Postgres test")
    pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    assert pool is not None
    try:
        yield pool
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_substrate_locks_table_exists(pg_pool, pg_schema_sql: str) -> None:
    async with pg_pool.acquire() as conn:
        # Apply the full schema (idempotent CREATE TABLE / INDEX IF NOT EXISTS).
        await conn.execute(pg_schema_sql)
        row = await conn.fetchrow(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'substrate_locks'
            """
        )
        assert row is not None, "substrate_locks table not created by pg_schema.sql"


@pytest.mark.asyncio
async def test_substrate_locks_has_expected_columns(pg_pool, pg_schema_sql: str) -> None:
    async with pg_pool.acquire() as conn:
        await conn.execute(pg_schema_sql)
        rows = await conn.fetch(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'substrate_locks'
            """
        )
    cols = {r["column_name"]: (r["data_type"], r["is_nullable"]) for r in rows}
    expected = {
        "lock_key": ("text", "NO"),
        "owner_token": ("text", "NO"),
        "acquired_at": ("timestamp with time zone", "NO"),
        "expires_at": ("timestamp with time zone", "YES"),
        "is_permanent": ("boolean", "NO"),
        "original_ttl_seconds": ("integer", "YES"),
        "metadata": ("text", "NO"),
    }
    assert cols == expected, f"column mismatch: got={cols} want={expected}"


@pytest.mark.asyncio
async def test_substrate_locks_supporting_indexes_exist(
    pg_pool, pg_schema_sql: str
) -> None:
    async with pg_pool.acquire() as conn:
        await conn.execute(pg_schema_sql)
        rows = await conn.fetch(
            """
            SELECT indexname FROM pg_indexes
            WHERE schemaname = 'public' AND tablename = 'substrate_locks'
            """
        )
    names = {r["indexname"] for r in rows}
    assert "idx_substrate_locks_expires_at" in names
    assert "idx_substrate_locks_is_permanent" in names
