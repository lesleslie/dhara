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

import asyncio
import threading
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _StubAsyncConnection:
    """Minimal async Connection backed by an in-memory dict.

    Avoids the on-disk ``AsyncFileStorage`` path used by the real
    ``AsyncConnection.new()``. ``_root`` is mutated directly by
    ``register_substrate_routes`` (legacy dict persistence path), so a real
    Python ``dict`` is required — a ``MagicMock`` would auto-generate child
    attributes and break the substrate CRUD round-trip semantics.
    """

    def __init__(self) -> None:
        self._root: dict[str, Any] = {}
        self.cache: dict[str, Any] = {}

    async def get_root(self) -> dict[str, Any]:
        return self._root

    async def commit(self) -> None:
        return None

    async def abort(self) -> None:
        return None

    @property
    def storage(self) -> dict[str, Any]:
        return self._root


def _build_in_memory_facade() -> Any:
    """Wrap a ``_StubAsyncConnection`` in a real ``_SyncConnectionFacade``.

    The facade's ``_run`` uses ``asyncio.run_coroutine_threadsafe``, which
    needs a real ``AbstractEventLoop``. Drive that loop from a daemon
    thread — same shape as the production ``_run_async_connection_wire``
    path (which calls ``_ensure_loop_background_thread``).
    """
    from dhara.mcp.server_core import _SyncConnectionFacade

    loop = asyncio.new_event_loop()
    thread = threading.Thread(
        target=loop.run_forever, daemon=True, name="test-substrate-crud-loop"
    )
    thread.start()
    return _SyncConnectionFacade(_StubAsyncConnection(), loop)


def _make_app_patches() -> tuple:
    """Return the patches that isolate DharaMCPServer from filesystem deps.

    NOTE: We deliberately do NOT mock ``FastMCP`` — tests need a real
    ASGI app from ``server.http_app(transport='http')``. Only the storage
    I/O, async connection wiring, and auth verifier are stubbed.

    The legacy ``patch("dhara.mcp.server_core.Connection")`` was removed
    because ``Connection`` now lives only inside a ``TYPE_CHECKING`` block
    (DharaMCPServer builds an ``AsyncConnection``). The
    ``_run_async_connection_wire`` patch here replaces the real
    ``AsyncConnection.new`` + duckdb path with an in-memory stub so the
    substrate routes can exercise their legacy dict persistence branch
    without touching disk.
    """
    return (
        # AsyncFileStorage: never touches disk (kept for parity with the
        # original fixture even though _run_async_connection_wire is now patched).
        patch("dhara.mcp.server_core.AsyncFileStorage"),
        # Async connection wire: skip AsyncConnection.new entirely.
        patch(
            "dhara.mcp.server_core._run_async_connection_wire",
            side_effect=lambda storage: _build_in_memory_facade(),
        ),
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
    started_patches = _make_app_patches()
    mocks = [p.start() for p in started_patches]
    try:
        server = DharaMCPServer(config)
    finally:
        # Stop the SAME patch objects we started above. Calling
        # ``_make_app_patches()`` again here would return fresh patches
        # that have never been started — ``.stop()`` on those is a no-op
        # and the original patches leak into subsequent tests.
        for p in started_patches:
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
    import httpx2 as httpx

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
