"""InMemoryDharaLock — test-double DharaLock implementation backed by a Python dict.

This is the spec-mandated rename of `LockStore`'s `InMemoryLockStore`.
Used in tests where a real SQL backend is overkill.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from dhara.lock.protocol import LockHandle, LockLost, LockPermanentError, LockTimeout


class InMemoryDharaLock:
    def __init__(self) -> None:
        self._items: dict[str, LockHandle] = {}

    def try_acquire(
        self,
        lock_key: str,
        *,
        owner_token: str | None = None,
        ttl_seconds: int | None = None,
        permanent: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> LockHandle | None:
        if permanent and ttl_seconds is not None:
            raise ValueError("permanent=True is mutually exclusive with ttl_seconds")
        if lock_key in self._items:
            existing = self._items[lock_key]
            if existing.is_permanent:
                raise ValueError(f"duplicate lock_id: {lock_key}")
            return None

        now = datetime.now(UTC)
        token = owner_token or uuid.uuid4().hex
        expires_at = None if ttl_seconds is None else now + timedelta(seconds=ttl_seconds)
        handle = LockHandle(
            lock_key=lock_key,
            owner_token=token,
            acquired_at=now,
            expires_at=expires_at,
            is_permanent=permanent,
            original_ttl_seconds=ttl_seconds,
            metadata=metadata or {},
        )
        self._items[lock_key] = handle
        return handle

    async def acquire(
        self,
        lock_key: str,
        *,
        owner_token: str | None = None,
        ttl_seconds: int | None = None,
        permanent: bool = False,
        timeout_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LockHandle:
        if permanent and ttl_seconds is not None:
            raise ValueError("permanent=True is mutually exclusive with ttl_seconds")

        try:
            handle = self.try_acquire(
                lock_key,
                owner_token=owner_token,
                ttl_seconds=ttl_seconds,
                permanent=permanent,
                metadata=metadata,
            )
        except ValueError:
            raise LockTimeout(f"permanent-held: {lock_key}") from None
        if handle is not None:
            return handle
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise LockTimeout(f"acquire timed out: {lock_key}")

        deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
        while True:
            await asyncio.sleep(0)
            try:
                handle = self.try_acquire(
                    lock_key,
                    owner_token=owner_token,
                    ttl_seconds=ttl_seconds,
                    permanent=permanent,
                    metadata=metadata,
                )
            except ValueError:
                raise LockTimeout(f"permanent-held: {lock_key}") from None
            if handle is not None:
                return handle
            if deadline is not None and time.monotonic() >= deadline:
                raise LockTimeout(f"acquire timed out: {lock_key}")

    def try_release(self, handle: LockHandle) -> bool:
        if handle.is_permanent:
            return False
        existing = self._items.get(handle.lock_key)
        if existing is None or existing.owner_token != handle.owner_token:
            return False
        del self._items[handle.lock_key]
        return True

    def release(self, handle: LockHandle) -> None:
        if handle.is_permanent:
            raise LockPermanentError(f"cannot release permanent: {handle.lock_key}")
        existing = self._items.get(handle.lock_key)
        if existing is None:
            raise LockLost(f"lock vanished: {handle.lock_key}")
        if existing.is_permanent:
            raise LockPermanentError(f"row became permanent: {handle.lock_key}")
        if existing.owner_token != handle.owner_token:
            raise LockLost(f"owner mismatch: {handle.lock_key}")
        del self._items[handle.lock_key]

    def heartbeat(
        self,
        handle: LockHandle,
        *,
        extend_seconds: int | None = None,
    ) -> None:
        if handle.is_permanent:
            raise LockPermanentError(f"cannot heartbeat permanent: {handle.lock_key}")
        if handle.expires_at is None:
            raise ValueError("cannot heartbeat advisory lock (no TTL)")
        extend = extend_seconds if extend_seconds is not None else (handle.original_ttl_seconds or 0)
        if extend <= 0:
            raise ValueError("extend_seconds must be positive")
        existing = self._items.get(handle.lock_key)
        if existing is None:
            raise LockLost(f"lock vanished: {handle.lock_key}")
        if existing.is_permanent:
            raise LockPermanentError(f"row became permanent: {handle.lock_key}")
        if existing.owner_token != handle.owner_token:
            raise LockLost(f"owner mismatch: {handle.lock_key}")
        new_expires_at = datetime.now(UTC) + timedelta(seconds=extend)
        self._items[handle.lock_key] = replace(existing, expires_at=new_expires_at)

    def get(self, lock_key: str) -> LockHandle | None:
        return self._items.get(lock_key)

    def list_keys(self, prefix: str | None = None) -> list[LockHandle]:
        items = self._items.values()
        if prefix is not None:
            items = [handle for handle in items if handle.lock_key.startswith(prefix)]
        return sorted(items, key=lambda handle: handle.acquired_at)
