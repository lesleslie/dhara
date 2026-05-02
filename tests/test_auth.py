"""Tests for dhara/mcp/auth.py — authentication, roles, tokens."""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from dhara.mcp.auth import (
    AuthContext,
    AuthMiddleware,
    AuthResult,
    EnvironmentAuth,
    HMACAuth,
    Permission,
    Role,
    TokenAuth,
    TokenInfo,
    _as_utc,
    _utcnow,
    generate_api_token,
    generate_token,
)


class TestPermission:
    def test_all_permissions(self):
        perms = Permission.all_permissions()
        assert Permission.READ in perms
        assert Permission.ADMIN in perms

    def test_read_permissions(self):
        perms = Permission.read_permissions()
        assert Permission.READ in perms
        assert Permission.WRITE not in perms

    def test_write_permissions_includes_read(self):
        perms = Permission.write_permissions()
        assert Permission.READ in perms
        assert Permission.WRITE in perms

    def test_admin_equals_all(self):
        assert Role.ADMIN.get_permissions() == Permission.all_permissions()


class TestRole:
    def test_readonly(self):
        perms = Role.READONLY.get_permissions()
        assert Permission.READ in perms
        assert Permission.WRITE not in perms

    def test_readwrite(self):
        perms = Role.READWRITE.get_permissions()
        assert Permission.READ in perms
        assert Permission.WRITE in perms

    def test_admin(self):
        perms = Role.ADMIN.get_permissions()
        assert Permission.ADMIN in perms


class TestAuthResult:
    def test_has_permission(self):
        r = AuthResult(success=True, permissions={Permission.READ, Permission.WRITE})
        assert r.has_permission(Permission.READ)
        assert not r.has_permission(Permission.ADMIN)

    def test_expired(self):
        r = AuthResult(success=True, expires_at=_utcnow() - timedelta(hours=1))
        assert r.expires_at is not None


class TestTokenInfo:
    def test_is_valid_fresh(self):
        info = TokenInfo(
            token_id="t1",
            token_hash="h",
            role=Role.READONLY,
            created_at=_utcnow(),
        )
        assert info.is_valid()

    def test_is_revoked(self):
        info = TokenInfo(
            token_id="t1",
            token_hash="h",
            role=Role.READONLY,
            created_at=_utcnow(),
            is_revoked=True,
        )
        assert not info.is_valid()

    def test_is_expired(self):
        info = TokenInfo(
            token_id="t1",
            token_hash="h",
            role=Role.READONLY,
            created_at=_utcnow(),
            expires_at=_utcnow() - timedelta(hours=1),
        )
        assert info.is_expired()
        assert not info.is_valid()

    def test_no_expiry_is_valid(self):
        info = TokenInfo(
            token_id="t1",
            token_hash="h",
            role=Role.READONLY,
            created_at=_utcnow(),
            expires_at=None,
        )
        assert not info.is_expired()


class TestTokenAuth:
    def test_authenticate_success(self):
        ta = TokenAuth(require_auth=False)
        result = ta.authenticate("anything")
        assert result.success

    def test_authenticate_with_token(self):
        ta = TokenAuth(require_auth=True)
        ta.add_token("mytok", "secret123", role=Role.ADMIN)
        result = ta.authenticate("secret123")
        assert result.success
        assert result.token_id == "mytok"
        assert result.role == Role.ADMIN

    def test_authenticate_wrong_token(self):
        ta = TokenAuth(require_auth=True)
        ta.add_token("mytok", "secret123")
        result = ta.authenticate("wrong")
        assert not result.success

    def test_revoke_token(self):
        ta = TokenAuth(require_auth=True)
        ta.add_token("mytok", "secret123")
        assert ta.revoke_token("mytok")
        result = ta.authenticate("secret123")
        assert not result.success

    def test_revoke_nonexistent(self):
        ta = TokenAuth()
        assert not ta.revoke_token("nope")

    def test_add_token_with_expiry(self):
        ta = TokenAuth()
        info = ta.add_token("t1", "val", expires_in=3600)
        assert info.expires_at is not None

    def test_expired_token_fails(self):
        ta = TokenAuth(require_auth=True)
        info = TokenInfo(
            token_id="t1",
            token_hash=ta._hash_token("old"),
            role=Role.READONLY,
            created_at=_utcnow() - timedelta(days=2),
            expires_at=_utcnow() - timedelta(hours=1),
        )
        ta.tokens["t1"] = info
        result = ta.authenticate("old")
        assert not result.success

    def test_rate_limit_check(self):
        ta = TokenAuth(require_auth=True)
        ta.add_token("t1", "v", rate_limit=2)
        loop = asyncio.get_event_loop()
        assert loop.run_until_complete(ta.check_rate_limit("t1"))
        assert loop.run_until_complete(ta.check_rate_limit("t1"))
        assert not loop.run_until_complete(ta.check_rate_limit("t1"))

    def test_unknown_token_no_rate_limit(self):
        ta = TokenAuth()
        loop = asyncio.get_event_loop()
        assert loop.run_until_complete(ta.check_rate_limit("unknown"))

    def test_save_and_load_tokens(self, tmp_path):
        filepath = str(tmp_path / "tokens.json")
        ta = TokenAuth(require_auth=True)
        ta.add_token("t1", "secret", role=Role.ADMIN)
        ta.save_tokens(filepath)

        ta2 = TokenAuth(require_auth=True, tokens_file=filepath)
        assert "t1" in ta2.tokens
        assert ta2.tokens["t1"].role == Role.ADMIN

    def test_load_empty_file(self, tmp_path):
        filepath = str(tmp_path / "tokens.json")
        with open(filepath, "w") as f:
            f.write("")
        ta = TokenAuth(tokens_file=filepath)
        assert len(ta.tokens) == 0


class TestHMACAuth:
    def test_not_required(self):
        ha = HMACAuth(require_auth=False)
        result = ha.authenticate("", "", "", "c1")
        assert result.success

    def test_generate_and_verify(self):
        secret = "mysecret"
        payload = '{"test": 1}'
        timestamp = "1234567890"
        sig = HMACAuth().generate_signature(payload, secret, timestamp)
        ha = HMACAuth(require_auth=True, secrets={"c1": secret})
        assert ha.verify_signature(payload, sig, timestamp, "c1")

    def test_wrong_signature(self):
        ha = HMACAuth(require_auth=True, secrets={"c1": "secret"})
        assert not ha.verify_signature("payload", "badsig", "ts", "c1")

    def test_unknown_client(self):
        ha = HMACAuth(require_auth=True)
        assert not ha.verify_signature("p", "sig", "ts", "unknown")


class TestEnvironmentAuth:
    def test_not_required_no_env(self, monkeypatch):
        monkeypatch.delenv("DURUS_AUTH_TOKEN", raising=False)
        ea = EnvironmentAuth(require_auth=False)
        result = ea.authenticate()
        assert result.success

    def test_with_matching_env(self, monkeypatch):
        monkeypatch.setenv("DURUS_AUTH_TOKEN", "tok123")
        ea = EnvironmentAuth(require_auth=True)
        result = ea.authenticate("tok123")
        assert result.success

    def test_wrong_token_required(self, monkeypatch):
        monkeypatch.setenv("DURUS_AUTH_TOKEN", "real")
        ea = EnvironmentAuth(require_auth=True)
        result = ea.authenticate("wrong")
        assert not result.success


class TestAuthMiddleware:
    def test_no_auth_required(self):
        mw = AuthMiddleware(require_auth=False)
        ctx = AuthContext()
        result = mw.authenticate(ctx)
        assert result.success

    def test_token_auth_success(self):
        ta = TokenAuth(require_auth=True)
        ta.add_token("t1", "secret", role=Role.ADMIN)
        mw = AuthMiddleware(token_auth=ta, require_auth=True)
        ctx = AuthContext(token="secret")
        result = mw.authenticate(ctx)
        assert result.success
        assert result.role == Role.ADMIN

    def test_env_fallback(self, monkeypatch):
        monkeypatch.setenv("DURUS_AUTH_TOKEN", "tok")
        ea = EnvironmentAuth(require_auth=False)
        mw = AuthMiddleware(env_auth=ea, require_auth=True)
        result = mw.authenticate(AuthContext(token="tok"))
        assert result.success

    def test_check_permission(self):
        mw = AuthMiddleware(require_auth=False)
        auth = AuthResult(success=True, permissions={Permission.READ})
        assert mw.check_permission(auth, Permission.READ)
        assert not mw.check_permission(auth, Permission.ADMIN)

    def test_check_permission_failed_auth(self):
        mw = AuthMiddleware(require_auth=False)
        auth = AuthResult(success=False)
        assert not mw.check_permission(auth, Permission.READ)


class TestGenerateToken:
    def test_generate_token_length(self):
        tok = generate_token(16)
        assert len(tok) == 32  # hex encoding doubles byte length

    def test_generate_api_token(self):
        tok, tok_hash = generate_api_token("my-id", "admin")
        assert len(tok) > 0
        assert len(tok_hash) == 64  # SHA-256 hex


class TestAsUtc:
    def test_naive_becomes_utc(self):
        dt = datetime(2025, 1, 1)
        result = _as_utc(dt)
        assert result.tzinfo == timezone.utc

    def test_already_utc(self):
        dt = datetime(2025, 1, 1, tzinfo=timezone.utc)
        assert _as_utc(dt) == dt
