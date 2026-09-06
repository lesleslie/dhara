"""Extended coverage tests for dhara.mcp.auth.

Production module is FROZEN — only tests are added here.
Targets 349 stmts from 27% baseline to >=95%.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from base64 import b64encode
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Pre-import shims: break beartype/pydantic.root_model race that breaks collection
# ---------------------------------------------------------------------------
import beartype.claw._clawstate  # noqa: F401
import pydantic.root_model as _pyd_root  # noqa: F401
import sys as _sys
_sys.modules.setdefault("pydantic.root_model", _pyd_root)

from mcp_common.auth.core import TokenPayload
from mcp_common.auth.exceptions import AuthError
from mcp_common.auth.permissions import Permission
from oneiric.actions.security import SecuritySecureAction, SecuritySecureSettings

from dhara.mcp import auth as auth_module
from dhara.mcp.auth import (
    AuthContext,
    AuthMiddleware,
    AuthResult,
    DharaPermission,
    EnvironmentAuth,
    HMACAuth,
    Role,
    TokenAuth,
    TokenInfo,
    _as_utc,
    _audit,
    _block_on_running_loop,
    _get_config,
    _permission_all_permissions,
    _permission_read_permissions,
    _permission_write_permissions,
    _reset_config,
    _secure_token_action,
    _utcnow,
    generate_api_token,
    generate_token,
    require_dhara_auth,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_token_payload(
    *,
    issuer: str = "test-issuer",
    subject: str = "test-subject",
    jti: str = "test-jti",
    permissions: frozenset[Permission] = frozenset({Permission.READ}),
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
    audience: str = "dhara",
    raw: dict[str, Any] | None = None,
) -> TokenPayload:
    return TokenPayload(
        issuer=issuer,
        audience=audience,
        subject=subject,
        jti=jti,
        permissions=permissions,
        issued_at=issued_at or datetime.now(UTC),
        expires_at=expires_at or (datetime.now(UTC) + timedelta(hours=1)),
        raw=raw or {},
    )


@pytest.fixture(autouse=True)
def _reset_auth_state():
    """Reset module-level config singleton between tests."""
    _reset_config()
    yield
    _reset_config()


@pytest.fixture
def tmp_token_file(tmp_path: Path) -> Path:
    return tmp_path / "tokens.json"


# ---------------------------------------------------------------------------
# Module-level helpers: _utcnow / _as_utc
# ---------------------------------------------------------------------------


class TestDatetimeHelpers:
    def test_utcnow_returns_aware_utc(self) -> None:
        result = _utcnow()
        assert isinstance(result, datetime)
        assert result.tzinfo is UTC

    def test_as_utc_normalizes_naive_datetime(self) -> None:
        naive = datetime(2025, 1, 1, 12, 0, 0)
        normalized = _as_utc(naive)
        assert normalized.tzinfo is UTC
        assert normalized.year == 2025 and normalized.hour == 12

    def test_as_utc_converts_other_timezone(self) -> None:
        from datetime import timezone, timedelta as td

        other_tz = timezone(td(hours=5))
        aware = datetime(2025, 6, 1, 10, 0, 0, tzinfo=other_tz)
        normalized = _as_utc(aware)
        assert normalized.tzinfo is UTC
        # 10:00 +05:00 == 05:00 UTC
        assert normalized.hour == 5


# ---------------------------------------------------------------------------
# _get_config / _reset_config singleton behavior
# ---------------------------------------------------------------------------


class TestConfigSingleton:
    def test_get_config_returns_singleton(self) -> None:
        a = _get_config()
        b = _get_config()
        assert a is b

    def test_reset_config_clears_cache(self) -> None:
        a = _get_config()
        _reset_config()
        b = _get_config()
        assert a is not b

    def test_config_defaults_to_disabled(self) -> None:
        cfg = _get_config()
        assert cfg.enabled is False
        assert cfg.service_name == "dhara"


# ---------------------------------------------------------------------------
# DharaPermission enum
# ---------------------------------------------------------------------------


class TestDharaPermission:
    def test_members(self) -> None:
        assert DharaPermission.CHECKPOINT.value == "checkpoint"
        assert DharaPermission.RESTORE.value == "restore"


# ---------------------------------------------------------------------------
# Permission classmethod shims
# ---------------------------------------------------------------------------


class TestPermissionShims:
    def test_all_permissions(self) -> None:
        all_perms = Permission.all_permissions()
        assert Permission.READ in all_perms
        assert Permission.WRITE in all_perms
        assert Permission.ADMIN in all_perms

    def test_read_permissions(self) -> None:
        assert Permission.read_permissions() == {Permission.READ}

    def test_write_permissions(self) -> None:
        assert Permission.write_permissions() == {Permission.READ, Permission.WRITE}

    def test_permission_aliases(self) -> None:
        assert Permission.LIST is Permission.READ
        assert Permission.CHECKPOINT is Permission.ADMIN
        assert Permission.RESTORE is Permission.ADMIN

    def test_helper_callables_return_sets(self) -> None:
        assert isinstance(_permission_all_permissions(Permission), set)
        assert isinstance(_permission_read_permissions(Permission), set)
        assert isinstance(_permission_write_permissions(Permission), set)


# ---------------------------------------------------------------------------
# Role enum / permission mapping
# ---------------------------------------------------------------------------


class TestRolePermissions:
    def test_readonly_permissions(self) -> None:
        assert Role.READONLY.get_permissions() == {Permission.READ}

    def test_readwrite_permissions(self) -> None:
        perms = Role.READWRITE.get_permissions()
        assert Permission.READ in perms
        assert Permission.WRITE in perms
        assert Permission.DELETE in perms

    def test_admin_permissions(self) -> None:
        perms = Role.ADMIN.get_permissions()
        assert Permission.READ in perms
        assert Permission.WRITE in perms
        assert Permission.DELETE in perms
        assert Permission.ADMIN in perms

    def test_unknown_role_fallback_branch(self) -> None:
        # The else branch `return set()` is unreachable through public API
        # because Role is a closed Enum. Reach it by calling the underlying
        # function with a sentinel self that matches none of the three roles.
        underlying = Role.get_permissions
        sentinel_self = object()
        result = underlying(sentinel_self)
        assert result == set()


# ---------------------------------------------------------------------------
# AuthResult
# ---------------------------------------------------------------------------


class TestAuthResult:
    def test_has_permission_true(self) -> None:
        ar = AuthResult(success=True, permissions={Permission.READ, Permission.WRITE})
        assert ar.has_permission(Permission.READ)
        assert ar.has_permission(Permission.WRITE)

    def test_has_permission_false(self) -> None:
        ar = AuthResult(success=True, permissions={Permission.READ})
        assert not ar.has_permission(Permission.ADMIN)


# ---------------------------------------------------------------------------
# AuthContext
# ---------------------------------------------------------------------------


class TestAuthContext:
    def test_post_init_sets_timestamp(self) -> None:
        ctx = AuthContext(token="x")
        assert ctx.timestamp is not None
        ts = int(ctx.timestamp)
        assert abs(ts - int(time.time())) < 5

    def test_post_init_preserves_explicit_timestamp(self) -> None:
        ctx = AuthContext(token="x", timestamp="1234567890")
        assert ctx.timestamp == "1234567890"

    def test_default_rate_limit_values(self) -> None:
        ctx = AuthContext()
        assert ctx.rate_limit_window == 60.0
        assert ctx.rate_limit_requests == 1000


# ---------------------------------------------------------------------------
# TokenInfo expiration/validity
# ---------------------------------------------------------------------------


class TestTokenInfo:
    def test_is_expired_when_no_expiry(self) -> None:
        ti = TokenInfo(
            token_id="a",
            token_hash="x",
            role=Role.READONLY,
            created_at=datetime.now(UTC),
            expires_at=None,
        )
        assert ti.is_expired() is False

    def test_is_expired_future_date(self) -> None:
        ti = TokenInfo(
            token_id="a",
            token_hash="x",
            role=Role.READONLY,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        assert ti.is_expired() is False

    def test_is_expired_past_date(self) -> None:
        ti = TokenInfo(
            token_id="a",
            token_hash="x",
            role=Role.READONLY,
            created_at=datetime.now(UTC) - timedelta(days=2),
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        assert ti.is_expired() is True

    def test_is_expired_normalizes_naive_datetime(self) -> None:
        ti = TokenInfo(
            token_id="a",
            token_hash="x",
            role=Role.READONLY,
            created_at=datetime.now(UTC),
            expires_at=datetime.now() - timedelta(seconds=10),
        )
        assert ti.is_expired() is True

    def test_is_valid_when_not_revoked_and_not_expired(self) -> None:
        ti = TokenInfo(
            token_id="a",
            token_hash="x",
            role=Role.READONLY,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        assert ti.is_valid() is True

    def test_is_valid_false_when_revoked(self) -> None:
        ti = TokenInfo(
            token_id="a",
            token_hash="x",
            role=Role.READONLY,
            created_at=datetime.now(UTC),
            is_revoked=True,
        )
        assert ti.is_valid() is False

    def test_is_valid_false_when_expired(self) -> None:
        ti = TokenInfo(
            token_id="a",
            token_hash="x",
            role=Role.READONLY,
            created_at=datetime.now(UTC) - timedelta(days=10),
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        assert ti.is_valid() is False


# ---------------------------------------------------------------------------
# TokenAuth
# ---------------------------------------------------------------------------


class TestTokenAuthInit:
    def test_init_without_file(self) -> None:
        ta = TokenAuth()
        assert ta.tokens == {}
        assert ta.tokens_file is None
        assert ta.require_auth is True
        assert ta.default_role == Role.READONLY

    def test_init_loads_existing_tokens_file(self, tmp_token_file: Path) -> None:
        payload = {
            "tokens": {
                "tok1": {
                    "token_hash": "abc123",
                    "role": "readwrite",
                    "created_at": datetime.now(UTC).isoformat(),
                    "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                    "is_revoked": False,
                    "rate_limit": 500,
                    "metadata": {"source": "test"},
                }
            }
        }
        tmp_token_file.write_text(json.dumps(payload))
        ta = TokenAuth(tokens_file=str(tmp_token_file))
        assert "tok1" in ta.tokens
        info = ta.tokens["tok1"]
        assert info.role == Role.READWRITE
        assert info.rate_limit == 500
        assert info.metadata == {"source": "test"}


class TestTokenAuthLoadSave:
    def test_load_tokens_returns_keys(self, tmp_token_file: Path) -> None:
        payload = {
            "tokens": {
                "tok1": {
                    "token_hash": "deadbeef",
                    "role": "admin",
                    "created_at": datetime.now(UTC).isoformat(),
                    "expires_at": None,
                }
            }
        }
        tmp_token_file.write_text(json.dumps(payload))
        ta = TokenAuth()
        ta.load_tokens(str(tmp_token_file))
        assert "tok1" in ta.tokens
        assert ta.tokens["tok1"].role == Role.ADMIN

    def test_load_tokens_empty_file(self, tmp_token_file: Path) -> None:
        tmp_token_file.write_text("")
        ta = TokenAuth()
        ta.load_tokens(str(tmp_token_file))
        assert ta.tokens == {}

    def test_load_tokens_propagates_errors(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json")
        ta = TokenAuth()
        with pytest.raises(json.JSONDecodeError):
            ta.load_tokens(str(bad_file))

    def test_save_tokens_requires_path(self) -> None:
        ta = TokenAuth()
        with pytest.raises(ValueError, match="No tokens file specified"):
            ta.save_tokens()

    def test_save_tokens_round_trip(self, tmp_token_file: Path) -> None:
        ta = TokenAuth()
        ta.add_token("tok1", "raw-secret", role=Role.READWRITE, expires_in=3600)
        ta.save_tokens(filepath=str(tmp_token_file))
        assert tmp_token_file.exists()
        ta2 = TokenAuth()
        ta2.load_tokens(str(tmp_token_file))
        assert "tok1" in ta2.tokens

    def test_save_tokens_uses_default_path(self, tmp_token_file: Path) -> None:
        ta = TokenAuth(tokens_file=str(tmp_token_file))
        ta.add_token("tok1", "raw-secret", role=Role.READWRITE)
        ta.save_tokens()
        assert tmp_token_file.exists()

    def test_save_tokens_no_expires_at(self, tmp_token_file: Path) -> None:
        ta = TokenAuth()
        ta.add_token("tok1", "raw-secret")
        ta.save_tokens(filepath=str(tmp_token_file))
        ta2 = TokenAuth()
        ta2.load_tokens(str(tmp_token_file))
        assert ta2.tokens["tok1"].expires_at is None


class TestTokenAuthAddRevoke:
    def test_add_token_with_metadata_and_expiry(self) -> None:
        ta = TokenAuth()
        ti = ta.add_token(
            "tok1",
            "raw-secret",
            role=Role.ADMIN,
            expires_in=3600,
            rate_limit=42,
            metadata={"foo": "bar"},
        )
        assert ti.role == Role.ADMIN
        assert ti.expires_at is not None
        assert ti.rate_limit == 42
        assert ti.metadata == {"foo": "bar"}
        assert ta.tokens["tok1"] is ti

    def test_add_token_default_metadata(self) -> None:
        ta = TokenAuth()
        ti = ta.add_token("tok1", "raw")
        assert ti.metadata == {}

    def test_revoke_existing_token(self) -> None:
        ta = TokenAuth()
        ta.add_token("tok1", "raw")
        assert ta.revoke_token("tok1") is True
        assert ta.tokens["tok1"].is_revoked is True

    def test_revoke_missing_token(self) -> None:
        ta = TokenAuth()
        assert ta.revoke_token("missing") is False

    def test_hash_and_compare_tokens(self) -> None:
        ta = TokenAuth()
        sha = ta._hash_token("abc")
        assert sha == hashlib.sha256(b"abc").hexdigest()
        assert ta._compare_tokens("abc", sha) is True
        assert ta._compare_tokens("xyz", sha) is False


class TestTokenAuthRateLimit:
    @pytest.mark.asyncio
    async def test_check_rate_limit_within_budget(self) -> None:
        ta = TokenAuth()
        ta.add_token("tok1", "raw", rate_limit=5)
        info = ta.tokens["tok1"]
        assert await ta._check_rate_limit("tok1", info) is True
        assert await ta._check_rate_limit("tok1", info) is True

    @pytest.mark.asyncio
    async def test_check_rate_limit_exceeded(self) -> None:
        ta = TokenAuth()
        ta.add_token("tok1", "raw", rate_limit=2)
        info = ta.tokens["tok1"]
        assert await ta._check_rate_limit("tok1", info) is True
        assert await ta._check_rate_limit("tok1", info) is True
        assert await ta._check_rate_limit("tok1", info) is False

    @pytest.mark.asyncio
    async def test_check_rate_limit_clears_old_timestamps(self) -> None:
        ta = TokenAuth()
        ta.add_token("tok1", "raw", rate_limit=2)
        info = ta.tokens["tok1"]
        ta._rate_limit_tracker["tok1"] = [time.time() - 120.0]
        assert await ta._check_rate_limit("tok1", info) is True
        assert all(ts > time.time() - 60.0 for ts in ta._rate_limit_tracker["tok1"])

    @pytest.mark.asyncio
    async def test_check_rate_limit_public_wrapper_missing_token(self) -> None:
        ta = TokenAuth()
        assert await ta.check_rate_limit("missing") is True

    @pytest.mark.asyncio
    async def test_check_rate_limit_public_wrapper_delegates(self) -> None:
        ta = TokenAuth()
        ta.add_token("tok1", "raw", rate_limit=1)
        assert await ta.check_rate_limit("tok1") is True
        assert await ta.check_rate_limit("tok1") is False


class TestTokenAuthenticate:
    def test_authenticate_disabled_returns_default_role(self) -> None:
        ta = TokenAuth(require_auth=False, default_role=Role.ADMIN)
        result = ta.authenticate("anything")
        assert result.success is True
        assert result.role == Role.ADMIN
        assert Permission.ADMIN in result.permissions

    def test_authenticate_success(self) -> None:
        ta = TokenAuth()
        ta.add_token("tok1", "secret", role=Role.READWRITE)
        # TokenAuth.authenticate hashes the input then compares; the raw
        # secret string is the input — the stored hash is sha256("secret").
        result = ta.authenticate("secret")
        assert result.success is True
        assert result.role == Role.READWRITE
        assert Permission.READ in result.permissions

    def test_authenticate_invalid_token(self) -> None:
        ta = TokenAuth()
        ta.add_token("tok1", "secret")
        result = ta.authenticate("not-the-secret")
        assert result.success is False
        assert result.error_message

    def test_authenticate_skips_revoked(self) -> None:
        ta = TokenAuth()
        ta.add_token("tok1", "secret")
        ta.revoke_token("tok1")
        result = ta.authenticate("secret")
        assert result.success is False

    def test_authenticate_skips_expired(self) -> None:
        ta = TokenAuth()
        ta.add_token("tok1", "secret", expires_in=-1)
        result = ta.authenticate("secret")
        assert result.success is False

    def test_authenticate_updates_last_used(self) -> None:
        ta = TokenAuth()
        ta.add_token("tok1", "secret")
        ta.authenticate("secret")
        assert ta.tokens["tok1"].last_used is not None


# ---------------------------------------------------------------------------
# HMACAuth
# ---------------------------------------------------------------------------


class TestHMACAuth:
    def test_init_loads_secrets_file(self, tmp_path: Path) -> None:
        f = tmp_path / "secrets.json"
        f.write_text(json.dumps({"secrets": {"client1": "hash-of-secret"}}))
        hmac_auth = HMACAuth(secrets_file=str(f))
        assert hmac_auth.secrets == {"client1": "hash-of-secret"}

    def test_load_secrets_propagates_errors(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{invalid")
        with pytest.raises(json.JSONDecodeError):
            HMACAuth(secrets_file=str(bad)).load_secrets(str(bad))

    def test_hash_secret_returns_sha256(self) -> None:
        hmac_auth = HMACAuth()
        result = hmac_auth._hash_secret("hello")
        assert result == hashlib.sha256(b"hello").hexdigest()

    def test_generate_signature(self) -> None:
        hmac_auth = HMACAuth()
        sig = hmac_auth.generate_signature("payload", "secret", "1234567890")
        expected = hmac.new(b"secret", b"1234567890payload", hashlib.sha256).digest()
        assert sig == b64encode(expected).decode()

    def test_verify_signature_success(self) -> None:
        hmac_auth = HMACAuth(secrets={"client1": "mysecret"})
        sig = hmac_auth.generate_signature("payload", "mysecret", "ts")
        assert hmac_auth.verify_signature("payload", sig, "ts", "client1") is True

    def test_verify_signature_failure(self) -> None:
        hmac_auth = HMACAuth(secrets={"client1": "mysecret"})
        assert hmac_auth.verify_signature("payload", "bogus", "ts", "client1") is False

    def test_verify_signature_unknown_client(self) -> None:
        hmac_auth = HMACAuth()
        assert hmac_auth.verify_signature("payload", "x", "ts", "missing") is False

    def test_authenticate_disabled_returns_admin(self) -> None:
        hmac_auth = HMACAuth(require_auth=False)
        result = hmac_auth.authenticate("p", "s", "ts", "client1")
        assert result.success is True
        assert result.role == Role.ADMIN

    def test_authenticate_success(self) -> None:
        hmac_auth = HMACAuth(secrets={"c1": "k"})
        sig = hmac_auth.generate_signature("p", "k", "t")
        result = hmac_auth.authenticate("p", sig, "t", "c1")
        assert result.success is True
        assert result.role == Role.ADMIN

    def test_authenticate_failure(self) -> None:
        hmac_auth = HMACAuth(secrets={"c1": "k"})
        result = hmac_auth.authenticate("p", "bogus", "t", "c1")
        assert result.success is False


# ---------------------------------------------------------------------------
# EnvironmentAuth
# ---------------------------------------------------------------------------


class TestEnvironmentAuth:
    def test_authenticate_disabled_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DURUS_AUTH_TOKEN", raising=False)
        env = EnvironmentAuth(require_auth=False)
        result = env.authenticate()
        assert result.success is True
        assert result.role == Role.ADMIN

    def test_authenticate_valid_env_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DURUS_AUTH_TOKEN", "tok123")
        env = EnvironmentAuth(require_auth=True)
        result = env.authenticate(token="tok123")
        assert result.success is True

    def test_authenticate_required_but_invalid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DURUS_AUTH_TOKEN", raising=False)
        env = EnvironmentAuth(require_auth=True)
        result = env.authenticate(token="wrong")
        assert result.success is False

    def test_authenticate_required_but_no_token_no_input(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DURUS_AUTH_TOKEN", raising=False)
        env = EnvironmentAuth(require_auth=True)
        result = env.authenticate()
        assert result.success is False

    def test_authenticate_optional_with_wrong_token_falls_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DURUS_AUTH_TOKEN", "env-tok")
        env = EnvironmentAuth(require_auth=False)
        result = env.authenticate(token="wrong-token")
        assert result.success is True
        assert result.token_id == "default"

    def test_authenticate_optional_no_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DURUS_AUTH_TOKEN", raising=False)
        env = EnvironmentAuth(require_auth=False)
        result = env.authenticate()
        assert result.success is True


# ---------------------------------------------------------------------------
# AuthMiddleware
# ---------------------------------------------------------------------------


class TestAuthMiddleware:
    def test_init_defaults(self) -> None:
        mw = AuthMiddleware()
        assert mw.require_auth is True
        assert mw.token_auth is None

    def test_authenticate_token_success(self) -> None:
        ta = TokenAuth()
        ta.add_token("tok1", "secret", role=Role.READWRITE)
        mw = AuthMiddleware(token_auth=ta, require_auth=True)
        result = mw.authenticate(AuthContext(token="secret"))
        assert result.success is True
        assert result.role == Role.READWRITE

    def test_authenticate_falls_through_to_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DURUS_AUTH_TOKEN", "env-tok")
        env_auth = EnvironmentAuth()
        mw = AuthMiddleware(env_auth=env_auth, require_auth=True)
        result = mw.authenticate(AuthContext(token="env-tok"))
        assert result.success is True

    def test_authenticate_hmac_path(self) -> None:
        hmac_auth = HMACAuth(secrets={"c1": "k"})
        # Middleware calls hmac_auth.authenticate(payload="", ...) so the
        # signature must be generated for an empty payload.
        sig = hmac_auth.generate_signature("", "k", "ts")
        mw = AuthMiddleware(hmac_auth=hmac_auth, require_auth=True)
        result = mw.authenticate(
            AuthContext(hmac_signature=sig, timestamp="ts", client_id="c1")
        )
        assert result.success is True

    def test_authenticate_required_fails_all(self) -> None:
        mw = AuthMiddleware(require_auth=True)
        result = mw.authenticate(AuthContext())
        assert result.success is False

    def test_authenticate_not_required_default(self) -> None:
        mw = AuthMiddleware(require_auth=False)
        result = mw.authenticate(AuthContext())
        assert result.success is True
        assert result.role == Role.READONLY

    def test_check_permission(self) -> None:
        mw = AuthMiddleware()
        good = AuthResult(success=True, permissions={Permission.READ})
        bad = AuthResult(success=False, permissions={Permission.READ})
        assert mw.check_permission(good, Permission.READ) is True
        assert mw.check_permission(bad, Permission.READ) is False
        noperm = AuthResult(success=True, permissions={Permission.WRITE})
        assert mw.check_permission(noperm, Permission.READ) is False

    @pytest.mark.asyncio
    async def test_require_permission_async_success(self) -> None:
        mw = AuthMiddleware(require_auth=False)
        captured: dict[str, Any] = {}

        @mw.require_permission(Permission.READ)
        async def endpoint(*args: Any, **kwargs: Any):
            captured["auth_result"] = kwargs.get("auth_result")
            return "ok"

        result = await endpoint(auth_context=AuthContext())
        assert result == "ok"
        assert "auth_result" in captured

    @pytest.mark.asyncio
    async def test_require_permission_async_no_context(self) -> None:
        mw = AuthMiddleware(require_auth=False)

        @mw.require_permission(Permission.READ)
        async def endpoint(*args: Any, **kwargs: Any):
            return "ok"

        with pytest.raises(ValueError, match="auth_context required"):
            await endpoint()

    @pytest.mark.asyncio
    async def test_require_permission_async_auth_failed(self) -> None:
        mw = AuthMiddleware(require_auth=True)

        @mw.require_permission(Permission.READ)
        async def endpoint(*args: Any, auth_context: AuthContext, **kwargs: Any):
            return "ok"

        with pytest.raises(PermissionError):
            await endpoint(auth_context=AuthContext())

    @pytest.mark.asyncio
    async def test_require_permission_async_missing_permission(self) -> None:
        mw = AuthMiddleware(require_auth=False)

        @mw.require_permission(Permission.ADMIN)
        async def endpoint(*args: Any, auth_context: AuthContext, **kwargs: Any):
            return "ok"

        with pytest.raises(PermissionError, match="Permission 'admin' required"):
            await endpoint(auth_context=AuthContext())

    def test_require_permission_sync_success(self) -> None:
        mw = AuthMiddleware(require_auth=False)
        captured: dict[str, Any] = {}

        @mw.require_permission(Permission.READ)
        def endpoint(*args: Any, **kwargs: Any):
            captured["auth_result"] = kwargs.get("auth_result")
            return "ok-sync"

        result = endpoint(auth_context=AuthContext())
        assert result == "ok-sync"
        assert "auth_result" in captured

    def test_require_permission_sync_no_context(self) -> None:
        mw = AuthMiddleware(require_auth=False)

        @mw.require_permission(Permission.READ)
        def endpoint(*args: Any, **kwargs: Any):
            return "ok"

        with pytest.raises(ValueError, match="auth_context required"):
            endpoint()

    def test_require_permission_sync_auth_failed(self) -> None:
        mw = AuthMiddleware(require_auth=True)

        @mw.require_permission(Permission.READ)
        def endpoint(*args: Any, auth_context: AuthContext, **kwargs: Any):
            return "ok"

        with pytest.raises(PermissionError):
            endpoint(auth_context=AuthContext())

    def test_require_permission_sync_missing_permission(self) -> None:
        mw = AuthMiddleware(require_auth=False)

        @mw.require_permission(Permission.ADMIN)
        def endpoint(*args: Any, auth_context: AuthContext, **kwargs: Any):
            return "ok"

        with pytest.raises(PermissionError, match="Permission 'admin' required"):
            endpoint(auth_context=AuthContext())

    def test_audit_log_with_context(self) -> None:
        log = MagicMock()
        mw = AuthMiddleware(audit_log=log)
        mw._audit_log("test_event", context=AuthContext(client_id="abc"))
        assert log.info.called
        msg = log.info.call_args.args[0]
        assert "AUDIT" in msg
        assert "test_event" in msg

    def test_audit_log_with_extra(self) -> None:
        log = MagicMock()
        mw = AuthMiddleware(audit_log=log)
        mw._audit_log("ev", context=None, extra={"foo": "bar"})
        assert log.info.called
        msg = log.info.call_args.args[0]
        assert "foo" in msg and "bar" in msg

    def test_audit_log_default_logger(self) -> None:
        mw = AuthMiddleware()
        mw._audit_log("ev", context=None)


# ---------------------------------------------------------------------------
# require_dhara_auth decorator
# ---------------------------------------------------------------------------


class TestRequireDharaAuth:
    @pytest.mark.asyncio
    async def test_passthrough_when_disabled(self) -> None:
        captured: dict[str, Any] = {}

        @require_dhara_auth(Permission.WRITE)
        async def endpoint(x: int) -> int:
            captured["x"] = x
            return x * 2

        result = await endpoint(x=5)
        assert result == 10
        assert captured == {"x": 5}

    @pytest.mark.asyncio
    async def test_missing_token_returns_error_envelope(self) -> None:
        with patch("dhara.mcp.auth._get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.enabled = True
            cfg.secret = "mysecret"
            mock_cfg.return_value = cfg

            @require_dhara_auth(Permission.WRITE)
            async def endpoint(x: int) -> int:
                return x

            result = await endpoint(x=5)
        assert result == {
            "error": "Authentication required",
            "error_code": "AUTH_REQUIRED",
        }

    @pytest.mark.asyncio
    async def test_auth_error_returns_error_envelope(self) -> None:
        with patch("dhara.mcp.auth._get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.enabled = True
            cfg.secret = "mysecret"
            mock_cfg.return_value = cfg

            with patch("dhara.mcp.auth._verify_token") as mock_vt:
                mock_vt.side_effect = AuthError("bad token")
                with patch.object(_audit, "emit"):

                    @require_dhara_auth(Permission.WRITE)
                    async def endpoint(x: int) -> int:
                        return x

                    result = await endpoint(x=5, __auth_token__="bad")
        assert result == {"error": "bad token", "error_code": "AUTH_FAILED"}

    @pytest.mark.asyncio
    async def test_success_emits_audit_and_calls(self) -> None:
        with patch("dhara.mcp.auth._get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.enabled = True
            cfg.secret = "mysecret"
            mock_cfg.return_value = cfg

            payload = _make_token_payload()
            with patch("dhara.mcp.auth._verify_token", return_value=payload), \
                 patch.object(_audit, "emit") as mock_emit:

                @require_dhara_auth(Permission.WRITE)
                async def endpoint(x: int) -> int:
                    return x * 2

                result = await endpoint(x=7, __auth_token__="good")
        assert result == 14
        assert mock_emit.called
        event = mock_emit.call_args.args[0]
        assert event.service == "dhara"
        assert event.caller_service == payload.issuer
        assert event.caller_id == payload.subject
        assert event.permission == Permission.WRITE
        assert event.result == "allowed"

    @pytest.mark.asyncio
    async def test_dhara_permission_falls_back_to_read(self) -> None:
        with patch("dhara.mcp.auth._get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.enabled = True
            cfg.secret = "mysecret"
            mock_cfg.return_value = cfg

            payload = _make_token_payload()
            with patch("dhara.mcp.auth._verify_token", return_value=payload), \
                 patch.object(_audit, "emit") as mock_emit:

                @require_dhara_auth(DharaPermission.CHECKPOINT)
                async def endpoint(x: int) -> int:
                    return x

                await endpoint(x=3, __auth_token__="good")
        event = mock_emit.call_args.args[0]
        assert event.permission == Permission.READ


# ---------------------------------------------------------------------------
# Token generation helpers
# ---------------------------------------------------------------------------


class TestTokenGeneration:
    def test_generate_token_default(self) -> None:
        tok = generate_token()
        assert isinstance(tok, str)
        assert len(tok) >= 40

    def test_generate_token_custom_length(self) -> None:
        tok = generate_token(16)
        assert isinstance(tok, str)
        assert len(tok) >= 20

    def test_generate_token_unique_each_call(self) -> None:
        a = generate_token()
        b = generate_token()
        assert a != b

    def test_generate_api_token(self) -> None:
        raw, hashed = generate_api_token("tok1", role="admin")
        assert isinstance(raw, str) and len(raw) >= 40
        assert hashed == hashlib.sha256(raw.encode()).hexdigest()

    def test_generate_token_raises_inside_running_loop(self) -> None:
        async def _runner():
            with pytest.raises(RuntimeError, match="generate_token cannot be called from inside a running event loop"):
                generate_token()

        asyncio.run(_runner())

    def test_block_on_running_loop_normal(self) -> None:
        _block_on_running_loop()

    def test_block_on_running_loop_raises(self) -> None:
        async def _runner():
            with pytest.raises(RuntimeError, match="generate_token cannot be called"):
                _block_on_running_loop()

        asyncio.run(_runner())

    def test_secure_token_action_is_cached(self) -> None:
        a = _secure_token_action()
        b = _secure_token_action()
        assert a is b
        assert isinstance(a, SecuritySecureAction)

    def test_secure_token_action_metadata(self) -> None:
        action = _secure_token_action()
        # execute() is a coroutine; await it via asyncio.run
        result = asyncio.run(
            action.execute({"mode": "token", "length": 16})
        )
        assert isinstance(result, dict)
        assert "token" in result
        assert isinstance(result["token"], str)


# ---------------------------------------------------------------------------
# `__all__` export sanity
# ---------------------------------------------------------------------------


class TestModuleExports:
    def test_all_contains_expected(self) -> None:
        assert "DharaPermission" in auth_module.__all__
        assert "Role" in auth_module.__all__
        assert "AuthResult" in auth_module.__all__
        assert "AuthContext" in auth_module.__all__
        assert "TokenAuth" in auth_module.__all__
        assert "TokenInfo" in auth_module.__all__
        assert "HMACAuth" in auth_module.__all__
        assert "EnvironmentAuth" in auth_module.__all__
        assert "AuthMiddleware" in auth_module.__all__
        assert "require_dhara_auth" in auth_module.__all__
        assert "generate_token" in auth_module.__all__
        assert "generate_api_token" in auth_module.__all__
        assert "_utcnow" in auth_module.__all__
        assert "_as_utc" in auth_module.__all__


# ---------------------------------------------------------------------------
# Additional branch-coverage exercises: fall-throughs in
# AuthMiddleware.authenticate and the save_tokens except branch
# ---------------------------------------------------------------------------


class TestAuthMiddlewareFallthroughs:
    def test_token_auth_fails_falls_through_to_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DURUS_AUTH_TOKEN", "env-tok")
        ta = TokenAuth()
        ta.add_token("tok1", "right-secret")
        env_auth = EnvironmentAuth(require_auth=False)
        mw = AuthMiddleware(
            token_auth=ta, env_auth=env_auth, require_auth=False
        )
        # token path fails (wrong input), env path succeeds
        result = mw.authenticate(AuthContext(token="env-tok"))
        assert result.success is True
        assert result.token_id == "environment"

    def test_token_and_hmac_fall_through_to_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DURUS_AUTH_TOKEN", "env-tok")
        ta = TokenAuth()
        ta.add_token("tok1", "right-secret")
        hmac_auth = HMACAuth(secrets={"c1": "k"})
        env_auth = EnvironmentAuth(require_auth=False)
        mw = AuthMiddleware(
            token_auth=ta, hmac_auth=hmac_auth, env_auth=env_auth,
            require_auth=False,
        )
        # wrong token + bad hmac signature → both fail → env succeeds
        result = mw.authenticate(
            AuthContext(
                token="bogus",
                hmac_signature="not-a-valid-sig",
                timestamp="ts",
                client_id="c1",
            )
        )
        # env_auth (require_auth=False) returns success="default" path
        # because env_token != provided token
        assert result.success is True

    def test_all_methods_fail_falls_through_to_require_auth_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DURUS_AUTH_TOKEN", raising=False)
        ta = TokenAuth()
        ta.add_token("tok1", "right-secret")
        hmac_auth = HMACAuth(secrets={"c1": "k"})
        # env_auth with require_auth=True will reject (no env var, no token)
        env_auth = EnvironmentAuth(require_auth=True)
        mw = AuthMiddleware(
            token_auth=ta, hmac_auth=hmac_auth, env_auth=env_auth,
            require_auth=True,
        )
        result = mw.authenticate(
            AuthContext(
                token="bogus",
                hmac_signature="bogus",
                timestamp="ts",
                client_id="c1",
            )
        )
        assert result.success is False


class TestSaveTokensError:
    def test_save_tokens_propagates_os_error(self, tmp_path: Path) -> None:
        ta = TokenAuth()
        ta.add_token("tok1", "raw")
        # write to a directory path → OSError on open() in write mode
        with pytest.raises((OSError, IsADirectoryError)):
            ta.save_tokens(filepath=str(tmp_path))
