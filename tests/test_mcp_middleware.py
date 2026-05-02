"""Tests for dhara.mcp.middleware — MCPMiddleware, RateLimiter, RequestContext."""

from __future__ import annotations

import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dhara.mcp.auth import AuthContext, AuthMiddleware, AuthResult, Permission, Role
from dhara.mcp.middleware import (
    MCPRequest,
    MCPResponse,
    MCPMiddleware,
    RateLimiter,
    RequestContext,
    create_auth_context_from_request,
)


# ===========================================================================
# MCPRequest
# ===========================================================================


class TestMCPRequest:
    def test_defaults(self):
        req = MCPRequest(method="test_method", params={"key": "val"})
        assert req.method == "test_method"
        assert req.params == {"key": "val"}
        assert req.request_id is None
        assert req.auth_token is None
        assert req.timestamp > 0

    def test_with_all_fields(self):
        req = MCPRequest(
            method="tools/call",
            params={"name": "test"},
            request_id="req-123",
            auth_token="tok",
            auth_hmac="sig",
            auth_timestamp="ts",
            auth_client_id="c1",
        )
        assert req.request_id == "req-123"
        assert req.auth_token == "tok"
        assert req.auth_hmac == "sig"


# ===========================================================================
# MCPResponse
# ===========================================================================


class TestMCPResponse:
    def test_success_response(self):
        resp = MCPResponse(success=True, result={"data": 42})
        assert resp.success is True
        assert resp.result == {"data": 42}
        assert resp.error is None
        assert resp.duration_ms == 0.0

    def test_error_response(self):
        resp = MCPResponse(success=False, error="something failed")
        assert not resp.success
        assert resp.error == "something failed"
        assert resp.result is None


# ===========================================================================
# MCPMiddleware Init
# ===========================================================================


class TestMCPMiddlewareInit:
    def test_defaults(self):
        mw = MCPMiddleware()
        assert mw.auth_middleware is None
        assert mw.enable_logging is True
        assert mw.enable_metrics is True
        assert mw._request_count == 0
        assert mw._error_count == 0

    def test_with_auth(self):
        auth = MagicMock(spec=AuthMiddleware)
        mw = MCPMiddleware(auth_middleware=auth)
        assert mw.auth_middleware is auth

    def test_logging_disabled(self):
        mw = MCPMiddleware(enable_logging=False)
        assert mw.enable_logging is False

    def test_metrics_disabled(self):
        mw = MCPMiddleware(enable_metrics=False)
        assert mw.enable_metrics is False

    def test_default_tool_permissions(self):
        mw = MCPMiddleware()
        assert mw.get_required_permission("store_adapter") == Permission.WRITE
        assert mw.get_required_permission("get_adapter") == Permission.READ
        assert mw.get_required_permission("durus_get") == Permission.READ
        assert mw.get_required_permission("durus_set") == Permission.WRITE
        assert mw.get_required_permission("unknown_tool") is None


# ===========================================================================
# Tool permissions
# ===========================================================================


class TestToolPermissions:
    def test_get_required_permission(self):
        mw = MCPMiddleware()
        assert mw.get_required_permission("store_adapter") == Permission.WRITE
        assert mw.get_required_permission("nonexistent") is None

    def test_set_tool_permission(self):
        mw = MCPMiddleware()
        mw.set_tool_permission("custom_tool", Permission.ADMIN)
        assert mw.get_required_permission("custom_tool") == Permission.ADMIN


# ===========================================================================
# process_request
# ===========================================================================


class TestProcessRequest:
    def test_no_auth_middleware(self):
        mw = MCPMiddleware(auth_middleware=None)
        req = MCPRequest(method="test", params={})
        result_req, result_auth = asyncio.get_event_loop().run_until_complete(
            mw.process_request(req)
        )
        assert result_req is req
        assert result_auth is None
        assert mw._request_count == 1

    def test_auth_success(self):
        mock_token_auth = MagicMock()
        mock_token_auth.check_rate_limit = AsyncMock(return_value=True)
        auth = AuthMiddleware(require_auth=False, token_auth=mock_token_auth)
        auth.authenticate = MagicMock(
            return_value=AuthResult(
                success=True, token_id="t1", role=Role.READONLY
            )
        )

        mw = MCPMiddleware(auth_middleware=auth)
        req = MCPRequest(method="test", params={})
        result_req, result_auth = asyncio.get_event_loop().run_until_complete(
            mw.process_request(req)
        )
        assert result_auth.success
        assert mw._request_count == 1

    def test_auth_failure(self):
        auth = AuthMiddleware(require_auth=False)
        auth.authenticate = MagicMock(
            return_value=AuthResult(
                success=False, error_message="bad token"
            )
        )

        mw = MCPMiddleware(auth_middleware=auth)
        req = MCPRequest(method="test", params={})
        result_req, result_auth = asyncio.get_event_loop().run_until_complete(
            mw.process_request(req)
        )
        assert not result_auth.success
        assert mw._auth_failure_count == 1
        assert mw._request_count == 0

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self):
        mock_token_auth = MagicMock()
        mock_token_auth.check_rate_limit = AsyncMock(return_value=False)
        auth = AuthMiddleware(require_auth=False, token_auth=mock_token_auth)
        auth.authenticate = MagicMock(
            return_value=AuthResult(
                success=True, token_id="t1", role=Role.READONLY
            )
        )

        mw = MCPMiddleware(auth_middleware=auth)
        req = MCPRequest(method="test", params={})
        result_req, result_auth = await mw.process_request(req)
        assert not result_auth.success
        assert result_auth.error_message == "Rate limit exceeded"
        assert mw._request_count == 0

    def test_no_token_id_skips_rate_limit(self):
        auth = AuthMiddleware(require_auth=False)
        auth.authenticate = MagicMock(
            return_value=AuthResult(
                success=True, token_id=None, role=Role.READONLY
            )
        )

        mw = MCPMiddleware(auth_middleware=auth)
        req = MCPRequest(method="test", params={})
        result_req, result_auth = asyncio.get_event_loop().run_until_complete(
            mw.process_request(req)
        )
        assert result_auth.success
        assert mw._request_count == 1


# ===========================================================================
# process_response
# ===========================================================================


class TestProcessResponse:
    def test_sets_duration(self):
        mw = MCPMiddleware()
        req = MCPRequest(method="test", params={})
        resp = MCPResponse(success=True)
        mw.process_response(req, resp)
        assert resp.duration_ms > 0

    def test_preserves_existing_duration(self):
        mw = MCPMiddleware()
        req = MCPRequest(method="test", params={})
        resp = MCPResponse(success=True, duration_ms=42.0)
        mw.process_response(req, resp)
        assert resp.duration_ms == 42.0

    def test_tracks_errors(self):
        mw = MCPMiddleware()
        req = MCPRequest(method="test", params={})
        resp = MCPResponse(success=False, error="fail")
        mw.process_response(req, resp)
        assert mw._error_count == 1

    def test_tracks_durations(self):
        mw = MCPMiddleware()
        req = MCPRequest(method="test", params={})
        resp = MCPResponse(success=True)
        mw.process_response(req, resp)
        assert len(mw._request_durations) == 1


# ===========================================================================
# check_tool_permission
# ===========================================================================


class TestCheckToolPermission:
    def test_no_permission_required(self):
        mw = MCPMiddleware()
        auth = AuthResult(success=True, permissions={Permission.ADMIN})
        assert mw.check_tool_permission("unknown", auth) is True

    def test_failed_auth_denied(self):
        mw = MCPMiddleware()
        auth = AuthResult(success=False)
        assert mw.check_tool_permission("store_adapter", auth) is False

    def test_no_auth_middleware_allows(self):
        mw = MCPMiddleware(auth_middleware=None)
        auth = AuthResult(success=True)
        assert mw.check_tool_permission("store_adapter", auth) is True

    def test_permission_granted(self):
        auth_mw = AuthMiddleware(require_auth=False)
        mw = MCPMiddleware(auth_middleware=auth_mw)
        auth = AuthResult(
            success=True, permissions=Permission.all_permissions()
        )
        assert mw.check_tool_permission("store_adapter", auth) is True

    def test_permission_denied(self):
        auth_mw = AuthMiddleware(require_auth=False)
        mw = MCPMiddleware(auth_middleware=auth_mw)
        auth = AuthResult(success=True, permissions=Permission.read_permissions())
        assert mw.check_tool_permission("store_adapter", auth) is False


# ===========================================================================
# Metrics
# ===========================================================================


class TestMetrics:
    def test_get_metrics_empty(self):
        mw = MCPMiddleware()
        metrics = mw.get_metrics()
        assert metrics["request_count"] == 0
        assert metrics["error_count"] == 0
        assert metrics["avg_duration_ms"] == 0.0
        assert metrics["error_rate"] == 0.0

    def test_get_metrics_with_data(self):
        mw = MCPMiddleware()
        mw._request_count = 10
        mw._error_count = 2
        mw._request_durations = [10.0, 20.0, 30.0]
        metrics = mw.get_metrics()
        assert metrics["request_count"] == 10
        assert metrics["error_count"] == 2
        assert metrics["avg_duration_ms"] == 20.0
        assert metrics["error_rate"] == 0.2

    def test_reset_metrics(self):
        mw = MCPMiddleware()
        mw._request_count = 5
        mw._error_count = 3
        mw._auth_failure_count = 2
        mw._request_durations = [1.0, 2.0]
        mw.reset_metrics()
        assert mw._request_count == 0
        assert mw._error_count == 0
        assert mw._auth_failure_count == 0
        assert mw._request_durations == []


# ===========================================================================
# RateLimiter
# ===========================================================================


class TestRateLimiterInit:
    def test_defaults(self):
        rl = RateLimiter()
        assert rl.requests_per_second == 10.0
        assert rl.burst_size == 100
        assert rl._buckets == {}

    def test_custom_config(self):
        rl = RateLimiter(requests_per_second=5.0, burst_size=50)
        assert rl.requests_per_second == 5.0
        assert rl.burst_size == 50


class TestRateLimiterAcquire:
    @pytest.mark.asyncio
    async def test_first_request_succeeds(self):
        rl = RateLimiter()
        result = await rl.acquire("key1")
        assert result is True

    @pytest.mark.asyncio
    async def test_burst_exhausted_fails(self):
        rl = RateLimiter(requests_per_second=0, burst_size=2)
        # First call initializes bucket (returns True without consuming)
        assert await rl.acquire("key1") is True
        # Second call consumes 1 token (2 -> 1)
        assert await rl.acquire("key1") is True
        # Third call consumes 1 token (1 -> 0)
        assert await rl.acquire("key1") is True
        # Fourth call fails (0 tokens available)
        assert await rl.acquire("key1") is False

    @pytest.mark.asyncio
    async def test_separate_keys(self):
        rl = RateLimiter(burst_size=1)
        r1 = await rl.acquire("a")
        r2 = await rl.acquire("b")
        assert r1 is True
        assert r2 is True


class TestRateLimiterAvailableTokens:
    def test_new_key_returns_burst(self):
        rl = RateLimiter(burst_size=50)
        assert rl.get_available_tokens("new") == 50

    @pytest.mark.asyncio
    async def test_existing_key_calculates(self):
        rl = RateLimiter(requests_per_second=10, burst_size=100)
        # First acquire initializes bucket (returns True, no tokens consumed)
        await rl.acquire("k")
        # Second acquire consumes 1 token (100 -> 99)
        await rl.acquire("k", tokens=30)
        available = rl.get_available_tokens("k")
        # After init + consume 30: 100 - 30 = 70 (plus small time-based refill)
        assert available <= 100  # capped at burst_size
        assert available >= 69  # ~70 minus tiny elapsed time


# ===========================================================================
# RequestContext
# ===========================================================================


class TestRequestContext:
    def test_init(self):
        ctx = RequestContext(request_id="r1", method="test", params={})
        assert ctx.request_id == "r1"
        assert ctx.method == "test"
        assert ctx.params == {}
        assert ctx.auth_result is None
        assert ctx.metadata == {}

    def test_duration(self):
        ctx = RequestContext(request_id="r1", method="test", params={})
        time.sleep(0.01)
        assert ctx.duration >= 0.01

    def test_duration_ms(self):
        ctx = RequestContext(request_id="r1", method="test", params={})
        time.sleep(0.01)
        assert ctx.duration_ms >= 10


# ===========================================================================
# create_auth_context_from_request
# ===========================================================================


class TestCreateAuthContext:
    def test_creates_context(self):
        req = MCPRequest(
            method="test",
            params={},
            auth_token="tok",
            auth_hmac="sig",
            auth_timestamp="ts",
            auth_client_id="c1",
        )
        ctx = create_auth_context_from_request(req)
        assert isinstance(ctx, AuthContext)
        assert ctx.token == "tok"
        assert ctx.hmac_signature == "sig"
        assert ctx.timestamp == "ts"
        assert ctx.client_id == "c1"
