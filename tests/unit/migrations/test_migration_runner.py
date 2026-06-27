from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pytest

from dhara.migrations.runner import MigrationError, run_migrations


@pytest.fixture
def fresh_db() -> Any:
    """Fresh in-memory DuckDB connection per test."""
    conn = duckdb.connect(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    """Directory containing two simple SQL migrations for testing."""
    sql_dir = tmp_path / "migrations"
    sql_dir.mkdir()
    (sql_dir / "0001_create_users.sql").write_text(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);"
    )
    (sql_dir / "0002_create_orders.sql").write_text(
        "CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER);"
    )
    return sql_dir


@pytest.mark.unit
async def test_run_migrations_applies_all_files_in_lexical_order(
    fresh_db: duckdb.DuckDBPyConnection, migrations_dir: Path
) -> None:
    """All *.sql files are applied in lexical order; each is recorded in dhara_migrations."""
    applied = await run_migrations(fresh_db, migrations_dir=migrations_dir)

    assert applied == ["0001_create_users", "0002_create_orders"]

    # Both tables exist
    tables = {row[0] for row in fresh_db.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
    ).fetchall()}
    assert {"users", "orders", "dhara_migrations"} <= tables

    # Bookkeeping row exists for each migration
    rows = fresh_db.execute(
        "SELECT version FROM dhara_migrations ORDER BY version"
    ).fetchall()
    assert [r[0] for r in rows] == ["0001_create_users", "0002_create_orders"]


@pytest.mark.unit
async def test_run_migrations_is_idempotent(
    fresh_db: duckdb.DuckDBPyConnection, migrations_dir: Path
) -> None:
    """A second run applies nothing new; version set is preserved."""
    first = await run_migrations(fresh_db, migrations_dir=migrations_dir)
    second = await run_migrations(fresh_db, migrations_dir=migrations_dir)

    assert first == ["0001_create_users", "0002_create_orders"]
    assert second == []

    # Still exactly two bookkeeping rows
    count = fresh_db.execute("SELECT COUNT(*) FROM dhara_migrations").fetchone()[0]
    assert count == 2


@pytest.mark.unit
async def test_run_migrations_records_applied_at_timestamp(
    fresh_db: duckdb.DuckDBPyConnection, migrations_dir: Path
) -> None:
    """Each bookkeeping row carries an applied_at timestamp."""
    await run_migrations(fresh_db, migrations_dir=migrations_dir)

    rows = fresh_db.execute(
        "SELECT version, applied_at FROM dhara_migrations ORDER BY version"
    ).fetchall()
    assert len(rows) == 2
    for _version, applied_at in rows:
        assert applied_at is not None


@pytest.mark.unit
async def test_run_migrations_partial_failure_rolls_back(
    fresh_db: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    """A bad SQL statement in migration 0002 rolls back 0002 but keeps 0001 applied."""
    sql_dir = tmp_path / "bad"
    sql_dir.mkdir()
    (sql_dir / "0001_good.sql").write_text(
        "CREATE TABLE alpha (id INTEGER);"
    )
    (sql_dir / "0002_bad.sql").write_text(
        "CREATE TABLE beta (this is not valid sql);"
    )

    with pytest.raises(MigrationError):
        await run_migrations(fresh_db, migrations_dir=sql_dir)

    # 0001 IS applied; 0002 is NOT applied
    applied = {
        row[0]
        for row in fresh_db.execute(
            "SELECT version FROM dhara_migrations"
        ).fetchall()
    }
    assert "0001_good" in applied
    assert "0002_bad" not in applied

    # alpha exists (0001 succeeded); beta does not (0002 rolled back)
    tables = {
        row[0]
        for row in fresh_db.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main'"
        ).fetchall()
    }
    assert "alpha" in tables
    assert "beta" not in tables


@pytest.mark.unit
async def test_run_migrations_ignores_non_sql_files(
    fresh_db: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    """Only files matching the discovery pattern are applied."""
    sql_dir = tmp_path / "mixed"
    sql_dir.mkdir()
    (sql_dir / "0001_first.sql").write_text("CREATE TABLE first_t (id INTEGER);")
    (sql_dir / "README.md").write_text("# not a migration")
    (sql_dir / "002_too_short.sql").write_text("CREATE TABLE ignored (id INTEGER);")
    (sql_dir / "_private.sql").write_text("CREATE TABLE ignored (id INTEGER);")

    applied = await run_migrations(fresh_db, migrations_dir=sql_dir)

    assert applied == ["0001_first"]
    # The 4-digit-prefix-only pattern kept the others out
    tables = {
        row[0]
        for row in fresh_db.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main' AND table_name NOT LIKE 'dhara_%'"
        ).fetchall()
    }
    assert tables == {"first_t"}


@pytest.mark.unit
async def test_run_migrations_raises_on_missing_directory(
    fresh_db: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    """A missing migrations directory is a hard error."""
    with pytest.raises(MigrationError):
        await run_migrations(
            fresh_db, migrations_dir=tmp_path / "does_not_exist"
        )


@pytest.mark.unit
async def test_run_migrations_empty_directory_records_nothing(
    fresh_db: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    """An empty migrations directory applies nothing but creates the bookkeeping table."""
    sql_dir = tmp_path / "empty"
    sql_dir.mkdir()
    applied = await run_migrations(fresh_db, migrations_dir=sql_dir)
    assert applied == []

    # Bookkeeping table still exists (so subsequent runs have something to query)
    rows = fresh_db.execute(
        "SELECT COUNT(*) FROM dhara_migrations"
    ).fetchall()
    assert rows[0][0] == 0
