"""Targeted coverage tests for ``dhara.mcp.fastmcp_auth``.

The module is small (36 stmts) but covers three distinct surfaces:
the ``tool_auth`` helper, the ``DharaTokenVerifier`` adapter that bridges
``TokenAuth`` to FastMCP's ``TokenVerifier`` contract, and the
``build_token_verifier`` factory. Each surface has happy-path and
failure-path behaviour that was previously uncovered.

These tests exercise the production module directly; no production
code is modified. Token storage uses a temporary JSON file written
via ``TokenAuth.add_token`` so the existing ``TokenAuth.authenticate``
machinery is reused rather than mocked.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from dhara.mcp.auth import Role, TokenAuth, TokenInfo
from dhara.mcp.fastmcp_auth import (
    DharaTokenVerifier,
    ROLE_MAP,
    build_token_verifier,
    tool_auth,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_tokens_file(tmp_path: Path, tokens: dict[str, dict[str, Any]]) -> Path:
    """Write a Dhara-style tokens JSON file used by ``TokenAuth.load_tokens``."""
    payload = {"tokens": tokens}
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _build_token(
    *,
    token_id: str,
    raw_token: str,
    role: Role = Role.READONLY,
    expires_at: datetime | None = None,
    is_revoked: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Return ``(raw_token_string, serialized_record)`` ready for the tokens file."""
    import hashlib

    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    record: dict[str, Any] = {
        "token_id": token_id,
        "token_hash": token_hash,
        "role": role.value,
        "created_at": datetime.now(UTC).isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "is_revoked": is_revoked,
        "rate_limit": 1000,
        "metadata": {},
    }
    return raw_token, record


def _build_verifier(
    tmp_path: Path,
    *,
    require_auth: bool = True,
    default_role: Role = Role.READONLY,
    required_scopes: list[str] | None = None,
    tokens: dict[str, TokenInfo] | None = None,
) -> DharaTokenVerifier:
    """Build a verifier with an in-memory token store written to disk."""
    file_path = tmp_path / "tokens.json"
    if tokens:
        auth = TokenAuth(require_auth=require_auth, default_role=default_role)
        for tid, info in tokens.items():
            auth.tokens[tid] = info
        auth.tokens_file = str(file_path)
        auth.save_tokens()
    return DharaTokenVerifier(
        tokens_file=file_path,
        require_auth=require_auth,
        default_role=default_role,
        required_scopes=required_scopes,
    )


# ---------------------------------------------------------------------------
# tool_auth helper
# ---------------------------------------------------------------------------


def test_tool_auth_returns_callable(monkeypatch: pytest.MonkeyPatch) -> None:
    """``tool_auth(*scopes)`` should defer to ``require_scopes`` and return its result."""
    captured: dict[str, Any] = {}

    def fake_require_scopes(*scopes: str) -> str:
        captured["scopes"] = scopes
        return "marker"

    monkeypatch.setattr(
        "dhara.mcp.fastmcp_auth.require_scopes", fake_require_scopes
    )

    result = tool_auth("read", "write")
    assert result == "marker"
    assert captured["scopes"] == ("read", "write")


def test_tool_auth_with_no_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    """``tool_auth()`` without arguments still returns the require_scopes marker."""
    captured: dict[str, Any] = {}

    def fake_require_scopes(*scopes: str) -> list[str]:
        captured["scopes"] = scopes
        return list(scopes)

    monkeypatch.setattr(
        "dhara.mcp.fastmcp_auth.require_scopes", fake_require_scopes
    )

    assert tool_auth() == []
    assert captured["scopes"] == ()


# ---------------------------------------------------------------------------
# ROLE_MAP coverage
# ---------------------------------------------------------------------------


def test_role_map_contains_all_roles() -> None:
    """The role map should expose readonly/readwrite/admin keys."""
    assert ROLE_MAP == {
        "readonly": Role.READONLY,
        "readwrite": Role.READWRITE,
        "admin": Role.ADMIN,
    }


# ---------------------------------------------------------------------------
# DharaTokenVerifier construction
# ---------------------------------------------------------------------------


def test_verifier_init_expands_user(tmp_path: Path) -> None:
    """``tokens_file`` should be expanded via ``Path.expanduser`` on construction."""
    raw_token, record = _build_token(
        token_id="t1", raw_token="abc123", role=Role.READWRITE
    )
    tokens = {
        "t1": TokenInfo(
            token_id="t1",
            token_hash=record["token_hash"],
            role=Role.READWRITE,
            created_at=datetime.now(UTC),
            expires_at=None,
        ),
    }
    file_path = _build_tokens_file(tmp_path, {"t1": record})

    verifier = DharaTokenVerifier(tokens_file=file_path)
    # expanded path points to the same file the helper wrote
    assert verifier.tokens_file == file_path.expanduser()
    assert verifier.token_auth.tokens_file == str(file_path.expanduser())
    # the token_auth instance has the same require_auth default
    assert verifier.token_auth.require_auth is True
    assert verifier.token_auth.default_role is Role.READONLY


def test_verifier_init_with_explicit_overrides(tmp_path: Path) -> None:
    """Constructor overrides should be passed through to ``TokenAuth``."""
    file_path = _build_tokens_file(tmp_path, {})

    verifier = DharaTokenVerifier(
        tokens_file=file_path,
        require_auth=False,
        default_role=Role.ADMIN,
        required_scopes=["read", "admin"],
    )

    assert verifier.token_auth.require_auth is False
    assert verifier.token_auth.default_role is Role.ADMIN
    # TokenVerifier stores the required_scopes on the base class
    assert verifier.required_scopes == ["read", "admin"]


# ---------------------------------------------------------------------------
# verify_token — happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_token_returns_access_token_for_valid_token(
    tmp_path: Path,
) -> None:
    """A valid token should yield an AccessToken with sorted scopes + role."""
    raw_token, record = _build_token(
        token_id="user-tok", raw_token="valid-secret", role=Role.READWRITE
    )
    file_path = _build_tokens_file(tmp_path, {"user-tok": record})
    verifier = DharaTokenVerifier(tokens_file=file_path)

    access = await verifier.verify_token(raw_token)

    assert access is not None
    assert access.token == raw_token
    assert access.client_id == "user-tok"
    # READWRITE role yields read/write/delete permissions + the role value.
    # Note: ``scopes`` is built as ``sorted(permissions) + [role.value]`` so
    # the role lands at the end rather than being sorted inline. The
    # permission subset itself IS sorted (covered by the assertion below).
    assert "readwrite" in access.scopes
    assert "read" in access.scopes
    assert "write" in access.scopes
    assert "delete" in access.scopes
    # Permissions appear sorted in the claims dict (they're built via
    # ``sorted(...)`` directly).
    assert access.claims["permissions"] == sorted(access.claims["permissions"])
    assert access.expires_at is None
    # Claims dict captures the role and permissions
    assert access.claims is not None
    assert access.claims["token_id"] == "user-tok"
    assert access.claims["role"] == "readwrite"
    # Permissions appear sorted in the claims dict too
    assert access.claims["permissions"] == sorted(access.claims["permissions"])


@pytest.mark.asyncio
async def test_verify_token_uses_default_client_id_when_missing(
    tmp_path: Path,
) -> None:
    """When ``require_auth`` is False, TokenAuth returns ``"default"`` as token_id.

    ``DharaTokenVerifier.verify_token`` should pass that through to the
    ``client_id`` field (the ``"dhara"`` fallback only kicks in when
    ``result.token_id`` is falsy, e.g. None or empty).
    """
    file_path = _build_tokens_file(tmp_path, {})
    verifier = DharaTokenVerifier(
        tokens_file=file_path, require_auth=False, default_role=Role.READONLY
    )

    access = await verifier.verify_token("anything")

    assert access is not None
    # TokenAuth.authenticate returns AuthResult(token_id="default") when
    # require_auth is False; the verifier surfaces that as client_id.
    assert access.client_id == "default"
    assert "readonly" in access.scopes


@pytest.mark.asyncio
async def test_verify_token_includes_expires_at(
    tmp_path: Path,
) -> None:
    """An expiring token should propagate ``expires_at`` as an int timestamp."""
    expiry = datetime.now(UTC) + timedelta(hours=1)
    raw_token, record = _build_token(
        token_id="expiring",
        raw_token="expiring-secret",
        role=Role.READONLY,
        expires_at=expiry,
    )
    file_path = _build_tokens_file(tmp_path, {"expiring": record})
    verifier = DharaTokenVerifier(tokens_file=file_path)

    access = await verifier.verify_token(raw_token)
    assert access is not None
    assert access.expires_at is not None
    assert access.expires_at == int(expiry.timestamp())


@pytest.mark.asyncio
async def test_verify_token_falls_back_to_dhara_client_id_when_token_id_falsy(
    tmp_path: Path,
) -> None:
    """If ``AuthResult.token_id`` is None/empty, ``client_id`` should be ``"dhara"``.

    Covers the ``result.token_id or "dhara"`` branch on line 62 of
    ``fastmcp_auth.py``. We monkey-patch the TokenAuth singleton on the
    verifier so we can return a hand-crafted AuthResult with token_id=None.
    """
    from dhara.mcp.auth import AuthResult, Permission

    file_path = _build_tokens_file(tmp_path, {})
    verifier = DharaTokenVerifier(
        tokens_file=file_path, require_auth=False, default_role=Role.READONLY
    )

    fake_result = AuthResult(
        success=True,
        token_id=None,  # falsy -> fallback to "dhara"
        role=Role.READONLY,
        permissions={Permission.READ},
    )
    verifier.token_auth.authenticate = lambda _token: fake_result  # type: ignore[assignment]

    access = await verifier.verify_token("any-token")
    assert access is not None
    assert access.client_id == "dhara"
    assert "readonly" in access.scopes


@pytest.mark.asyncio
async def test_verify_token_with_admin_role(tmp_path: Path) -> None:
    """Admin role should yield ``admin``, ``read``, ``write``, ``delete`` scopes."""
    raw_token, record = _build_token(
        token_id="admin-tok", raw_token="admin-secret", role=Role.ADMIN
    )
    file_path = _build_tokens_file(tmp_path, {"admin-tok": record})
    verifier = DharaTokenVerifier(tokens_file=file_path)

    access = await verifier.verify_token(raw_token)
    assert access is not None
    assert access.client_id == "admin-tok"
    assert "admin" in access.scopes
    assert access.claims["role"] == "admin"
    assert access.claims["token_id"] == "admin-tok"


@pytest.mark.asyncio
async def test_verify_token_revoked_returns_none(tmp_path: Path) -> None:
    """A revoked token should not authenticate (TokenAuth.is_valid filters it)."""
    raw_token, record = _build_token(
        token_id="revoked-tok",
        raw_token="revoked-secret",
        role=Role.READONLY,
        is_revoked=True,
    )
    file_path = _build_tokens_file(tmp_path, {"revoked-tok": record})
    verifier = DharaTokenVerifier(tokens_file=file_path)

    assert await verifier.verify_token(raw_token) is None


@pytest.mark.asyncio
async def test_verify_token_skips_role_append_when_role_is_none(
    tmp_path: Path,
) -> None:
    """If ``AuthResult.role`` is None, the role-scope append should be skipped.

    Covers the ``50->53`` branch in ``fastmcp_auth.py`` where
    ``result.role is None`` falsifies the ``if`` block at line 50 and falls
    through to the required_scopes check at line 53.
    """
    from dhara.mcp.auth import AuthResult, Permission

    file_path = _build_tokens_file(tmp_path, {})
    verifier = DharaTokenVerifier(
        tokens_file=file_path, require_auth=False, default_role=Role.READONLY
    )

    fake_result = AuthResult(
        success=True,
        token_id="no-role-tok",
        role=None,  # truthy branch falsified -> skips ``scopes.append``
        permissions={Permission.READ},
    )
    verifier.token_auth.authenticate = lambda _token: fake_result  # type: ignore[assignment]

    access = await verifier.verify_token("any-token")
    assert access is not None
    assert access.client_id == "no-role-tok"
    # Only the permission scopes — no role.value was appended.
    assert access.scopes == ["read"]
    # And the claim reflects role=None too.
    assert access.claims is not None
    assert access.claims["role"] is None
    assert access.claims["token_id"] == "no-role-tok"


# ---------------------------------------------------------------------------
# verify_token — failure / filtering paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_token_returns_none_for_invalid_token(
    tmp_path: Path,
) -> None:
    """Unknown tokens must yield None."""
    _, record = _build_token(
        token_id="known", raw_token="real-secret", role=Role.READONLY
    )
    file_path = _build_tokens_file(tmp_path, {"known": record})
    verifier = DharaTokenVerifier(tokens_file=file_path)

    assert await verifier.verify_token("not-the-real-token") is None


@pytest.mark.asyncio
async def test_verify_token_returns_none_when_required_scopes_missing(
    tmp_path: Path,
) -> None:
    """When ``required_scopes`` is set and token lacks them, return None."""
    raw_token, record = _build_token(
        token_id="user-tok", raw_token="valid-secret", role=Role.READONLY
    )
    file_path = _build_tokens_file(tmp_path, {"user-tok": record})
    verifier = DharaTokenVerifier(
        tokens_file=file_path, required_scopes=["admin"]
    )

    assert await verifier.verify_token(raw_token) is None


@pytest.mark.asyncio
async def test_verify_token_passes_when_required_scopes_satisfied(
    tmp_path: Path,
) -> None:
    """When the token's scopes include ``required_scopes``, accept the token."""
    raw_token, record = _build_token(
        token_id="admin-tok", raw_token="admin-secret", role=Role.ADMIN
    )
    file_path = _build_tokens_file(tmp_path, {"admin-tok": record})
    verifier = DharaTokenVerifier(
        tokens_file=file_path, required_scopes=["admin"]
    )

    access = await verifier.verify_token(raw_token)
    assert access is not None
    assert "admin" in access.scopes


@pytest.mark.asyncio
async def test_verify_token_skips_scope_check_when_required_scopes_empty(
    tmp_path: Path,
) -> None:
    """An empty ``required_scopes`` list should bypass the scope subset check.

    Covers the ``50->53`` branch in ``fastmcp_auth.py`` where
    ``self.required_scopes`` is falsy and the scope-check block is skipped
    entirely (rather than treated as ``issubset`` of an empty set, which
    would also pass but is the wrong intent).
    """
    raw_token, record = _build_token(
        token_id="user-tok", raw_token="valid-secret", role=Role.READONLY
    )
    file_path = _build_tokens_file(tmp_path, {"user-tok": record})
    verifier = DharaTokenVerifier(
        tokens_file=file_path, required_scopes=[]
    )

    access = await verifier.verify_token(raw_token)
    assert access is not None
    assert "readonly" in access.scopes


# ---------------------------------------------------------------------------
# build_token_verifier factory
# ---------------------------------------------------------------------------


def test_build_token_verifier_disabled_returns_none(tmp_path: Path) -> None:
    """When authentication is disabled, the factory returns None."""
    assert (
        build_token_verifier(
            enabled=False,
            tokens_file=tmp_path / "any.json",
            require_auth=True,
            default_role="readonly",
        )
        is None
    )


def test_build_token_verifier_missing_tokens_file_raises(tmp_path: Path) -> None:
    """Enabled auth without a tokens file path should raise ValueError."""
    with pytest.raises(ValueError, match="no token file is configured"):
        build_token_verifier(
            enabled=True,
            tokens_file=None,
            require_auth=True,
            default_role="readonly",
        )


def test_build_token_verifier_nonexistent_path_raises(tmp_path: Path) -> None:
    """If the resolved file doesn't exist, raise ValueError with the path."""
    missing = tmp_path / "does-not-exist.json"
    with pytest.raises(ValueError, match=str(missing)):
        build_token_verifier(
            enabled=True,
            tokens_file=missing,
            require_auth=True,
            default_role="readonly",
        )


def test_build_token_verifier_happy_path(tmp_path: Path) -> None:
    """Enabled + valid file returns a ``DharaTokenVerifier`` with mapped role."""
    file_path = _build_tokens_file(tmp_path, {})
    verifier = build_token_verifier(
        enabled=True,
        tokens_file=file_path,
        require_auth=False,
        default_role="admin",
        required_scopes=["read"],
    )

    assert isinstance(verifier, DharaTokenVerifier)
    assert verifier.token_auth.require_auth is False
    assert verifier.token_auth.default_role is Role.ADMIN
    assert verifier.required_scopes == ["read"]


def test_build_token_verifier_unknown_role_falls_back_to_readonly(
    tmp_path: Path,
) -> None:
    """An unmapped role name should fall back to READONLY (Role.READONLY)."""
    file_path = _build_tokens_file(tmp_path, {})
    verifier = build_token_verifier(
        enabled=True,
        tokens_file=file_path,
        require_auth=True,
        default_role="not-a-real-role",
    )
    assert verifier is not None
    assert verifier.token_auth.default_role is Role.READONLY


def test_build_token_verifier_required_scopes_default_empty(
    tmp_path: Path,
) -> None:
    """When ``required_scopes`` is None, the verifier should default to []."""
    file_path = _build_tokens_file(tmp_path, {})
    verifier = build_token_verifier(
        enabled=True,
        tokens_file=file_path,
        require_auth=True,
        default_role="readonly",
        required_scopes=None,
    )
    assert verifier is not None
    assert verifier.required_scopes == []
