"""Tests for DharaLock Protocol surface — behavior, not reflection."""

from __future__ import annotations

from datetime import UTC, datetime

from dhara.lock import (
    DharaLock,
    InMemoryDharaLock,
    LockHandle,
    LockLost,
    LockPermanentError,
    LockTimeout,
)


def test_lock_handle_instantiation_round_trip() -> None:
    """Behavior: LockHandle fields are real attributes, not just annotations."""
    handle = LockHandle(
        lock_key="k",
        owner_token="t",
        acquired_at=datetime.now(UTC),
        expires_at=None,
        is_permanent=False,
        original_ttl_seconds=None,
        metadata={"foo": "bar"},
    )
    assert handle.lock_key == "k"
    assert handle.metadata == {"foo": "bar"}


def test_dhara_lock_protocol_impl_via_isinstance() -> None:
    """Behavior: concrete impl satisfies Protocol (runtime_checkable)."""
    impl = InMemoryDharaLock()
    # If InMemoryDharaLock doesn't satisfy the Protocol (missing method), this raises.
    assert isinstance(impl, DharaLock)


def test_exception_classes_exist() -> None:
    assert issubclass(LockTimeout, Exception)
    assert issubclass(LockLost, Exception)
    assert issubclass(LockPermanentError, Exception)
