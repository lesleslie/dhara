from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

# Pattern: 4-digit prefix + "_" + name + ".sql" — e.g. "0001_initial.sql".
_MIGRATION_PATTERN = re.compile(r"^\d{4}_.+\.sql$")

# Bookkeeping table — DuckDB-friendly TIMESTAMP; Postgres can override if desired.
_BOOKKEEPING_DDL = """
CREATE TABLE IF NOT EXISTS dhara_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


class MigrationError(RuntimeError):
    """Raised when migrations cannot be discovered or applied."""


class SupportsMigrations(Protocol):
    """Minimal protocol covering DuckDB and asyncpg connection shapes we use.

    DuckDB's ``execute`` is synchronous; asyncpg's is awaitable. The runner
    dispatches on the return type so both backends work transparently.
    """

    def execute(self, sql: str, params: Any = ...) -> Any: ...


def _maybe_await(value: Any) -> Awaitable[Any]:
    """Return ``value`` if it's awaitable, else wrap it as a completed coroutine."""
    if hasattr(value, "__await__"):
        return value  # type: ignore[no-any-return]
    return _CompletedAwaitable(value)


class _CompletedAwaitable:
    """Minimal stand-in for an already-resolved awaitable."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def __await__(self) -> Any:
        if False:  # pragma: no cover — yield makes this a generator
            yield
        return self._value


@dataclass(frozen=True, slots=True)
class AppliedMigration:
    """Record of one applied migration."""

    version: str
    applied_at: str


def _discover_versions(directory: Path) -> list[str]:
    """Return the sorted list of migration version strings in ``directory``."""
    if not directory.exists():
        raise MigrationError(f"Migrations directory does not exist: {directory}")
    if not directory.is_dir():
        raise MigrationError(f"Migrations path is not a directory: {directory}")

    versions: list[str] = []
    for entry in sorted(directory.iterdir()):
        if not entry.is_file():
            continue
        if not _MIGRATION_PATTERN.match(entry.name):
            continue
        # Strip the ".sql" suffix to get the version key (e.g. "0001_initial").
        versions.append(entry.name[: -len(".sql")])
    return versions


def _read_sql_file(directory: Path, version: str) -> str:
    """Read the SQL body for a migration version."""
    path = directory / f"{version}.sql"
    return path.read_text(encoding="utf-8")


def _is_awaitable(conn: Any) -> bool:
    """Return True if ``conn.execute`` returns an awaitable (asyncpg-style)."""
    # Inspecting ``execute`` is tricky without calling it; check for the
    # ``_impl`` attribute that asyncpg.Connection exposes, or a class flag.
    cls = getattr(conn, "__class__", None)
    if cls is None:
        return False
    return getattr(cls, "_IS_ASYNC", False) or cls.__module__.startswith("asyncpg")


async def _ensure_bookkeeping_table(conn: Any) -> None:
    result = conn.execute(_BOOKKEEPING_DDL)
    await _maybe_await(result)


async def _fetch_applied_versions(conn: Any) -> set[str]:
    result = conn.execute("SELECT version FROM dhara_migrations ORDER BY version")
    result = await _maybe_await(result)
    rows = (
        await _maybe_await(result.fetchall())
        if hasattr(result, "fetchall")
        else result.fetchall()
    )
    return {row[0] for row in rows}


def _execute_raw(conn: Any, sql: str, params: Any = None) -> Any:
    """Execute a SQL string and return the raw result (possibly awaitable)."""
    if params is None:
        return conn.execute(sql)
    return conn.execute(sql, params)


async def _wait(value: Any) -> None:
    """Await ``value`` if it is awaitable; no-op otherwise."""
    await _maybe_await(value)


async def run_migrations(
    connection: Any,
    *,
    migrations_dir: Path | str = Path("dhara/migrations/sql"),
) -> list[str]:
    """Apply every pending migration in ``migrations_dir`` and return their versions.

    Migrations are ``*.sql`` files with a four-digit numeric prefix and an
    underscore separator (e.g. ``0001_initial.sql``). The runner:

    1. Ensures a ``dhara_migrations`` bookkeeping table exists.
    2. Discovers all matching files and applies the ones whose version is not
       already in the bookkeeping table, in lexical order.
    3. Records each successfully applied version in ``dhara_migrations``.

    Each migration is executed as a single statement batch; the bookkeeping
    insert happens only after the DDL succeeds, so a failure in migration N
    leaves the runner ready to apply N again on the next run.

    Returns the list of versions that were applied during this call (in order).
    """
    sql_dir = Path(migrations_dir)

    versions = _discover_versions(sql_dir)

    await _ensure_bookkeeping_table(connection)
    already_applied = await _fetch_applied_versions(connection)

    newly_applied: list[str] = []
    for version in versions:
        if version in already_applied:
            continue
        sql_body = _read_sql_file(sql_dir, version)
        try:
            # Execute the migration DDL.
            await _wait(_execute_raw(connection, sql_body))
        except Exception as exc:
            raise MigrationError(f"Migration {version} failed: {exc}") from exc
        # Record the version only after the DDL succeeded.
        await _wait(
            _execute_raw(
                connection,
                "INSERT INTO dhara_migrations (version) VALUES (?)",
                (version,),
            )
        )
        newly_applied.append(version)

    return newly_applied


__all__ = [
    "AppliedMigration",
    "MigrationError",
    "run_migrations",
]


# Silence "imported but unused" for the Callable import — kept for forward
# compatibility with subscribers that may want a callable API.
_ = Callable
