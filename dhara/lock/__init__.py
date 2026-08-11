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
from dhara.lock.sql import SQLBackendLock

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
