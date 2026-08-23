"""Tests for dhara/mcp/worktree_registry.py — keyspace + serialization (ADR 015 v4 §11)."""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime

import pytest

from dhara.mcp import worktree_registry as wr
from dhara.mcp.kv_timeseries import AsyncKVTimeSeriesStore


# ----- keyspace tests -------------------------------------------------------


def test_worktree_registry_key_uses_mahavishnu_prefix() -> None:
    assert wr.worktree_registry_key("abc").startswith("mahavishnu:")
    assert wr.worktree_registry_key("abc") == "mahavishnu:worktree-registry:abc"


def test_secondary_indexes_have_consistent_prefix() -> None:
    p = wr.worktree_registry_idx_principal("alice")
    r = wr.worktree_registry_idx_repo("mahavishnu")
    assert p == "mahavishnu:worktree-registry:idx:principal:alice"
    assert r == "mahavishnu:worktree-registry:idx:repo:mahavishnu"


def test_lock_key_includes_principal_repo_branch() -> None:
    k = wr.worktree_lock_key("uid:1000", "mahavishnu", "feature/auth")
    assert k == "mahavishnu:worktree-registry:lock:uid:1000:mahavishnu:feature/auth"


def test_audit_log_key_normalizes_date_to_utc_yyyy_mm_dd() -> None:
    pst = datetime(2026, 8, 23, 12, 0, 0, tzinfo=__import__("datetime").timezone(__import__("datetime").timedelta(hours=-7)))
    k = wr.audit_log_key(pst, "handle-1", 7)
    assert k == "mahavishnu:audit-log:2026-08-23:handle-1:7"


def test_audit_log_index_keys_use_date_partition() -> None:
    pst = datetime(2026, 8, 23, 12, 0, 0, tzinfo=__import__("datetime").timezone(__import__("datetime").timedelta(hours=-7)))
    assert wr.audit_log_idx_handle("h-1") == "mahavishnu:audit-log-idx:handle:h-1"
    assert wr.audit_log_idx_date(pst) == "mahavishnu:audit-log-idx:date:2026-08-23"


def test_cache_key_scopes_to_handle() -> None:
    assert (
        wr.worktree_cache_key("handle-1", "mycroft:counter:42")
        == "mahavishnu:worktree-cache:handle-1:mycroft:counter:42"
    )


# ----- Principal + AuditEvent serialization ---------------------------------


def test_principal_from_uid_uses_default_name() -> None:
    p = wr.Principal.from_uid(1000)
    assert p.uid == 1000
    assert p.name == "uid:1000"


def test_principal_anonymous_has_no_uid() -> None:
    p = wr.Principal.anonymous()
    assert p.uid is None
    assert p.name == "anonymous"
    assert p.is_anonymous is True  # type: ignore[attr-defined]


def test_principal_serialization_roundtrip() -> None:
    p = wr.Principal(uid=42, name="alice", scopes=["worktree:create"], cleanup_policy_override="keep")
    d = wr.serialize_principal(p)
    assert d == {
        "uid": 42,
        "name": "alice",
        "scopes": ["worktree:create"],
        "cleanup_policy_override": "keep",
    }
    p2 = wr.deserialize_principal(d)
    assert p2 == p


def test_audit_event_serialization_roundtrip() -> None:
    p = wr.Principal.from_uid(7)
    e = wr.AuditEvent(
        event_id=uuid.uuid4().hex,
        event_type="worktree.created",
        principal=p,
        handle_id="h-1",
        payload={"repo": "mahavishnu", "branch": "feature/auth"},
        timestamp=datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC),
        trace_id="trace-1",
    )
    blob = wr.serialize_audit_event(e)
    # JSON-encoded bytes
    assert isinstance(blob, bytes)
    parsed = json.loads(blob.decode("utf-8"))
    assert parsed["event_type"] == "worktree.created"
    assert parsed["principal"]["uid"] == 7
    e2 = wr.deserialize_audit_event(blob)
    assert e2.event_id == e.event_id
    assert e2.timestamp == e.timestamp
    assert e2.principal == e.principal
    assert e2.payload == e.payload
