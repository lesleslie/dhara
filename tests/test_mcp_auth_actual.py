from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from dhara.mcp import auth as auth_module
from dhara.mcp.auth import (
    AuthContext,
    AuthMiddleware,
    AuthResult,
    DharaPermission,
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
    require_dhara_auth,
)
from mcp_common.auth.exceptions import AuthError


@pytest.fixture(autouse=True)
def _reset_auth_config():
    auth_module._reset_config()
    yield
    auth_module._reset_config()


def test_utc_helpers_and_permissions():
    now = _utcnow()
    assert now.tzinfo == UTC

    naive = datetime(2024, 1, 1, 12, 0, 0)
    aware = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert _as_utc(naive).tzinfo == UTC
    assert _as_utc(aware) == aware

    assert DharaPermission.CHECKPOINT.value == "checkpoint"
    assert Role.READONLY.get_permissions() == {Permission.READ}
    assert Role.READWRITE.get_permissions() == {
        Permission.READ,
        Permission.WRITE,
        Permission.DELETE,
    }
    assert Role.ADMIN.get_permissions() == {
        Permission.READ,
        Permission.WRITE,
        Permission.DELETE,
        Permission.ADMIN,
    }


def test_role_fallback_branch():
    bogus = object.__new__(Role)
    assert Role.get_permissions(bogus) == set()


def test_auth_result_context_and_tokeninfo():
    result = AuthResult(success=True, permissions={Permission.READ})
    assert result.has_permission(Permission.READ) is True
    assert result.has_permission(Permission.WRITE) is False

    context = AuthContext()
    assert context.timestamp is not None
    assert context.timestamp.isdigit()

    explicit = AuthContext(timestamp="123", token="tok")
    assert explicit.timestamp == "123"
    assert explicit.token == "tok"

    expired = TokenInfo(
        token_id="t1",
        token_hash="hash",
        role=Role.READONLY,
        created_at=datetime.now(UTC) - timedelta(days=1),
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    valid = TokenInfo(
        token_id="t2",
        token_hash="hash",
        role=Role.READONLY,
        created_at=datetime.now(UTC),
    )
    assert expired.is_expired() is True
    assert valid.is_expired() is False
    assert valid.is_valid() is True


def test_token_auth_round_trip_and_rate_limit(tmp_path):
    tokens_file = tmp_path / "tokens.json"
    token_auth = TokenAuth(require_auth=True, tokens_file=str(tokens_file))
    token_info = token_auth.add_token("tok1", "secret", role=Role.READWRITE, rate_limit=1)
    assert token_auth.authenticate("secret").success is True
    assert token_auth.authenticate("bad").success is False
    assert token_auth.revoke_token("tok1") is True
    assert token_auth.revoke_token("missing") is False
    assert token_info.is_valid() is False

    token_auth.save_tokens()
    saved = json.loads(tokens_file.read_text())
    assert "tok1" in saved["tokens"]

    loaded = TokenAuth(tokens_file=str(tokens_file))
    assert "tok1" in loaded.tokens


def test_token_auth_load_and_save_error_paths(tmp_path):
    bad_tokens = tmp_path / "bad_tokens.json"
    bad_tokens.write_text("{not-json")
    with pytest.raises(Exception):
        TokenAuth(tokens_file=str(bad_tokens))

    token_auth = TokenAuth(require_auth=True)
    with pytest.raises(ValueError, match="No tokens file specified"):
        token_auth.save_tokens()

    token_auth.tokens_file = str(tmp_path / "out.json")
    with patch("builtins.open", side_effect=OSError("boom")):
        with pytest.raises(OSError):
            token_auth.save_tokens()


@pytest.mark.asyncio
async def test_token_auth_rate_limit_and_hash_helpers():
    token_auth = TokenAuth(require_auth=True)
    token_info = token_auth.add_token("tok", "secret", rate_limit=1)
    assert token_auth._hash_token("secret") == hashlib.sha256(b"secret").hexdigest()
    assert token_auth._compare_tokens("secret", token_info.token_hash) is True
    assert await token_auth.check_rate_limit("missing") is True
    assert await token_auth._check_rate_limit("tok", token_info) is True
    assert await token_auth._check_rate_limit("tok", token_info) is False


def test_token_auth_expires_in_branch():
    token_auth = TokenAuth(require_auth=True)
    token_info = token_auth.add_token("tok-exp", "secret", expires_in=10)
    assert token_info.expires_at is not None


def test_hmac_and_environment_auth(monkeypatch):
    hmac_auth = HMACAuth(secrets={"client": "sharedsecret"})
    signature = hmac_auth.generate_signature("payload", "sharedsecret", "123")
    assert hmac_auth.verify_signature("payload", signature, "123", "client") is True
    assert hmac_auth.verify_signature("payload", "bad", "123", "missing") is False
    assert hmac_auth.authenticate("payload", signature, "123", "client").success is True
    assert hmac_auth.authenticate("payload", "bad", "123", "client").success is False

    monkeypatch.delenv("TEST_AUTH_TOKEN", raising=False)
    env_auth = EnvironmentAuth(env_var="TEST_AUTH_TOKEN", require_auth=False)
    assert env_auth.authenticate().success is True

    monkeypatch.setenv("TEST_AUTH_TOKEN", "token")
    relaxed_env = EnvironmentAuth(env_var="TEST_AUTH_TOKEN", require_auth=False)
    assert relaxed_env.authenticate("bad").success is True

    strict_env = EnvironmentAuth(env_var="TEST_AUTH_TOKEN", require_auth=True)
    assert strict_env.authenticate("token").success is True
    assert strict_env.authenticate("bad").success is False


def test_auth_module_reload_and_fallback_branches(monkeypatch):
    import importlib

    reloaded = importlib.reload(auth_module)

    first = reloaded._get_config()
    second = reloaded._get_config()
    assert first is second

    failing_hmac = SimpleNamespace(
        authenticate=MagicMock(return_value=reloaded.AuthResult(success=False))
    )
    failing_env = SimpleNamespace(
        authenticate=MagicMock(return_value=reloaded.AuthResult(success=False))
    )
    middleware = reloaded.AuthMiddleware(
        hmac_auth=failing_hmac,
        env_auth=failing_env,
        require_auth=False,
    )
    result = middleware.authenticate(
        reloaded.AuthContext(
            token="token",
            hmac_signature="sig",
            timestamp="123",
            client_id="client",
        )
    )

    assert result.success is True
    assert result.token_id == "default"


def test_hmac_auth_file_loading_and_hash_branch(tmp_path):
    secrets_file = tmp_path / "secrets.json"
    secrets_file.write_text(json.dumps({"secrets": {"client": "sharedsecret"}}))

    auth = HMACAuth(secrets_file=str(secrets_file))
    assert auth.secrets["client"] == "sharedsecret"
    assert auth._hash_secret("plain") == hashlib.sha256(b"plain").hexdigest()

    bad_file = tmp_path / "bad_secrets.json"
    bad_file.write_text("{broken")
    with pytest.raises(Exception):
        HMACAuth(secrets_file=str(bad_file))


def test_generate_token_helpers(monkeypatch):
    # Wave 3: generate_token no longer calls secrets.token_hex directly;
    # it routes through SecuritySecureAction (mode='token') which uses
    # secrets.token_urlsafe. Monkeypatch the action's underlying
    # token_urlsafe so we can assert deterministic token shapes without
    # coupling to the exact url-safe length.
    url_safe_calls: list[int] = []

    def fake_url_safe(n: int) -> str:
        url_safe_calls.append(n)
        return "a" * (4 * n // 3)

    monkeypatch.setattr(auth_module.secrets, "token_urlsafe", fake_url_safe)
    token = generate_token(8)
    assert token == "a" * 10  # 4 * 8 // 3 == 10
    assert url_safe_calls == [8]

    api_token, token_hash = generate_api_token("token-id", role="admin")
    assert api_token == "a" * (4 * 32 // 3)  # default generate_token length
    assert token_hash == hashlib.sha256(api_token.encode()).hexdigest()


def test_auth_middleware_paths(monkeypatch):
    ok_result = AuthResult(success=True, permissions={Permission.READ, Permission.WRITE})
    bad_result = AuthResult(success=False, error_message="nope")
    token_auth = SimpleNamespace(authenticate=MagicMock(return_value=ok_result))
    hmac_auth = SimpleNamespace(authenticate=MagicMock(return_value=ok_result))
    env_auth = SimpleNamespace(authenticate=MagicMock(return_value=ok_result))
    middleware = AuthMiddleware(token_auth=token_auth, hmac_auth=hmac_auth, env_auth=env_auth)

    assert middleware.check_permission(ok_result, Permission.READ) is True
    assert middleware.check_permission(bad_result, Permission.READ) is False

    context = AuthContext(token="token", hmac_signature="sig", timestamp="123", client_id="client")
    assert middleware.authenticate(context).success is True

    middleware_no_auth = AuthMiddleware(require_auth=False)
    assert middleware_no_auth.authenticate(AuthContext()).success is True

    middleware_require = AuthMiddleware(require_auth=True)
    assert middleware_require.authenticate(AuthContext()).success is False

    captured: list[dict[str, object]] = []
    monkeypatch.setattr(
        middleware,
        "audit_log",
        SimpleNamespace(info=lambda msg: captured.append({"msg": msg})),
    )
    middleware._audit_log("event", context, {"extra": 1})
    assert captured and "AUDIT:" in captured[0]["msg"]  # type: ignore[index]


def test_auth_middleware_hmac_and_env_paths(monkeypatch):
    hmac_auth = SimpleNamespace(authenticate=MagicMock(return_value=AuthResult(success=True, permissions={Permission.ADMIN})))
    env_auth = SimpleNamespace(authenticate=MagicMock(return_value=AuthResult(success=True, permissions={Permission.READ})))
    middleware = AuthMiddleware(hmac_auth=hmac_auth, env_auth=env_auth, require_auth=False)

    context = AuthContext(hmac_signature="sig", timestamp="123", client_id="client")
    assert middleware.authenticate(context).success is True
    hmac_auth.authenticate.assert_called_once_with(payload="", signature="sig", timestamp="123", client_id="client")

    env_only = AuthMiddleware(env_auth=env_auth, require_auth=True)
    context2 = AuthContext(token="token")
    assert env_only.authenticate(context2).success is True
    env_auth.authenticate.assert_called_once_with("token")


@pytest.mark.asyncio
async def test_auth_middleware_require_permission_sync_and_async():
    ok_result = AuthResult(success=True, permissions={Permission.READ, Permission.WRITE})
    token_auth = SimpleNamespace(authenticate=MagicMock(return_value=ok_result))
    middleware = AuthMiddleware(token_auth=token_auth, require_auth=True)

    @middleware.require_permission(Permission.READ)
    def sync_tool(*, auth_result: AuthResult) -> tuple[str, str]:
        return auth_result.token_id or "none", auth_result.role.value if auth_result.role else "none"

    @middleware.require_permission(Permission.WRITE)
    async def async_tool(*, auth_result: AuthResult) -> str:
        return auth_result.token_id or "none"

    context = AuthContext(token="secret")
    assert sync_tool(auth_context=context) == ("none", "none")
    assert await async_tool(auth_context=context) == "none"

    with pytest.raises(ValueError, match="auth_context required"):
        sync_tool()

    no_perm = AuthResult(success=True, permissions=set())
    middleware_denied = AuthMiddleware(
        token_auth=SimpleNamespace(authenticate=MagicMock(return_value=no_perm))
    )

    @middleware_denied.require_permission(Permission.READ)
    def denied_tool(*, auth_result: AuthResult) -> None:
        return None

    with pytest.raises(PermissionError, match="Permission 'read' required"):
        denied_tool(auth_context=context)

    async_denied_middleware = AuthMiddleware(
        token_auth=SimpleNamespace(
            authenticate=MagicMock(return_value=AuthResult(success=True, permissions={Permission.READ}))
        )
    )

    @async_denied_middleware.require_permission(Permission.WRITE)
    async def denied_async_permission(*, auth_result: AuthResult) -> None:
        return None

    with pytest.raises(PermissionError, match="Permission 'write' required"):
        await denied_async_permission(auth_context=context)

    @middleware.require_permission(Permission.READ)
    async def denied_async_tool(*, auth_result: AuthResult) -> None:
        return None

    denied_middleware = AuthMiddleware(
        token_auth=SimpleNamespace(authenticate=MagicMock(return_value=AuthResult(success=False, error_message="denied")))
    )

    @denied_middleware.require_permission(Permission.READ)
    async def auth_failed_async(*, auth_result: AuthResult) -> None:
        return None

    with pytest.raises(ValueError, match="auth_context required"):
        await denied_async_tool()

    with pytest.raises(PermissionError, match="Authentication required"):
        await auth_failed_async(auth_context=context)

    sync_failed_middleware = AuthMiddleware(
        token_auth=SimpleNamespace(authenticate=MagicMock(return_value=AuthResult(success=False, error_message="sync denied")))
    )

    @sync_failed_middleware.require_permission(Permission.READ)
    def sync_auth_failed(*, auth_result: AuthResult) -> None:
        return None

    with pytest.raises(PermissionError, match="Authentication required"):
        sync_auth_failed(auth_context=context)


@pytest.mark.asyncio
async def test_require_dhara_auth_paths(monkeypatch):
    cfg = SimpleNamespace(enabled=True, secret="secret")
    monkeypatch.setattr(auth_module, "_get_config", lambda: cfg)

    payload = SimpleNamespace(issuer="svc-a", subject="user-1", jti="jti-1")
    events: list[object] = []
    monkeypatch.setattr(auth_module, "_verify_token", lambda *a, **k: payload)
    monkeypatch.setattr(auth_module._audit, "emit", lambda event: events.append(event))

    @require_dhara_auth(DharaPermission.CHECKPOINT)
    async def tool(**kwargs):
        return kwargs

    result = await tool(__auth_token__="token")
    assert result == {}
    assert events and events[0].permission == Permission.READ

    @require_dhara_auth(Permission.WRITE)
    async def write_tool(**kwargs):
        return kwargs

    await write_tool(__auth_token__="token")
    assert events[-1].permission == Permission.WRITE

    @require_dhara_auth()
    async def disabled_tool(**kwargs):
        return kwargs

    monkeypatch.setattr(auth_module, "_get_config", lambda: SimpleNamespace(enabled=False, secret="secret"))
    assert await disabled_tool() == {}

    monkeypatch.setattr(auth_module, "_get_config", lambda: SimpleNamespace(enabled=True, secret="secret"))

    @require_dhara_auth()
    async def missing_token_tool(**kwargs):
        return kwargs

    assert await missing_token_tool() == {
        "error": "Authentication required",
        "error_code": "AUTH_REQUIRED",
    }

    def raise_auth_error(*args, **kwargs):
        raise AuthError("bad token")

    monkeypatch.setattr(auth_module, "_verify_token", raise_auth_error)

    @require_dhara_auth()
    async def failed_tool(**kwargs):
        return kwargs

    assert await failed_tool(__auth_token__="token") == {
        "error": "bad token",
        "error_code": "AUTH_FAILED",
    }


@pytest.mark.asyncio
async def test_require_dhara_auth_missing_context_and_invalid_permission(monkeypatch):
    cfg = SimpleNamespace(enabled=True, secret="secret")
    monkeypatch.setattr(auth_module, "_get_config", lambda: cfg)
    monkeypatch.setattr(auth_module, "_verify_token", lambda *a, **k: SimpleNamespace(issuer="svc", subject="sub", jti="jti"))
    monkeypatch.setattr(auth_module._audit, "emit", lambda event: None)

    @require_dhara_auth(Permission.WRITE)
    async def write_only(**kwargs):
        return kwargs

    assert await write_only(__auth_token__="token") == {}

    @require_dhara_auth()
    async def missing_context(**kwargs):
        return kwargs

    assert await missing_context(__auth_token__="token") == {}

    monkeypatch.setattr(auth_module, "_get_config", lambda: SimpleNamespace(enabled=True, secret="secret"))
    monkeypatch.setattr(auth_module, "_verify_token", lambda *a, **k: SimpleNamespace(issuer="svc", subject="sub", jti="jti"))

    @require_dhara_auth()
    async def no_token_again(**kwargs):
        return kwargs

    assert await no_token_again() == {
        "error": "Authentication required",
        "error_code": "AUTH_REQUIRED",
    }


def test_audit_log_without_context_or_extra(monkeypatch):
    captured = []
    middleware = AuthMiddleware(audit_log=SimpleNamespace(info=lambda msg: captured.append(msg)))
    middleware._audit_log("event", None, None)
    assert captured and "AUDIT:" in captured[0]
