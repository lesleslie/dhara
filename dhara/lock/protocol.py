"""D-LOCK Protocol surface — distributed lock + audit ledger primitive.

See docs/superpowers/specs/2026-08-04-d-lock-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class LockHandle:
    lock_key: str
    owner_token: str
    acquired_at: datetime
    expires_at: datetime | None
    is_permanent: bool
    original_ttl_seconds: int | None
    metadata: dict[str, Any]


class LockTimeout(Exception):
    """acquire(timeout_seconds=N) elapsed without acquiring the lock."""


class LockLost(Exception):
    """release / heartbeat 0-rowcount or owner_token mismatch (after non-permanent row check)."""


class LockPermanentError(Exception):
    """release / heartbeat called on a permanent lock, or heartbeat on advisory lock."""


class LockHeld(Exception):
    """Optional raise-on-held; consumers construct from try_acquire returning None."""


@runtime_checkable
class DharaLock(Protocol):
    def try_acquire(
        self,
        lock_key: str,
        *,
        owner_token: str | None = None,
        ttl_seconds: int | None = None,
        permanent: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> LockHandle | None: ...

    async def acquire(
        self,
        lock_key: str,
        *,
        owner_token: str | None = None,
        ttl_seconds: int | None = None,
        permanent: bool = False,
        timeout_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LockHandle: ...

    def try_release(self, handle: LockHandle) -> bool: ...

    def release(self, handle: LockHandle) -> None: ...

    def heartbeat(
        self,
        handle: LockHandle,
        *,
        extend_seconds: int | None = None,
    ) -> None: ...

    def get(self, lock_key: str) -> LockHandle | None: ...

    def list_keys(self, prefix: str | None = None) -> list[LockHandle]: ...
