"""In-memory DuckDB adapter for the Dhara SQL proxy.

Provides ``DuckDBAdapter`` — a singleton async wrapper around an in-memory
``duckdb.DuckDBPyConnection``. The SQL proxy tools use this adapter as the
default backend in dev/test (production uses asyncpg via ``PostgresAdapter``).

The connection is process-local: a single in-memory DuckDB instance is shared
by all callers within the same process. ``reset_singleton`` is provided so
tests can isolate state.
"""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Any

try:
    import duckdb
except ImportError as exc:  # pragma: no cover - exercised via pyproject extras
    raise ImportError(
        "duckdb is required for the DuckDBAdapter. "
        "Install Dhara with the 'sql' extra: pip install 'dhara[sql]'."
    ) from exc

# Statement prefixes allowed by ``query`` (read-only).
_SELECT_PREFIXES: tuple[str, ...] = (
    "SELECT",
    "WITH",
    "PRAGMA",  # DuckDB-specific; read-only metadata
    "SHOW",  # DuckDB-specific; read-only metadata
    "EXPLAIN",  # Plan inspection only
)

# Statement prefixes refused by ``execute`` (destructive to the whole instance).
_FORBIDDEN_EXECUTE_PREFIXES: tuple[str, ...] = (
    "DROP DATABASE",
    "DROP SCHEMA",
)


class DuckDBAdapter:
    """Async wrapper around a process-shared in-memory DuckDB connection.

    The adapter exposes ``execute`` and ``query`` methods that mirror the
    SQL proxy MCP tools. All calls run the synchronous DuckDB driver inside
    ``asyncio.to_thread`` so the event loop is never blocked.

    Connection is lazily created on first instantiation and shared across
    instances; tests can call ``reset_singleton`` to drop it.
    """

    _instance: DuckDBAdapter | None = None
    _lock = threading.Lock()

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn

    @classmethod
    async def create(cls, path: str | None = None) -> DuckDBAdapter:
        """Return a (possibly shared) DuckDBAdapter.

        Args:
            path: Filesystem path for the DuckDB database. Defaults to
                ``DHARA_SQL_DUCKDB_PATH`` env var, or ``":memory:"`` if unset.
                Use ``":memory:"`` for a per-process in-memory database.
        """
        # Fast path: already initialized and the caller did not override path.
        with cls._lock:
            existing = cls._instance
            if existing is not None and path is None:
                return existing

        target_path = path or os.environ.get("DHARA_SQL_DUCKDB_PATH", ":memory:")

        def _open() -> duckdb.DuckDBPyConnection:
            return duckdb.connect(target_path)

        conn = await asyncio.to_thread(_open)
        adapter = cls(conn)
        if target_path == ":memory:" and path is None:
            with cls._lock:
                cls._instance = adapter
        return adapter

    async def execute(
        self,
        sql: str,
        params: list[Any] | None,
    ) -> dict[str, Any]:
        """Execute a DDL/DML statement.

        Returns ``{"rows_affected": int, "last_row_id": Any | None,
        "status": "ok"}``. Raises ``ValueError`` for forbidden statements.
        """
        normalized = sql.strip().upper()
        for prefix in _FORBIDDEN_EXECUTE_PREFIXES:
            if normalized.startswith(prefix):
                raise ValueError(f"Refusing to execute destructive statement: {sql!r}")

        dml_prefixes = ("INSERT", "UPDATE", "DELETE", "MERGE", "COPY")
        is_dml = normalized.startswith(dml_prefixes)

        # For DML, wrap with RETURNING so we get accurate rowcount and
        # last_row_id in a single round trip (DuckDB's cursor.rowcount is -1
        # for DML and lastrowid is unreliable for batched statements).
        if is_dml and "RETURNING" not in normalized:

            def _run_dml() -> tuple[int, Any]:
                base = sql.rstrip().rstrip(";").rstrip()
                wrapped = f"{base} RETURNING 1"
                rows = self._conn.execute(wrapped, params or []).fetchall()
                return len(rows), rows[-1][0] if rows else None

            rowcount, last_id = await asyncio.to_thread(_run_dml)
        else:

            def _run() -> tuple[int, Any]:
                cursor = self._conn.execute(sql, params or [])
                raw = cursor.rowcount
                if raw is None or raw < 0:
                    rowcount = 0
                else:
                    rowcount = raw
                last_id: Any = getattr(cursor, "lastrowid", None)
                return rowcount, last_id

            rowcount, last_id = await asyncio.to_thread(_run)

        return {
            "rows_affected": rowcount,
            "last_row_id": last_id,
            "status": "ok",
        }

    async def query(
        self,
        sql: str,
        params: list[Any] | None,
    ) -> list[dict[str, Any]]:
        """Execute a read-only SELECT/WITH statement and return list[dict].

        Raises ``ValueError`` if the statement is not a SELECT/WITH/etc.
        """
        normalized = sql.strip().upper()
        if not any(normalized.startswith(p) for p in _SELECT_PREFIXES):
            raise ValueError(
                f"Refusing non-SELECT statement in query(): {sql!r}. "
                f"Allowed prefixes: {', '.join(_SELECT_PREFIXES)}."
            )

        def _run() -> list[dict[str, Any]]:
            cursor = self._conn.execute(sql, params or [])
            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            return [dict(zip(columns, row, strict=False)) for row in rows]

        return await asyncio.to_thread(_run)

    async def close(self) -> None:
        """Close the underlying DuckDB connection (idempotent)."""
        conn = self._conn
        if conn is not None:
            await asyncio.to_thread(conn.close)


async def reset_singleton() -> None:
    """Drop the shared singleton (test helper).

    Closes the current in-memory connection (if any) so the next
    ``DuckDBAdapter.create()`` returns a fresh database.
    """
    with DuckDBAdapter._lock:
        existing = DuckDBAdapter._instance
        DuckDBAdapter._instance = None
    if existing is not None:
        await existing.close()


__all__ = ["DuckDBAdapter", "reset_singleton"]
