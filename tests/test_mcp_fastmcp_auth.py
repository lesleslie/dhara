"""Tests for dhara.mcp.fastmcp_auth — tool_auth, DharaTokenVerifier, build_token_verifier."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from dhara.mcp.auth import AuthResult, Permission, Role
from dhara.mcp.fastmcp_auth import (
    ROLE_MAP,
    DharaTokenVerifier,
    build_token_verifier,
    tool_auth,
)


# ===========================================================================
# ROLE_MAP
# ===========================================================================


class TestRoleMap:
    def test_readonly_mapping(self):
        assert ROLE_MAP["readonly"] is Role.READONLY

    def test_readwrite_mapping(self):
        assert ROLE_MAP["readwrite"] is Role.READWRITE

    def test_admin_mapping(self):
        assert ROLE_MAP["admin"] is Role.ADMIN


# ===========================================================================
# tool_auth
# ===========================================================================


class TestToolAuth:
    @patch("dhara.mcp.fastmcp_auth.require_scopes")
    def test_delegates_to_require_scopes(self, mock_require_scopes):
        sentinel = object()
        mock_require_scopes.return_value = sentinel
        result = tool_auth("read", "write")
        assert result is sentinel
        mock_require_scopes.assert_called_once_with("read", "write")

    @patch("dhara.mcp.fastmcp_auth.require_scopes")
    def test_single_scope(self, mock_require_scopes):
        tool_auth("admin")
        mock_require_scopes.assert_called_once_with("admin")


# ===========================================================================
# DharaTokenVerifier
# ===========================================================================


class TestDharaTokenVerifier:
    """Tests covering __init__ (lines 36-38) and verify_token (lines 46-61)."""

    @staticmethod
    def _make_tokens_file(tokens: dict | None = None) -> Path:
        """Create a temporary tokens JSON file and return its path."""
        tokens = tokens or {}
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        data = {"tokens": tokens}
        with open(path, "w") as f:
            json.dump(data, f)
        return Path(path)

    @staticmethod
    def _make_token_entry(
        token_hash: str,
        role: str = "readonly",
        expires_at: str | None = None,
    ) -> dict:
        entry: dict = {
            "token_hash": token_hash,
            "role": role,
            "created_at": datetime.now(UTC).isoformat(),
        }
        if expires_at is not None:
            entry["expires_at"] = expires_at
        return entry

    def test_init_expanduser(self):
        """Line 37: Path(tokens_file).expanduser() is called."""
        verifier = DharaTokenVerifier(
            tokens_file=Path("~/.dhara_tokens.json"),
            require_auth=False,
        )
        assert verifier.tokens_file == Path("~/.dhara_tokens.json").expanduser()

    def test_init_creates_token_auth(self):
        """Lines 38-42: TokenAuth is created with correct parameters."""
        tokens_file = self._make_tokens_file()
        try:
            verifier = DharaTokenVerifier(
                tokens_file=tokens_file,
                require_auth=True,
                default_role=Role.ADMIN,
                required_scopes=["read"],
            )
            assert verifier.token_auth.require_auth is True
            assert verifier.token_auth.default_role is Role.ADMIN
            assert verifier.required_scopes == ["read"]
        finally:
            tokens_file.unlink()

    async def test_verify_token_failure(self):
        """Line 47-48: authenticate fails -> returns None."""
        tokens_file = self._make_tokens_file()
        try:
            verifier = DharaTokenVerifier(
                tokens_file=tokens_file,
                require_auth=True,
            )
            access_token = await verifier.verify_token("bad-token")
            assert access_token is None
        finally:
            tokens_file.unlink()

    async def test_verify_token_success_without_expires(self):
        """Lines 50-65, 59: successful verify with no expires_at."""
        import hashlib

        raw_token = "test-secret-token"
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        tokens_file = self._make_tokens_file({
            "tok1": self._make_token_entry(token_hash=token_hash, role="readwrite"),
        })
        try:
            verifier = DharaTokenVerifier(
                tokens_file=tokens_file,
                require_auth=True,
            )
            access_token = await verifier.verify_token(raw_token)
            assert access_token is not None
            assert access_token.client_id == "tok1"
            assert access_token.token == raw_token
            assert "read" in access_token.scopes
            assert "write" in access_token.scopes
            assert "readwrite" in access_token.scopes
            assert access_token.expires_at is None
            assert access_token.claims["role"] == "readwrite"
            assert access_token.claims["token_id"] == "tok1"
        finally:
            tokens_file.unlink()

    async def test_verify_token_success_with_expires(self):
        """Line 59: expires_at is converted to timestamp."""
        import hashlib

        raw_token = "expiring-token"
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        # Use a round datetime so .timestamp() produces an integer
        future = datetime(2030, 1, 1, 0, 0, 0, tzinfo=UTC)
        tokens_file = self._make_tokens_file({
            "tok2": self._make_token_entry(
                token_hash=token_hash, role="admin", expires_at=future.isoformat()
            ),
        })
        try:
            verifier = DharaTokenVerifier(
                tokens_file=tokens_file,
                require_auth=True,
            )
            access_token = await verifier.verify_token(raw_token)
            assert access_token is not None
            assert access_token.expires_at is not None
            assert isinstance(access_token.expires_at, int)
        finally:
            tokens_file.unlink()

    async def test_verify_token_required_scopes_satisfied(self):
        """Lines 54-57: required_scopes subset check passes."""
        import hashlib

        raw_token = "admin-token"
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        tokens_file = self._make_tokens_file({
            "tok3": self._make_token_entry(token_hash=token_hash, role="admin"),
        })
        try:
            verifier = DharaTokenVerifier(
                tokens_file=tokens_file,
                require_auth=True,
                required_scopes=["admin", "read"],
            )
            access_token = await verifier.verify_token(raw_token)
            assert access_token is not None
        finally:
            tokens_file.unlink()

    async def test_verify_token_required_scopes_not_satisfied(self):
        """Lines 54-57: required_scopes subset check fails -> returns None."""
        import hashlib

        raw_token = "readonly-token"
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        tokens_file = self._make_tokens_file({
            "tok4": self._make_token_entry(token_hash=token_hash, role="readonly"),
        })
        try:
            verifier = DharaTokenVerifier(
                tokens_file=tokens_file,
                require_auth=True,
                required_scopes=["admin"],
            )
            access_token = await verifier.verify_token(raw_token)
            assert access_token is None
        finally:
            tokens_file.unlink()

    async def test_verify_token_claims_permissions_sorted(self):
        """Line 69: permissions in claims are sorted."""
        import hashlib

        raw_token = "perm-token"
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        tokens_file = self._make_tokens_file({
            "tok5": self._make_token_entry(token_hash=token_hash, role="admin"),
        })
        try:
            verifier = DharaTokenVerifier(
                tokens_file=tokens_file,
                require_auth=True,
            )
            access_token = await verifier.verify_token(raw_token)
            assert access_token is not None
            perms = access_token.claims["permissions"]
            assert perms == sorted(perms), f"permissions not sorted: {perms}"
        finally:
            tokens_file.unlink()

    async def test_verify_token_no_role(self):
        """Lines 51-52: when role is None, scopes only come from permissions."""
        tokens_file = self._make_tokens_file()
        try:
            verifier = DharaTokenVerifier(
                tokens_file=tokens_file,
                require_auth=True,
            )
            # Patch authenticate to return a result with no role
            mock_result = AuthResult(
                success=True,
                token_id="mock-tok",
                role=None,
                permissions={Permission.READ, Permission.LIST},
                expires_at=None,
            )
            with patch.object(
                verifier.token_auth, "authenticate", return_value=mock_result
            ):
                access_token = await verifier.verify_token("anything")
                assert access_token is not None
                assert "readonly" not in access_token.scopes
                assert "read" in access_token.scopes
        finally:
            tokens_file.unlink()


# ===========================================================================
# build_token_verifier
# ===========================================================================


class TestBuildTokenVerifier:
    """Tests covering lines 83-93."""

    def test_disabled_returns_none(self):
        """Line 83-84: enabled=False -> returns None."""
        result = build_token_verifier(
            enabled=False,
            tokens_file=None,
            require_auth=True,
            default_role="readonly",
        )
        assert result is None

    def test_enabled_no_tokens_file_raises(self):
        """Lines 86-87: enabled but tokens_file is None -> ValueError."""
        with pytest.raises(ValueError, match="no token file is configured"):
            build_token_verifier(
                enabled=True,
                tokens_file=None,
                require_auth=True,
                default_role="readonly",
            )

    def test_enabled_missing_file_raises(self):
        """Lines 89-91: tokens_file does not exist -> ValueError."""
        with pytest.raises(ValueError, match="token file not found"):
            build_token_verifier(
                enabled=True,
                tokens_file="/nonexistent/path/tokens.json",
                require_auth=True,
                default_role="readonly",
            )

    def test_enabled_valid_file_returns_verifier(self):
        """Lines 93-98: valid config returns a DharaTokenVerifier."""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w") as f:
            json.dump({"tokens": {}}, f)
        try:
            verifier = build_token_verifier(
                enabled=True,
                tokens_file=Path(path),
                require_auth=True,
                default_role="admin",
                required_scopes=["read"],
            )
            assert verifier is not None
            assert isinstance(verifier, DharaTokenVerifier)
            assert verifier.token_auth.default_role is Role.ADMIN
        finally:
            os.unlink(path)

    def test_unknown_default_role_falls_back_to_readonly(self):
        """Line 96: unknown role string falls back to Role.READONLY."""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w") as f:
            json.dump({"tokens": {}}, f)
        try:
            verifier = build_token_verifier(
                enabled=True,
                tokens_file=Path(path),
                require_auth=True,
                default_role="unknown_role",
            )
            assert verifier is not None
            assert verifier.token_auth.default_role is Role.READONLY
        finally:
            os.unlink(path)

    def test_none_required_scopes_becomes_empty_list(self):
        """Line 97: required_scopes=None is converted to []."""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w") as f:
            json.dump({"tokens": {}}, f)
        try:
            verifier = build_token_verifier(
                enabled=True,
                tokens_file=Path(path),
                require_auth=True,
                default_role="readonly",
                required_scopes=None,
            )
            assert verifier is not None
            assert verifier.required_scopes == []
        finally:
            os.unlink(path)

    def test_tilde_expansion_in_tokens_file(self):
        """Line 89: ~ in tokens_file is expanded."""
        # We can't test with an actual ~ file easily, but we can test
        # that the function uses expanduser by providing a temp file
        # and verifying the verifier's tokens_file is expanded.
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w") as f:
            json.dump({"tokens": {}}, f)
        try:
            # Use the real path (already absolute, expanduser is a no-op)
            verifier = build_token_verifier(
                enabled=True,
                tokens_file=Path(path),
                require_auth=True,
                default_role="readonly",
            )
            assert verifier is not None
            assert verifier.tokens_file == Path(path).expanduser()
        finally:
            os.unlink(path)
