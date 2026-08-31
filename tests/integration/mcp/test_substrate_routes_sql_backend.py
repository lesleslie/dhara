"""SQL-backed persistence tests for substrate_routes (Workstream C).

Closes Workstream C from the 2026-06 Dhara Substrate plans:
``dhara/mcp/substrate_routes.py`` currently writes to an inline
``PersistentMapping`` dict with a TODO to migrate to the migration 0001
SQL tables. These tests assert the SQL tables
(``adapters_active_settings_version``,
``tenants_context_versions``,
``workflows_progress_snapshots``) are populated on POST and queried
on GET.

Falls under TDD discipline: each test below should fail against the
current implementation (writes to dict, not SQL) and pass after the
substrate_routes.py refactor wires handlers through the SQL backend.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import httpx2 as httpx
import pytest

_MIGRATION_0001 = (
    Path(__file__).parents[3] / "dhara" / "migrations" / "sql" / "0001_initial.sql"
).read_text()


@pytest.fixture
async def sql_backend() -> Any:
    """Fresh in-memory DuckDB per test with migration 0001 applied."""
    conn = duckdb.connect(":memory:")
    conn.execute(_MIGRATION_0001)
    try:
        yield conn
    finally:
        conn.close()


def _build_app(sql_backend: Any) -> Any:
    """Minimal FastMCP app wired to a real SQL backend.

    Substrate routes currently take only a ``Connection``; the SQL
    backend will be threaded through ``register_substrate_routes``
    once Workstream C is closed. For now we pass it positionally
    via the new ``sql_backend`` kwarg.
    """
    from fastmcp import FastMCP

    from dhara.mcp.substrate_routes import register_substrate_routes

    server = FastMCP(name="test-substrate-sql")

    class _FakeConnection:
        def get_root(self) -> Any:  # pragma: no cover - not exercised
            raise NotImplementedError("SQL backend in use")

    register_substrate_routes(
        server,
        _FakeConnection(),  # type: ignore[arg-type]
        sql_backend=sql_backend,
    )
    return server


@pytest.fixture
async def http_client(sql_backend: Any) -> Any:
    """Async httpx client against the FastMCP ASGI app."""
    server = _build_app(sql_backend)
    app = server.http_app(transport="http")
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    try:
        yield client
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# adapters_active_settings_version
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_active_settings_version_inserts_sql_row(
    http_client: Any, sql_backend: Any
) -> None:
    """POST /adapters/{id}/active-settings-version must INSERT into SQL table."""
    response = await http_client.post(
        "/adapters/adapter-1/active-settings-version",
        json={"version": "v1.0.0", "source": "test"},
    )
    assert response.status_code == 200, response.text

    rows = sql_backend.execute(
        "SELECT version_id, adapter_name, tenant_id, settings_blob "
        "FROM adapters_active_settings_version WHERE adapter_name = 'adapter-1'"
    ).fetchall()
    assert len(rows) == 1, (
        f"expected 1 row in adapters_active_settings_version, got {len(rows)}"
    )
    version_id, adapter_name, _tenant_id, settings_blob = rows[0]
    assert adapter_name == "adapter-1"
    assert version_id  # non-empty ULID/UUID
    assert "v1.0.0" in settings_blob


@pytest.mark.asyncio
async def test_get_active_settings_version_reads_from_sql(
    http_client: Any, sql_backend: Any
) -> None:
    """GET must SELECT from SQL table; seeded row should round-trip."""
    sql_backend.execute(
        "INSERT INTO adapters_active_settings_version "
        "(version_id, adapter_name, tenant_id, settings_blob, activated_by) "
        "VALUES ('seed-1', 'adapter-2', 'tenant-x', '{\"version\":\"seed-v\"}', 'tester')"
    )
    response = await http_client.get("/adapters/adapter-2/active-settings-version")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["adapter_id"] == "adapter-2"
    assert body["version"] == "seed-v"
    assert body["total"] >= 1


# ---------------------------------------------------------------------------
# tenants_context_versions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_context_versions_inserts_sql_row(
    http_client: Any, sql_backend: Any
) -> None:
    """POST /tenants/{id}/context-versions must INSERT into SQL table."""
    response = await http_client.post(
        "/tenants/tenant-9/context-versions",
        json={"version": "ctx-v1", "kind": "release"},
    )
    assert response.status_code == 200, response.text

    rows = sql_backend.execute(
        "SELECT version_id, tenant_id, context_blob "
        "FROM tenants_context_versions WHERE tenant_id = 'tenant-9'"
    ).fetchall()
    assert len(rows) == 1, (
        f"expected 1 row in tenants_context_versions, got {len(rows)}"
    )
    _version_id, tenant_id, context_blob = rows[0]
    assert tenant_id == "tenant-9"
    assert "ctx-v1" in context_blob


# ---------------------------------------------------------------------------
# workflows_progress_snapshots
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_progress_snapshots_inserts_sql_row(
    http_client: Any, sql_backend: Any
) -> None:
    """POST /workflows/{id}/progress-snapshots must INSERT into SQL table."""
    response = await http_client.post(
        "/workflows/wf-42/progress-snapshots",
        json={"stage": "build", "percent": 75, "note": "phase 3"},
    )
    assert response.status_code == 200, response.text

    rows = sql_backend.execute(
        "SELECT snapshot_id, workflow_id, step, progress_percent "
        "FROM workflows_progress_snapshots WHERE workflow_id = 'wf-42'"
    ).fetchall()
    assert len(rows) == 1, (
        f"expected 1 row in workflows_progress_snapshots, got {len(rows)}"
    )
    _snapshot_id, workflow_id, step, progress_percent = rows[0]
    assert workflow_id == "wf-42"
    assert step == "build"
    assert progress_percent == 75.0
