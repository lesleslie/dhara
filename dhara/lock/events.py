"""Structured audit event emission for D-LOCK."""

from __future__ import annotations

from typing import Any, Protocol

from dhara.lock.protocol import LockHandle


class EventSink(Protocol):
    def emit(self, event_type: str, **payload: Any) -> None: ...


class NullSink:
    def emit(self, event_type: str, **payload: Any) -> None:
        return None


class LockEventEmitter:
    """Emits audit:lock.* events with structured payload."""

    def __init__(self, sink: EventSink | None = None) -> None:
        self._sink: EventSink = sink or NullSink()

    def acquired(self, handle: LockHandle) -> None:
        self._sink.emit(
            "audit:lock.acquired",
            lock_key=handle.lock_key,
            owner_token=handle.owner_token,
            ttl_seconds=handle.original_ttl_seconds,
            is_permanent=handle.is_permanent,
        )

    def released(self, handle: LockHandle) -> None:
        self._sink.emit(
            "audit:lock.released",
            lock_key=handle.lock_key,
            owner_token=handle.owner_token,
        )

    def heartbeat(self, handle: LockHandle) -> None:
        self._sink.emit(
            "audit:lock.heartbeat",
            lock_key=handle.lock_key,
            owner_token=handle.owner_token,
        )

    def lost(self, lock_key: str, owner_token: str, reason: str) -> None:
        self._sink.emit(
            "audit:lock.lost",
            lock_key=lock_key,
            owner_token=owner_token,
            reason=reason,
        )
