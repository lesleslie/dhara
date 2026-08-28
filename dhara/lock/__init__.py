"""D-LOCK public API."""

from __future__ import annotations

from dhara.lock.in_memory import InMemoryDharaLock
from dhara.lock.protocol import (
    DharaLock,
    LockHandle,
    LockHeld,
    LockLost,
    LockPermanentError,
    LockTimeout,
)

try:
    from dhara.lock.sql import SQLBackendLock
except ImportError:
    # duckdb is optional; SQLBackendLock is unavailable without it.
    SQLBackendLock = None  # type: ignore[assignment,misc]  # ty: ignore[invalid-assignment]

try:
    from dhara.lock.postgres import PostgresBackendLock
except ImportError:
    # asyncpg is optional; PostgresBackendLock is unavailable without it.
    PostgresBackendLock = None  # type: ignore[assignment,misc]  # ty: ignore[invalid-assignment]

__all__ = [
    "DharaLock",
    "InMemoryDharaLock",
    "LockHandle",
    "LockHeld",
    "LockLost",
    "LockPermanentError",
    "LockTimeout",
    "PostgresBackendLock",
    "SQLBackendLock",
]
