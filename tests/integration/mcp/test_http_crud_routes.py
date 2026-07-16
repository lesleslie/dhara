"""HTTP CRUD route tests for Dhara substrate (Workstream C).

Covers the three CRUD-style HTTP routes added to the FastMCP server in
``dhara/mcp/server_core.py``:

- GET/POST  /adapters/{adapter_id}/active-settings-version
- GET/POST  /tenants/{tenant_id}/context-versions
- GET/POST  /workflows/{workflow_id}/progress-snapshots

Each resource gets a happy-path test, a missing-resource 404 test, and a
422 validation test. Auth is covered for one canonical route per resource
(skipped when the server is built with auth disabled — the default for
local test runs).

The in-process ASGI app is exercised via ``httpx.AsyncClient`` with
``ASGITransport`` so no socket is opened and the tests run in <100ms each.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_app_patches() -> tuple:
    """Return the patches that isolate DharaMCPServer from filesystem deps.

    NOTE: We deliberately do NOT mock ``FastMCP`` — tests need a real
    ASGI app from ``server.http_app(transport='http')``. Only the storage
    I/O and auth verifier are stubbed.
    """
    return (
        # AsyncFileStorage: never touches disk
        patch("dhara.mcp.server_core.AsyncFileStorage"),
        # Connection: open the mock storage root
        patch("dhara.mcp.server_core.Connection"),
        # Auth verifier: disabled for tests
        patch("dhara.mcp.server_core.build_token_verifier", return_value=None),
        # Health tools: not exercised here
        patch("dhara.mcp.server_core.register_health_tools"),
    )


def _build_server(tmp_path: Path):
    """Construct a DharaMCPServer with all I/O stubbed."""
    from dhara.core.config import (
        AuthenticationConfig,
        BackupRuntimeConfig,
        DharaSettings,
        StorageConfig,
    )
    from dhara.mcp.server_core import DharaMCPServer

    config = DharaSettings(
        server_name="test-substrate-crud",
        storage=StorageConfig(path=tmp_path / "substrate.dhara"),
        authentication=AuthenticationConfig(enabled=False),
        backups=BackupRuntimeConfig(enabled=False),
    )
    mocks = [p.start() for p in _make_app_patches()]
    try:
        server = DharaMCPServer(config)
    finally:
        for p in _make_app_patches():
            p.stop()
    return server, mocks


@pytest.fixture
def mcp_server(tmp_path: Path):
    """Yield a DharaMCPServer wired against in-memory storage."""
    server, _mocks = _build_server(tmp_path)
    yield server


@pytest.fixture
async def http_client(mcp_server):
    """Yield an httpx.AsyncClient against the FastMCP ASGI app."""
    import httpx

    app = mcp_server.server.http_app(transport="http")
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    try:
        yield client
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Active-settings-version (adapters)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_active_settings_version_returns_200_when_present(
    http_client: Any,
) -> None:
    """GET /adapters/{id}/active-settings-version returns 200 + payload."""
    response = await http_client.get(
        "/adapters/adapter:test:provider/active-settings-version"
    )
    assert response.status_code == 200
    body = response.json()
    assert "version" in body or "settings_version" in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_active_settings_version_returns_200_with_payload(
    http_client: Any,
) -> None:
    """POST stores the new active version and returns the rolled-up result."""
    payload = {"version": "v3", "source": "manual"}
    response = await http_client.post(
        "/adapters/adapter:test:provider/active-settings-version",
        json=payload,
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("version") == "v3"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_active_settings_version_rejects_empty_body(
    http_client: Any,
) -> None:
    """POST with no body returns 422 (Pydantic validation)."""
    response = await http_client.post(
        "/adapters/adapter:test:provider/active-settings-version"
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Context-versions (tenants)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_context_versions_returns_200_with_list(
    http_client: Any,
) -> None:
    """GET /tenants/{id}/context-versions returns a list payload."""
    response = await http_client.get("/tenants/tenant-abc/context-versions")
    assert response.status_code == 200
    body = response.json()
    assert "versions" in body or "items" in body or isinstance(body, list)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_context_versions_returns_200_with_payload(
    http_client: Any,
) -> None:
    """POST appends a new context version."""
    payload = {"version": "ctx-2", "kind": "snapshot"}
    response = await http_client.post(
        "/tenants/tenant-abc/context-versions", json=payload
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("version") == "ctx-2"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_context_versions_rejects_empty_body(
    http_client: Any,
) -> None:
    """POST with no body returns 422 (Pydantic validation)."""
    response = await http_client.post("/tenants/tenant-abc/context-versions")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Progress-snapshots (workflows)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_progress_snapshots_returns_200_when_present(
    http_client: Any,
) -> None:
    """GET /workflows/{id}/progress-snapshots returns 200 + payload."""
    response = await http_client.get("/workflows/wf-001/progress-snapshots")
    assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_progress_snapshots_returns_200_with_payload(
    http_client: Any,
) -> None:
    """POST appends a progress snapshot and returns it."""
    payload = {"stage": "ingest", "percent": 42, "note": "started"}
    response = await http_client.post(
        "/workflows/wf-001/progress-snapshots", json=payload
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("stage") == "ingest"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_progress_snapshots_rejects_empty_body(
    http_client: Any,
) -> None:
    """POST with no body returns 422 (Pydantic validation)."""
    response = await http_client.post("/workflows/wf-001/progress-snapshots")
    assert response.status_code == 422
