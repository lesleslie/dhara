"""Integration tests for D-LOCK REST routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import httpx
import pytest
from fastmcp import FastMCP

from dhara.lock.routes import register_lock_routes
from dhara.lock.sql import SQLBackendLock

_MIGRATION_0003 = (
    Path(__file__).parents[3] / "dhara" / "migrations" / "sql" / "0003_locks.sql"
).read_text()


@pytest.fixture
async def sql_backend() -> Any:
    conn = duckdb.connect(":memory:")
    conn.execute(_MIGRATION_0003)
    try:
        yield conn
    finally:
        conn.close()


def _build_app(sql_backend: Any) -> Any:
    server = FastMCP(name="test-lock-routes")
    register_lock_routes(server, sql_backend)
    return server


@pytest.fixture
async def http_client(sql_backend: Any) -> Any:
    server = _build_app(sql_backend)
    app = server.http_app(transport="http")
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    try:
        yield client
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_post_try_acquire_returns_handle(http_client: Any) -> None:
    response = await http_client.post(
        "/locks/r1", json={"owner_token": "t1", "ttl_seconds": 30}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lock_key"] == "r1"
    assert body["owner_token"] == "t1"


@pytest.mark.asyncio
async def test_post_try_acquire_returns_409_duplicate_permanent(http_client: Any) -> None:
    """H11 fix: duplicate-permanent returns reason=duplicate_permanent."""
    response = await http_client.post("/locks/r2", json={"owner_token": "t", "permanent": True})
    assert response.status_code == 200
    response = await http_client.post("/locks/r2", json={"owner_token": "t2", "permanent": True})
    assert response.status_code == 409
    body = response.json()
    assert body["reason"] == "duplicate_permanent"
    assert body["current_owner_token"] == "t"  # H4 fix


@pytest.mark.asyncio
async def test_post_try_acquire_returns_409_lock_lost_when_lease_held(http_client: Any) -> None:
    response = await http_client.post("/locks/r3", json={"owner_token": "a", "ttl_seconds": 30})
    assert response.status_code == 200
    response = await http_client.post("/locks/r3", json={"owner_token": "b", "ttl_seconds": 30})
    assert response.status_code == 409
    body = response.json()
    assert body["reason"] == "lock_lost"
    assert body["current_owner_token"] == "a"


@pytest.mark.asyncio
async def test_post_heartbeat_with_header(http_client: Any) -> None:
    await http_client.post("/locks/r4", json={"owner_token": "owner", "ttl_seconds": 30})
    response = await http_client.post(
        "/locks/r4/heartbeat", json={"extend_seconds": 60},
        headers={"X-Owner-Token": "owner"},
    )
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_post_heartbeat_returns_409_lock_permanent_on_permanent_lock(http_client: Any) -> None:
    """H8 fix: heartbeat on permanent lock returns 409 with reason=lock_permanent."""
    await http_client.post("/locks/r5", json={"owner_token": "owner", "permanent": True})
    response = await http_client.post(
        "/locks/r5/heartbeat", json={"extend_seconds": 60},
        headers={"X-Owner-Token": "owner"},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["reason"] == "lock_permanent"


@pytest.mark.asyncio
async def test_delete_returns_409_lock_permanent_on_permanent_lock(http_client: Any) -> None:
    """H9 fix: DELETE on permanent lock returns 409 with reason=lock_permanent."""
    await http_client.post("/locks/r6", json={"owner_token": "owner", "permanent": True})
    response = await http_client.request(
        "DELETE", "/locks/r6", headers={"X-Owner-Token": "owner"}
    )
    assert response.status_code == 409
    body = response.json()
    assert body["reason"] == "lock_permanent"


@pytest.mark.asyncio
async def test_delete_with_header(http_client: Any) -> None:
    await http_client.post("/locks/r7", json={"owner_token": "owner", "ttl_seconds": 30})
    response = await http_client.request(
        "DELETE", "/locks/r7", headers={"X-Owner-Token": "owner"}
    )
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_get_returns_handle(http_client: Any) -> None:
    await http_client.post("/locks/r8", json={"owner_token": "x", "ttl_seconds": 30})
    response = await http_client.get("/locks/r8")
    assert response.status_code == 200
    assert response.json()["lock_key"] == "r8"


@pytest.mark.asyncio
async def test_get_returns_404(http_client: Any) -> None:
    response = await http_client.get("/locks/nonexistent")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_list_with_prefix(http_client: Any) -> None:
    await http_client.post("/locks/ns:a:1", json={"owner_token": "x"})
    await http_client.post("/locks/ns:a:2", json={"owner_token": "x"})
    await http_client.post("/locks/ns:b:1", json={"owner_token": "x"})
    response = await http_client.get("/locks", params={"prefix": "ns:a:"})
    assert response.status_code == 200
    keys = [h["lock_key"] for h in response.json()]
    assert set(keys) == {"ns:a:1", "ns:a:2"}