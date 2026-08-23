"""Worktree registry keyspace + dataclasses (ADR 015 v4 §11).

Defines the keyspace convention and the value dataclasses that mahavishnu
uses to store worktree state in Dhara. The keyspace is a naming
convention; the actual storage is provided by
``dhara.mcp.kv_timeseries.AsyncKVTimeSeriesStore`` (put/get with TTL).

Keyspace (v4 §11):
    mahavishnu:worktree-registry:<handle_id>            JSON(WorktreeHandle)  [no TTL]
    mahavishnu:worktree-registry:idx:principal:<p>      SET<handle_id>         [no TTL]
    mahavishnu:worktree-registry:idx:repo:<r>           SET<handle_id>         [no TTL]
    mahavishnu:worktree-registry:lock:<p>:<r>:<b>       lease_token            [TTL = lease_ttl]
    mahavishnu:audit-log:<YYYY-MM-DD>:<handle_id>:<seq> JSON(AuditEvent)      [no TTL; archived quarterly]
    mahavishnu:audit-log-idx:handle:<handle_id>         SET<event_id>           [no TTL]
    mahavishnu:audit-log-idx:date:<YYYY-MM-DD>           SET<event_id>           [no TTL]
    mahavishnu:worktree-cache:<handle_id>:<suffix>     bytes                  [TTL = cache_ttl_seconds]

Dataclasses mirror those in ``mahavishnu.auth`` (Principal, CleanupPolicy)
and ``mahavishnu.core.worktree_providers`` (WorktreeHandle, BackendKind,
WorktreeRef, LocalWorktreeRef, S3WorktreeRef). The dataclasses here are
intentionally lightweight (no dependency on mahavishnu); mahavishnu's
classes are the canonical implementation; Dhara's copies are for
serialization roundtrips when mahavishnu is not importable (e.g.,
from a Dhara MCP tool).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal


# Keyspace prefix for all mahavishnu-owned keys in Dhara. The full
# keyspace is namespaced under this prefix so other components
# (akosha, session-buddy, crackerjack) cannot collide.
KEYSPACE_PREFIX = "mahavishnu"


def worktree_registry_key(handle_id: str) -> str:
    """Primary key for a worktree handle record."""
    return f"{KEYSPACE_PREFIX}:worktree-registry:{handle_id}"


def worktree_registry_idx_principal(principal: str) -> str:
    """Secondary index: handles owned by a given principal."""
    return f"{KEYSPACE_PREFIX}:worktree-registry:idx:principal:{principal}"


def worktree_registry_idx_repo(repo: str) -> str:
    """Secondary index: handles for a given repo."""
    return f"{KEYSPACE_PREFIX}:worktree-registry:idx:repo:{repo}"


def worktree_lock_key(principal: str, repo: str, branch: str) -> str:
    """Distributed-lock key for a (principal, repo, branch) tuple.

    Value: lease token (opaque string). TTL: lease_ttl seconds.
    """
    return f"{KEYSPACE_PREFIX}:worktree-registry:lock:{principal}:{repo}:{branch}"


def audit_log_key(date: datetime, handle_id: str, sequence: int) -> str:
    """Append-only audit log entry key.

    Date is normalized to YYYY-MM-DD; sequence is a monotonic per-day
    counter to prevent collisions when multiple events fire in the
    same millisecond.
    """
    date_str = date.astimezone(UTC).strftime("%Y-%m-%d")
    return f"{KEYSPACE_PREFIX}:audit-log:{date_str}:{handle_id}:{sequence}"


def audit_log_idx_handle(handle_id: str) -> str:
    """Secondary index: audit event IDs for a given handle."""
    return f"{KEYSPACE_PREFIX}:audit-log-idx:handle:{handle_id}"


def audit_log_idx_date(date: datetime) -> str:
    """Secondary index: audit event IDs for a given date."""
    date_str = date.astimezone(UTC).strftime("%Y-%m-%d")
    return f"{KEYSPACE_PREFIX}:audit-log-idx:date:{date_str}"


def worktree_cache_key(handle_id: str, suffix: str) -> str:
    """Per-handle cache key. Value: bytes. TTL: cache_ttl_seconds."""
    return f"{KEYSPACE_PREFIX}:worktree-cache:{handle_id}:{suffix}"


# ---------------------------------------------------------------------------
# Dataclasses (mirror of mahavishnu's types for serialization purposes)
# ---------------------------------------------------------------------------

# Where the canonical implementation lives (used for cross-validation in tests)
CANONICAL_TYPES_MODULE = "mahavishnu.auth"
CANONICAL_TYPES_NAMES = ("Principal", "CleanupPolicy")


@dataclass(frozen=True)
class Principal:
    """Identity for storage operations. Mirrors ``mahavishnu.auth.Principal``.

    Constructed via:
      - Principal.from_uid(uid)
      - Principal.anonymous()
      - Principal.current()
    """

    uid: int | None
    name: str
    scopes: list[str] = field(default_factory=list)
    cleanup_policy_override: str | None = None  # Literal["mark", "keep", "remove"]

    @classmethod
    def from_uid(cls, uid: int, *, name: str | None = None) -> "Principal":
        return cls(uid=uid, name=name or f"uid:{uid}")

    @classmethod
    def anonymous(cls) -> "Principal":
        return cls(uid=None, name="anonymous")

    @classmethod
    def current(cls) -> "Principal":
        import os

        return cls.from_uid(os.getuid())

    @property
    def is_anonymous(self) -> bool:
        return self.uid is None


@dataclass(frozen=True)
class AuditEvent:
    """One audit log entry (ADR 015 v4 §11 audit-log schema)."""

    event_id: str  # UUID4 hex
    event_type: str  # e.g. "worktree.created", "worktree.fetched", "lock.acquired"
    principal: Principal
    handle_id: str | None
    payload: dict[str, Any]
    timestamp: datetime
    trace_id: str | None = None


@dataclass
class WorktreeLock:
    """Distributed lock record (ADR 015 v4 §14)."""

    acquire_at: datetime
    expires_at: datetime
    owner_principal: Principal
    fencing_token: int
    repo: str
    branch: str


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def serialize_principal(principal: Principal) -> dict[str, Any]:
    """Serialize a Principal to a JSON-compatible dict for Dhara storage."""
    return asdict(principal)


def deserialize_principal(data: dict[str, Any]) -> Principal:
    """Deserialize a Principal from its JSON dict form."""
    return Principal(**data)


def serialize_audit_event(event: AuditEvent) -> bytes:
    """Serialize an AuditEvent to JSON bytes for Dhara storage."""
    d = asdict(event)
    d["timestamp"] = event.timestamp.isoformat()
    d["principal"] = serialize_principal(event.principal)
    return json.dumps(d, sort_keys=True).encode("utf-8")


def deserialize_audit_event(blob: bytes) -> AuditEvent:
    """Deserialize bytes (as written by serialize_audit_event) to an AuditEvent."""
    raw = json.loads(blob.decode("utf-8"))
    raw["timestamp"] = datetime.fromisoformat(raw["timestamp"])
    raw["principal"] = deserialize_principal(raw["principal"])
    return AuditEvent(**raw)


__all__ = [
    "AuditEvent",
    "CANONICAL_TYPES_MODULE",
    "CANONICAL_TYPES_NAMES",
    "KEYSPACE_PREFIX",
    "Principal",
    "WorktreeLock",
    "audit_log_idx_date",
    "audit_log_idx_handle",
    "audit_log_key",
    "deserialize_audit_event",
    "deserialize_principal",
    "serialize_audit_event",
    "serialize_principal",
    "worktree_cache_key",
    "worktree_lock_key",
    "worktree_registry_idx_principal",
    "worktree_registry_idx_repo",
    "worktree_registry_key",
]
