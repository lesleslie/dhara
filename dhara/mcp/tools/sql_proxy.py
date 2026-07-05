"""SQL proxy MCP tools for Dhara.

Exposes a generic SQL proxy — backed by DuckDB in dev/test and asyncpg
in production — as two MCP tools:

* ``dhara_sql_execute(sql, params)`` — DDL/DML; returns ``rows_affected``,
  ``last_row_id`` and ``status``.
* ``dhara_sql_query(sql, params)`` — read-only SELECT/WITH/PRAGMA/SHOW/
  EXPLAIN; returns ``list[dict]``.

Both tools go through a single in-process backend singleton selected by
``DHARA_SQL_BACKEND`` (default ``"duckdb"``). The backend abstraction
keeps the surface stable when swapping to ``PostgresAdapter``.

Functions are plain async callables; ``DharaMCPServer`` decorates them
with FastMCP ``@server.tool()`` at registration time. Tests therefore
import the module and call the functions directly.
"""

from __future__ import annotations

import os
from typing import Any

from dhara.storage.duckdb_adapter import DuckDBAdapter

# Re-exported so callers don't need to import the storage layer directly.
from dhara.storage.duckdb_adapter import DuckDBAdapter as _DuckDBAdapter  # noqa: F401

# SELECT-prefix policy. ``query`` accepts only these prefixes; anything
# else raises ValueError. DuckDB-specific read-only statements
# (``PRAGMA``, ``SHOW``, ``EXPLAIN``) are included for parity with the
# adapter's own check.
_QUERY_ALLOWED_PREFIXES: tuple[str, ...] = (
    "SELECT",
    "WITH",
    "PRAGMA",
    "SHOW",
    "EXPLAIN",
)


# Forbidden DDL — destructive to the entire instance, not just one table.
_EXECUTE_FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "DROP DATABASE",
    "DROP SCHEMA",
)


async def _get_backend() -> DuckDBAdapter:
    """Return the configured SQL backend (DuckDB by default)."""
    backend_name = os.environ.get("DHARA_SQL_BACKEND", "duckdb").lower()
    if backend_name != "duckdb":
        raise NotImplementedError(
            f"SQL backend {backend_name!r} is not yet wired up; "
            f"only 'duckdb' is currently supported."
        )
    return await DuckDBAdapter.create()


def _enforce_query_safety(sql: str) -> None:
    """Raise ``ValueError`` if the SQL is not a SELECT-family statement."""
    normalized = sql.strip().upper()
    if not normalized:
        raise ValueError("Refusing to query empty SQL statement.")
    if not any(normalized.startswith(p) for p in _QUERY_ALLOWED_PREFIXES):
        raise ValueError(
            f"Refusing non-SELECT statement in dhara_sql_query: {sql!r}. "
            f"Allowed prefixes: {', '.join(_QUERY_ALLOWED_PREFIXES)}. "
            f"Use dhara_sql_execute for DDL/DML."
        )


def _enforce_execute_safety(sql: str) -> None:
    """Raise ``ValueError`` if the SQL is forbidden for execute()."""
    normalized = sql.strip().upper()
    if not normalized:
        raise ValueError("Refusing to execute empty SQL statement.")
    for prefix in _EXECUTE_FORBIDDEN_PREFIXES:
        if normalized.startswith(prefix):
            raise ValueError(f"Refusing to execute destructive statement: {sql!r}")


async def dhara_sql_execute(
    sql: str,
    params: list[Any] | None = None,
) -> dict[str, Any]:
    """Execute a DDL/DML statement and return rowcount + status.

    Args:
        sql: The SQL statement (CREATE/INSERT/UPDATE/DELETE/...).
        params: Optional positional parameter list bound with ``?``
            placeholders (DuckDB syntax).

    Returns:
        ``{"rows_affected": int, "last_row_id": Any | None,
        "status": "ok"}``.

    Raises:
        ValueError: If the statement is empty or forbidden (DROP DATABASE /
            DROP SCHEMA).
    """
    _enforce_execute_safety(sql)
    backend = await _get_backend()
    return await backend.execute(sql, params)  # type: ignore[no-any-return]


async def dhara_sql_query(
    sql: str,
    params: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Execute a read-only SELECT/WITH query and return list[dict].

    Args:
        sql: The SELECT-family statement.
        params: Optional positional parameter list bound with ``?``
            placeholders (DuckDB syntax).

    Returns:
        ``list[dict[str, Any]]`` — one entry per row, keyed by SELECT
        projection names.

    Raises:
        ValueError: If the statement is not SELECT-family.
    """
    _enforce_query_safety(sql)
    backend = await _get_backend()
    return await backend.query(sql, params)  # type: ignore[no-any-return]


__all__ = [
    "dhara_sql_execute",
    "dhara_sql_query",
    "DuckDBAdapter",
]
