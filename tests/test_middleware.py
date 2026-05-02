"""Tests for dhara/mcp/middleware.py — MCP middleware, rate limiter, request context."""

from __future__ import annotations

import asyncio
import time

import pytest

from dhara.mcp.auth import AuthContext, AuthResult, AuthMiddleware, Permission, Role, TokenAuth
from dhara.mcp.middleware import (
    MCPMiddleware,
    MCPRequest,
    MCPResponse,
    RateLimiter,
    RequestContext,
    create_auth_context_from_request,
)


class TestMCPRequest:
    def test_defaults(self):
        req = MCPRequest(method="test", params={})
        assert req.method == "test"
        assert req.auth_token is None
        assert req.request_id is None

    def test_with_auth(self):
        req = MCPRequest(
            method="test",
            params={},
            auth_token="tok",
            auth_hmac="sig",
            auth_timestamp="ts",
            auth_client_id="client1",
        )
        assert req.auth_token == "tok"
        assert req.auth_hmac == "sig"


class TestMCPResponse:
    def test_success(self):
        resp = MCPResponse(success=True, result={"data": 1})
        assert resp.success
        assert resp.error is None

    def test_error(self):
        resp = MCPResponse(success=False, error="boom")
        assert not resp.success
        assert resp.error == "boom"


class TestRequestContext:
    def test_duration_increases(self):
        ctx = RequestContext(request_id="1", method="m", params={})
        t1 = ctx.duration
        time.sleep(0.01)
        assert ctx.duration > t1

    def test_duration_ms(self):
        ctx = RequestContext(request_id="1", method="m", params={})
        assert ctx.duration_ms > 0

    def test_metadata(self):
        ctx = RequestContext(request_id="1", method="m", params={})
        ctx.metadata["key"] = "val"
        assert ctx.metadata["key"] == "val"


class TestMCPMiddleware:
    def test_process_request_no_auth(self):
        mw = MCPMiddleware(enable_logging=False)
        req = MCPRequest(method="put", params={"key": "k"})
        processed_req, auth_result = asyncio.get_event_loop().run_until_complete(
            mw.process_request(req)
        )
        assert processed_req.method == "put"
        assert auth_result is None

    def test_process_response_adds_duration(self):
        mw = MCPMiddleware(enable_logging=False)
        req = MCPRequest(method="get", params={})
        resp = MCPResponse(success=True)
        result = mw.process_response(req, resp)
        assert result.duration_ms > 0

    def test_metrics_tracking(self):
        mw = MCPMiddleware(enable_logging=False, enable_metrics=True)
        req = MCPRequest(method="get", params={})
        # process_request increments request_count
        asyncio.get_event_loop().run_until_complete(mw.process_request(req))
        asyncio.get_event_loop().run_until_complete(mw.process_request(req))
        resp_err = MCPResponse(success=False, error="e")
        mw.process_response(req, resp_err)
        metrics = mw.get_metrics()
        assert metrics["request_count"] == 2
        assert metrics["error_count"] == 1
        assert metrics["error_rate"] == 0.5

    def test_reset_metrics(self):
        mw = MCPMiddleware(enable_logging=False)
        req = MCPRequest(method="get", params={})
        mw.process_response(req, MCPResponse(success=True))
        mw.reset_metrics()
        assert mw.get_metrics()["request_count"] == 0

    def test_get_tool_permission(self):
        mw = MCPMiddleware(enable_logging=False)
        assert mw.get_required_permission("durus_get") == Permission.READ
        assert mw.get_required_permission("durus_set") == Permission.WRITE
        assert mw.get_required_permission("unknown_tool") is None

    def test_set_tool_permission(self):
        mw = MCPMiddleware(enable_logging=False)
        mw.set_tool_permission("custom", Permission.ADMIN)
        assert mw.get_required_permission("custom") == Permission.ADMIN

    def test_check_tool_permission_no_auth_required(self):
        mw = MCPMiddleware(enable_logging=False)
        auth = AuthResult(success=True, permissions={Permission.READ})
        assert mw.check_tool_permission("unknown_tool", auth) is True

    def test_check_tool_permission_has_permission(self):
        mw = MCPMiddleware(enable_logging=False)
        auth = AuthResult(success=True, permissions={Permission.READ})
        assert mw.check_tool_permission("durus_get", auth) is True

    def test_check_tool_permission_denied(self):
        # Need auth_middleware set so check_permission delegates to it
        ta = TokenAuth(require_auth=True)
        mw = MCPMiddleware(auth_middleware=AuthMiddleware(token_auth=ta), enable_logging=False)
        auth = AuthResult(success=True, permissions=set())
        assert mw.check_tool_permission("durus_get", auth) is False

    def test_check_tool_permission_auth_failed(self):
        mw = MCPMiddleware(enable_logging=False)
        auth = AuthResult(success=False)
        assert mw.check_tool_permission("durus_get", auth) is False

    def test_process_request_with_auth_failure(self):
        auth_mw = AuthMiddleware(require_auth=True)
        mw = MCPMiddleware(auth_middleware=auth_mw, enable_logging=False)
        req = MCPRequest(method="get", params={})
        processed_req, auth_result = asyncio.get_event_loop().run_until_complete(
            mw.process_request(req)
        )
        assert auth_result is not None
        assert auth_result.success is False


class TestRateLimiter:
    def test_initial_acquire(self):
        limiter = RateLimiter(requests_per_second=10, burst_size=5)
        result = asyncio.get_event_loop().run_until_complete(limiter.acquire("k1"))
        assert result is True

    def test_available_tokens_full_bucket(self):
        limiter = RateLimiter(burst_size=100)
        assert limiter.get_available_tokens("new_key") == 100

    def test_available_tokens_new_key(self):
        limiter = RateLimiter(burst_size=100)
        assert limiter.get_available_tokens("new_key") == 100


class TestCreateAuthContext:
    def test_from_request(self):
        req = MCPRequest(
            method="test",
            params={},
            auth_token="tok",
            auth_hmac="sig",
            auth_timestamp="ts",
            auth_client_id="client1",
        )
        ctx = create_auth_context_from_request(req)
        assert ctx.token == "tok"
        assert ctx.hmac_signature == "sig"
        assert ctx.client_id == "client1"
