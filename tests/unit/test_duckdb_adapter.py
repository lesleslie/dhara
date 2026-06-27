"""Unit tests for DuckDBAdapter (storage layer for sql_proxy).

TDD red phase: these tests pin the expected behaviour of the async
DuckDB-backed adapter. They will fail until ``dhara/storage/duckdb_adapter.py``
is implemented.
"""

from __future__ import annotations

import os

import pytest

from dhara.storage.duckdb_adapter import DuckDBAdapter, reset_singleton

# Force in-memory DuckDB for unit tests so each test process is isolated.
os.environ.setdefault("DHARA_SQL_DUCKDB_PATH", ":memory:")


@pytest.fixture(autouse=True)
async def _reset_duckdb_singleton() -> None:
    """Each test starts with a clean singleton so fixtures don't leak."""
    await reset_singleton()


@pytest.fixture
async def adapter() -> DuckDBAdapter:
    """Return a fresh in-memory DuckDB adapter."""
    return await DuckDBAdapter.create()


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
        "CREATE TABLE events (id INTEGER, payload JSON)",
    ],
)
@pytest.mark.unit
async def test_execute_ddl_returns_rowcount_zero(
    adapter: DuckDBAdapter, sql: str
) -> None:
    """DDL statements report rows_affected=0 via execute()."""
    result = await adapter.execute(sql, None)
    assert result["rows_affected"] == 0
    assert result["status"] == "ok"


@pytest.mark.unit
async def test_execute_insert_returns_rows_affected(adapter: DuckDBAdapter) -> None:
    """INSERT reports rows_affected=1 for single-row inserts."""
    await adapter.execute(
        "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)", None
    )
    result = await adapter.execute(
        "INSERT INTO t (id, name) VALUES (?, ?)",
        [1, "alice"],
    )
    assert result["rows_affected"] == 1
    assert result["status"] == "ok"


@pytest.mark.unit
async def test_execute_insert_supports_last_row_id(adapter: DuckDBAdapter) -> None:
    """When backend supports lastrowid, execute returns last_row_id."""
    await adapter.execute(
        "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)", None
    )
    result = await adapter.execute(
        "INSERT INTO t (id, name) VALUES (?, ?)",
        [42, "bob"],
    )
    # DuckDB supports last_row_id; the adapter surfaces it.
    assert result.get("last_row_id") is not None


@pytest.mark.unit
async def test_execute_update_returns_rows_affected(adapter: DuckDBAdapter) -> None:
    """UPDATE reports rows_affected matching the matched row count."""
    await adapter.execute(
        "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)", None
    )
    await adapter.execute("INSERT INTO t (id, name) VALUES (?, ?)", [1, "alice"])
    await adapter.execute("INSERT INTO t (id, name) VALUES (?, ?)", [2, "bob"])
    result = await adapter.execute(
        "UPDATE t SET name = ? WHERE id = ?",
        ["alex", 1],
    )
    assert result["rows_affected"] == 1


@pytest.mark.unit
async def test_execute_delete_returns_rows_affected(adapter: DuckDBAdapter) -> None:
    """DELETE reports rows_affected matching the deleted row count."""
    await adapter.execute(
        "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)", None
    )
    await adapter.execute("INSERT INTO t (id, name) VALUES (?, ?)", [1, "alice"])
    await adapter.execute("INSERT INTO t (id, name) VALUES (?, ?)", [2, "bob"])
    result = await adapter.execute("DELETE FROM t WHERE id = ?", [1])
    assert result["rows_affected"] == 1


@pytest.mark.parametrize(
    "sql,params,expected_count",
    [
        ("SELECT 1 AS one", None, 1),
        ("SELECT 1 AS one", [], 1),
        (
            "SELECT id, name FROM (VALUES (1,'a'),(2,'b'),(3,'c')) t(id,name)",
            None,
            3,
        ),
        (
            "SELECT name FROM (VALUES ('alice'),('bob')) t(name) WHERE name = ?",
            ["alice"],
            1,
        ),
    ],
)
@pytest.mark.unit
async def test_query_returns_list_of_dicts(
    adapter: DuckDBAdapter,
    sql: str,
    params: list[object] | None,
    expected_count: int,
) -> None:
    """query() returns a list of dict rows; uses ? placeholders."""
    rows = await adapter.query(sql, params)
    assert isinstance(rows, list)
    assert len(rows) == expected_count
    for row in rows:
        assert isinstance(row, dict)


@pytest.mark.unit
async def test_query_returns_column_keys_as_dict_keys(
    adapter: DuckDBAdapter,
) -> None:
    """Each dict row exposes the SELECT projection as its keys."""
    rows = await adapter.query(
        "SELECT id, name FROM (VALUES (1,'alice'),(2,'bob')) t(id,name)",
        None,
    )
    assert rows == [
        {"id": 1, "name": "alice"},
        {"id": 2, "name": "bob"},
    ]


@pytest.mark.unit
async def test_query_rejects_non_select(adapter: DuckDBAdapter) -> None:
    """query() raises ValueError for non-SELECT statements."""
    with pytest.raises(ValueError):
        await adapter.query("DROP TABLE users", None)


@pytest.mark.unit
async def test_query_empty_result_returns_empty_list(
    adapter: DuckDBAdapter,
) -> None:
    """A SELECT with zero matches yields an empty list."""
    rows = await adapter.query("SELECT 1 WHERE 0 = 1", None)
    assert rows == []


@pytest.mark.unit
async def test_execute_drops_unsafe_statements(adapter: DuckDBAdapter) -> None:
    """execute() refuses DROP DATABASE / DROP SCHEMA."""
    for sql in ("DROP DATABASE foo", "DROP SCHEMA foo"):
        with pytest.raises(ValueError):
            await adapter.execute(sql, None)


@pytest.mark.unit
async def test_concurrent_queries_share_singleton() -> None:
    """Two ``DuckDBAdapter.create()`` calls return equivalent connections to the same DB."""
    a = await DuckDBAdapter.create()
    b = await DuckDBAdapter.create()
    await a.execute(
        "CREATE TABLE shared (id INTEGER PRIMARY KEY, label TEXT)", None
    )
    await a.execute(
        "INSERT INTO shared (id, label) VALUES (?, ?)", [1, "x"]
    )
    rows = await b.query("SELECT label FROM shared WHERE id = ?", [1])
    assert rows == [{"label": "x"}]


@pytest.mark.unit
async def test_close_does_not_raise(adapter: DuckDBAdapter) -> None:
    """close() is idempotent and safe."""
    await adapter.close()
    await adapter.close()
