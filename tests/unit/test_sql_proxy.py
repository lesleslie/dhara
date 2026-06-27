"""Unit tests for the Dhara SQL proxy MCP tools.

TDD red phase: these tests pin the public contract of
``dhara.mcp.tools.sql_proxy``. They will fail until the module
exists.

Both tools must:
  * operate against an in-memory DuckDB backend for unit tests;
  * be invokable as plain async functions (the FastMCP decorator
    is applied at registration time, but the underlying functions
    remain callable for direct unit testing);
  * honour a SQL safety policy: ``query`` rejects non-SELECTs,
    ``execute`` refuses DROP DATABASE/SCHEMA.
"""

from __future__ import annotations

import os
from typing import Any

# Force DuckDB mode for unit tests.
os.environ.setdefault("DHARA_SQL_BACKEND", "duckdb")
os.environ.setdefault("DHARA_SQL_DUCKDB_PATH", ":memory:")

import pytest

from dhara.mcp.tools import sql_proxy
from dhara.storage.duckdb_adapter import reset_singleton


@pytest.fixture(autouse=True)
async def _reset_backend() -> None:
    """Each test starts on a clean in-memory DuckDB."""
    await reset_singleton()


@pytest.mark.unit
async def test_dhara_sql_execute_returns_dict_with_required_keys() -> None:
    """dhara_sql_execute returns ``rows_affected`` and ``status``."""
    result = await sql_proxy.dhara_sql_execute(
        sql="CREATE TABLE t (id INTEGER PRIMARY KEY)",
        params=None,
    )
    assert isinstance(result, dict)
    assert "rows_affected" in result
    assert "status" in result


@pytest.mark.unit
async def test_dhara_sql_execute_insert_returns_rows_affected() -> None:
    """INSERT through the proxy reports rows_affected=1."""
    await sql_proxy.dhara_sql_execute(
        sql="CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)",
        params=None,
    )
    result = await sql_proxy.dhara_sql_execute(
        sql="INSERT INTO t (id, name) VALUES (?, ?)",
        params=[1, "alice"],
    )
    assert result["rows_affected"] == 1
    assert result["status"] == "ok"


@pytest.mark.unit
async def test_dhara_sql_execute_refuses_drop_database() -> None:
    """``DROP DATABASE`` is rejected by the proxy."""
    with pytest.raises(ValueError):
        await sql_proxy.dhara_sql_execute(
            sql="DROP DATABASE foo",
            params=None,
        )


@pytest.mark.unit
async def test_dhara_sql_execute_refuses_drop_schema() -> None:
    """``DROP SCHEMA`` is rejected by the proxy."""
    with pytest.raises(ValueError):
        await sql_proxy.dhara_sql_execute(
            sql="DROP SCHEMA foo",
            params=None,
        )


@pytest.mark.unit
async def test_dhara_sql_query_returns_list_of_dicts() -> None:
    """``dhara_sql_query`` returns list[dict[str, Any]]."""
    await sql_proxy.dhara_sql_execute(
        sql="CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)",
        params=None,
    )
    await sql_proxy.dhara_sql_execute(
        sql="INSERT INTO t (id, name) VALUES (?, ?)", params=[1, "alice"]
    )
    await sql_proxy.dhara_sql_execute(
        sql="INSERT INTO t (id, name) VALUES (?, ?)", params=[2, "bob"]
    )
    rows = await sql_proxy.dhara_sql_query(
        sql="SELECT id, name FROM t ORDER BY id",
        params=None,
    )
    assert isinstance(rows, list)
    assert rows == [
        {"id": 1, "name": "alice"},
        {"id": 2, "name": "bob"},
    ]


@pytest.mark.unit
async def test_dhara_sql_query_rejects_non_select() -> None:
    """``query`` raises ValueError on non-SELECT statements."""
    with pytest.raises(ValueError):
        await sql_proxy.dhara_sql_query(sql="DROP TABLE t", params=None)
    with pytest.raises(ValueError):
        await sql_proxy.dhara_sql_query(
            sql="INSERT INTO t VALUES (1)", params=None
        )
    with pytest.raises(ValueError):
        await sql_proxy.dhara_sql_query(sql="UPDATE t SET x=1", params=None)
    with pytest.raises(ValueError):
        await sql_proxy.dhara_sql_query(sql="DELETE FROM t", params=None)


@pytest.mark.unit
async def test_dhara_sql_query_supports_with_clause() -> None:
    """WITH ... SELECT is allowed by the safety policy."""
    rows = await sql_proxy.dhara_sql_query(
        sql="WITH cte AS (SELECT 1 AS n) SELECT n FROM cte",
        params=None,
    )
    assert rows == [{"n": 1}]


@pytest.mark.unit
async def test_dhara_sql_query_with_params_binds_correctly() -> None:
    """``params`` are passed through to the backend."""
    await sql_proxy.dhara_sql_execute(
        sql="CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)",
        params=None,
    )
    await sql_proxy.dhara_sql_execute(
        sql="INSERT INTO t (id, name) VALUES (?, ?)", params=[1, "alice"]
    )
    rows = await sql_proxy.dhara_sql_query(
        sql="SELECT name FROM t WHERE id = ?", params=[1]
    )
    assert rows == [{"name": "alice"}]


@pytest.mark.unit
async def test_dhara_sql_execute_allows_create() -> None:
    """CREATE TABLE through the proxy is permitted."""
    result = await sql_proxy.dhara_sql_execute(
        sql="CREATE TABLE items (id INTEGER PRIMARY KEY)",
        params=None,
    )
    assert result["status"] == "ok"


@pytest.mark.parametrize(
    "sql,params",
    [
        ("SELECT 1 AS one", None),
        ("SELECT 1 AS one", []),
        ("SELECT ? AS one", [42]),
        (
            "SELECT id, name FROM (VALUES (1,'a'),(2,'b')) t(id,name) ORDER BY id",
            None,
        ),
        (
            "SELECT name FROM (VALUES ('x'),('y')) t(name) WHERE name = ?",
            ["x"],
        ),
        ("WITH cte AS (SELECT 1 AS n) SELECT n FROM cte", None),
    ],
)
@pytest.mark.unit
async def test_dhara_sql_query_parametrized(
    sql: str, params: list[Any] | None
) -> None:
    """Run a battery of SELECT statements through the proxy."""
    rows = await sql_proxy.dhara_sql_query(sql=sql, params=params)
    assert isinstance(rows, list)
    assert all(isinstance(row, dict) for row in rows)


@pytest.mark.parametrize(
    "sql,params",
    [
        ("CREATE TABLE a1 (id INTEGER PRIMARY KEY)", None),
        ("CREATE TABLE a2 (id INTEGER PRIMARY KEY)", None),
        ("CREATE TABLE a3 (id INTEGER PRIMARY KEY)", None),
        ("CREATE TABLE a4 (id INTEGER PRIMARY KEY)", None),
    ],
)
@pytest.mark.unit
async def test_dhara_sql_execute_parametrized(
    sql: str, params: list[Any] | None
) -> None:
    """DDL + DML statements are accepted by ``execute``."""
    result = await sql_proxy.dhara_sql_execute(sql=sql, params=params)
    assert result["status"] == "ok"


@pytest.mark.parametrize(
    "sql,params",
    [
        ("INSERT INTO a1 (id) VALUES (?)", [1]),
        ("UPDATE a1 SET id = ? WHERE id = ?", [2, 1]),
        ("DELETE FROM a1 WHERE id = ?", [2]),
        ("CREATE TABLE a5 (id INTEGER PRIMARY KEY)", None),
    ],
)
@pytest.mark.unit
async def test_dhara_sql_execute_dml_parametrized(
    sql: str, params: list[Any] | None
) -> None:
    """Mixed DML/DDL statements are accepted by ``execute``."""
    # Seed a1 so INSERT/UPDATE/DELETE can match.
    await sql_proxy.dhara_sql_execute(
        sql="CREATE TABLE IF NOT EXISTS a1 (id INTEGER PRIMARY KEY)",
        params=None,
    )
    await sql_proxy.dhara_sql_execute(
        sql="INSERT INTO a1 (id) VALUES (?)", params=[100]
    )
    result = await sql_proxy.dhara_sql_execute(sql=sql, params=params)
    assert result["status"] == "ok"
