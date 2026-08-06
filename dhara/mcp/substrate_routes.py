"""Substrate HTTP CRUD routes for Dhara (Workstream C).

Adds three CRUD-style HTTP routes to the FastMCP app for the substrate
features described in the Dhara Substrate Implementation Plan:

- GET/POST /adapters/{adapter_id}/active-settings-version
- GET/POST /tenants/{tenant_id}/context-versions
- GET/POST /workflows/{workflow_id}/progress-snapshots

Persistence: when ``sql_backend`` is provided to
``register_substrate_routes``, the handlers INSERT/SELECT against the
migration 0001 SQL tables (``adapters_active_settings_version``,
``tenants_context_versions``, ``workflows_progress_snapshots``). When
``sql_backend`` is None, the legacy in-memory ``PersistentMapping`` root
under ``connection.get_root()["substrate"]`` is used — preserved for
the 223-line ``test_http_crud_routes.py`` contract suite that mocks the
Connection. Both paths preserve the same public HTTP shape.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from fastmcp import FastMCP
from pydantic import BaseModel, Field


class SQLBackend(Protocol):
    """Minimal contract for the substrate SQL backend.

    ``execute`` returns a cursor-like object supporting ``fetchall()``.
    DuckDB's ``DuckDBPyConnection`` satisfies this; asyncpg pool's
    ``Connection`` does via ``await conn.fetch(...)`` (callers wrap as
    needed).
    """

    def execute(self, sql: str, params: list[Any] | None = None) -> Any: ...


# ---------------------------------------------------------------------------
# Inline substrate schemas (legacy dict path — used only when no sql_backend)
# ---------------------------------------------------------------------------

_SUBSTRATE_ROOT_KEY = "substrate"


def _root(connection: Any) -> Any:
    """Return the connection root, lazily creating the substrate bucket."""
    root = connection.get_root()
    if _SUBSTRATE_ROOT_KEY not in root:
        root[_SUBSTRATE_ROOT_KEY] = {}
    return root


def _bucket(connection: Any, name: str) -> dict[str, Any]:
    """Return the named substrate bucket, creating it if missing."""
    root = _root(connection)
    sub: dict[str, Any] = dict(root[_SUBSTRATE_ROOT_KEY])
    if name not in sub:
        sub[name] = {}
    root[_SUBSTRATE_ROOT_KEY] = sub
    return sub[name]  # type: ignore[no-any-return]


class _ActiveSettingsVersionIn(BaseModel):
    version: str = Field(..., min_length=1)
    source: str | None = None
    metadata: dict[str, Any] | None = None


class _ContextVersionIn(BaseModel):
    version: str = Field(..., min_length=1)
    kind: str | None = None
    metadata: dict[str, Any] | None = None


class _ProgressSnapshotIn(BaseModel):
    stage: str = Field(..., min_length=1)
    percent: int = Field(..., ge=0, le=100)
    note: str | None = None
    metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """ISO-8601 UTC timestamp without external deps."""
    return datetime.now(UTC).isoformat()


def _read(connection: Any, resource: str, resource_id: str) -> list[dict[str, Any]]:
    """Return the list of stored records for the given resource (legacy)."""
    return _bucket(connection, resource).get(resource_id, []).copy()  # type: ignore[no-any-return]


def _store_substrate(
    connection: Any,
    resource: str,
    resource_id: str,
    payload: dict[str, Any],
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Append a new substrate record and return the persisted row (legacy)."""
    record: dict[str, Any] = {
        "id": uuid4().hex,
        "tenant_id": tenant_id,
        "created_at": _now_iso(),
        "payload": payload.copy(),
    }
    parent = _bucket(connection, resource)
    items = list(parent.get(resource_id, []))
    items.append(record)
    parent[resource_id] = items
    return record


def _json(payload: Any, status_code: int = 200) -> Any:
    """Starlette JSONResponse wrapper (matches existing route style)."""
    from starlette.responses import JSONResponse

    return JSONResponse(payload, status_code=status_code)


# ---------------------------------------------------------------------------
# SQL backend helpers
# ---------------------------------------------------------------------------


def _sql_insert_settings(
    sql_backend: SQLBackend,
    *,
    adapter_name: str,
    tenant_id: str | None,
    settings_payload: dict[str, Any],
    activated_by: str,
) -> str:
    """INSERT into adapters_active_settings_version. Return new version_id."""
    version_id = uuid4().hex
    sql_backend.execute(
        "INSERT INTO adapters_active_settings_version "
        "(version_id, adapter_name, tenant_id, settings_blob, activated_by) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            version_id,
            adapter_name,
            tenant_id or "",
            json.dumps(settings_payload),
            activated_by,
        ],
    )
    return version_id


def _sql_insert_context(
    sql_backend: SQLBackend,
    *,
    tenant_id: str,
    context_payload: dict[str, Any],
    published_by: str,
) -> str:
    """INSERT into tenants_context_versions. Return new version_id."""
    version_id = uuid4().hex
    sql_backend.execute(
        "INSERT INTO tenants_context_versions "
        "(version_id, tenant_id, context_blob, published_by) "
        "VALUES (?, ?, ?, ?)",
        [
            version_id,
            tenant_id,
            json.dumps(context_payload),
            published_by,
        ],
    )
    return version_id


def _sql_insert_progress(
    sql_backend: SQLBackend,
    *,
    workflow_id: str,
    tenant_id: str | None,
    step: str,
    progress_percent: float,
) -> str:
    """INSERT into workflows_progress_snapshots. Return new snapshot_id."""
    snapshot_id = uuid4().hex
    sql_backend.execute(
        "INSERT INTO workflows_progress_snapshots "
        "(snapshot_id, workflow_id, tenant_id, step, progress_percent) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            snapshot_id,
            workflow_id,
            tenant_id or "",
            step,
            progress_percent,
        ],
    )
    return snapshot_id


def _sql_fetch_settings(
    sql_backend: SQLBackend, adapter_id: str
) -> list[dict[str, Any]]:
    """SELECT from adapters_active_settings_version for an adapter."""
    rows = sql_backend.execute(
        "SELECT version_id, adapter_name, tenant_id, settings_blob, activated_at "
        "FROM adapters_active_settings_version WHERE adapter_name = ? "
        "ORDER BY activated_at DESC",
        [adapter_id],
    ).fetchall()
    return [
        {
            "id": row[0],
            "adapter_name": row[1],
            "tenant_id": row[2] or None,
            "settings": json.loads(row[3]),
            "activated_at": str(row[4]),
        }
        for row in rows
    ]


def _sql_fetch_context(sql_backend: SQLBackend, tenant_id: str) -> list[dict[str, Any]]:
    """SELECT from tenants_context_versions for a tenant."""
    rows = sql_backend.execute(
        "SELECT version_id, tenant_id, context_blob, published_by, published_at "
        "FROM tenants_context_versions WHERE tenant_id = ? "
        "ORDER BY published_at DESC",
        [tenant_id],
    ).fetchall()
    return [
        {
            "id": row[0],
            "tenant_id": row[1],
            "context": json.loads(row[2]),
            "published_by": row[3],
            "published_at": str(row[4]),
        }
        for row in rows
    ]


def _sql_fetch_progress(
    sql_backend: SQLBackend, workflow_id: str
) -> list[dict[str, Any]]:
    """SELECT from workflows_progress_snapshots for a workflow."""
    rows = sql_backend.execute(
        "SELECT snapshot_id, workflow_id, tenant_id, step, progress_percent, recorded_at "
        "FROM workflows_progress_snapshots WHERE workflow_id = ? "
        "ORDER BY recorded_at DESC",
        [workflow_id],
    ).fetchall()
    return [
        {
            "id": row[0],
            "workflow_id": row[1],
            "tenant_id": row[2] or None,
            "step": row[3],
            "progress_percent": row[4],
            "recorded_at": str(row[5]),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def _read_settings(
    sql_backend: SQLBackend | None,
    connection: Any,
    adapter_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read settings records (SQL or legacy). Returns ``(records, current)``.

    ``current`` is the most recent settings dict, or ``{}`` when no records
    exist — callers can use ``current.get("version")`` directly without a
    None-guard.
    """
    if sql_backend is not None:
        records = _sql_fetch_settings(sql_backend, adapter_id)
        return records, records[0]["settings"] if records else {}
    records = _read(connection, "active_settings_version", adapter_id)
    return records, records[-1]["payload"] if records else {}


def _write_settings(
    sql_backend: SQLBackend | None,
    connection: Any,
    adapter_id: str,
    parsed: _ActiveSettingsVersionIn,
) -> str:
    """Insert settings record (SQL or legacy). Return record_id."""
    if sql_backend is not None:
        return _sql_insert_settings(
            sql_backend,
            adapter_name=adapter_id,
            tenant_id=parsed.metadata.get("tenant_id") if parsed.metadata else None,
            settings_payload=parsed.model_dump(),
            activated_by="api",
        )
    record = _store_substrate(
        connection, "active_settings_version", adapter_id, parsed.model_dump()
    )
    return str(record["id"])


def _read_context_versions(
    sql_backend: SQLBackend | None,
    connection: Any,
    tenant_id: str,
) -> list[dict[str, Any]]:
    """Read context-version records (SQL or legacy)."""
    if sql_backend is not None:
        return _sql_fetch_context(sql_backend, tenant_id)
    return _read(connection, "context_versions", tenant_id)


def _write_context_version(
    sql_backend: SQLBackend | None,
    connection: Any,
    tenant_id: str,
    parsed: _ContextVersionIn,
) -> str:
    """Insert context-version record (SQL or legacy). Return record_id."""
    if sql_backend is not None:
        return _sql_insert_context(
            sql_backend,
            tenant_id=tenant_id,
            context_payload=parsed.model_dump(),
            published_by="api",
        )
    record = _store_substrate(
        connection,
        "context_versions",
        tenant_id,
        parsed.model_dump(),
        tenant_id=tenant_id,
    )
    return str(record["id"])


def _read_progress_snapshots(
    sql_backend: SQLBackend | None,
    connection: Any,
    workflow_id: str,
) -> list[dict[str, Any]]:
    """Read progress-snapshot records (SQL or legacy)."""
    if sql_backend is not None:
        return _sql_fetch_progress(sql_backend, workflow_id)
    return _read(connection, "progress_snapshots", workflow_id)


def _write_progress_snapshot(
    sql_backend: SQLBackend | None,
    connection: Any,
    workflow_id: str,
    parsed: _ProgressSnapshotIn,
) -> str:
    """Insert progress-snapshot record (SQL or legacy). Return record_id."""
    if sql_backend is not None:
        return _sql_insert_progress(
            sql_backend,
            workflow_id=workflow_id,
            tenant_id=None,
            step=parsed.stage,
            progress_percent=parsed.percent,
        )
    record = _store_substrate(
        connection, "progress_snapshots", workflow_id, parsed.model_dump()
    )
    return str(record["id"])


def register_substrate_routes(
    server: FastMCP,
    connection: Any,
    *,
    sql_backend: SQLBackend | None = None,
) -> None:
    """Register the three substrate CRUD route sets on the FastMCP app.

    Args:
        server: The ``FastMCP`` instance to attach routes to.
        connection: A Dhara ``Connection`` for legacy dict persistence.
        sql_backend: Optional SQL backend (DuckDB / asyncpg). When
            provided, the routes INSERT/SELECT against migration 0001
            tables instead of the inline dict. When None, the legacy
            dict path is used.
    """

    @server.custom_route(
        "/adapters/{adapter_id}/active-settings-version", methods=["GET"]
    )
    async def get_active_settings_version(request: Any) -> Any:
        from starlette.responses import JSONResponse

        adapter_id = request.path_params["adapter_id"]
        records, current = _read_settings(sql_backend, connection, adapter_id)
        body: dict[str, Any] = {
            "adapter_id": adapter_id,
            "version": current.get("version"),
            "settings_version": current.get("version"),
            "history": records,
            "total": len(records),
        }
        return JSONResponse(body, status_code=200)

    @server.custom_route(
        "/adapters/{adapter_id}/active-settings-version", methods=["POST"]
    )
    async def post_active_settings_version(request: Any) -> Any:
        adapter_id = request.path_params["adapter_id"]
        parsed = await _parse_json_body(request, _ActiveSettingsVersionIn)
        if not isinstance(parsed, _ActiveSettingsVersionIn):
            return parsed
        record_id = _write_settings(sql_backend, connection, adapter_id, parsed)
        body = {
            "adapter_id": adapter_id,
            "version": parsed.version,
            "record_id": record_id,
        }
        return _json(body, status_code=200)

    @server.custom_route("/tenants/{tenant_id}/context-versions", methods=["GET"])
    async def get_context_versions(request: Any) -> Any:
        from starlette.responses import JSONResponse

        tenant_id = request.path_params["tenant_id"]
        records = _read_context_versions(sql_backend, connection, tenant_id)
        versions = (
            [r["context"] for r in records]
            if sql_backend is not None
            else [r["payload"] for r in records]
        )
        body = {
            "tenant_id": tenant_id,
            "versions": versions,
            "items": records,
            "total": len(records),
        }
        return JSONResponse(body, status_code=200)

    @server.custom_route("/tenants/{tenant_id}/context-versions", methods=["POST"])
    async def post_context_versions(request: Any) -> Any:
        tenant_id = request.path_params["tenant_id"]
        parsed = await _parse_json_body(request, _ContextVersionIn)
        if not isinstance(parsed, _ContextVersionIn):
            return parsed
        record_id = _write_context_version(sql_backend, connection, tenant_id, parsed)
        body = {
            "tenant_id": tenant_id,
            "version": parsed.version,
            "record_id": record_id,
        }
        return _json(body, status_code=200)

    @server.custom_route("/workflows/{workflow_id}/progress-snapshots", methods=["GET"])
    async def get_progress_snapshots(request: Any) -> Any:
        from starlette.responses import JSONResponse

        workflow_id = request.path_params["workflow_id"]
        records = _read_progress_snapshots(sql_backend, connection, workflow_id)
        snapshots = (
            records.copy()
            if sql_backend is not None
            else [r["payload"] for r in records]
        )
        body = {
            "workflow_id": workflow_id,
            "snapshots": snapshots,
            "items": records,
            "total": len(records),
        }
        return JSONResponse(body, status_code=200)

    @server.custom_route(
        "/workflows/{workflow_id}/progress-snapshots", methods=["POST"]
    )
    async def post_progress_snapshots(request: Any) -> Any:
        workflow_id = request.path_params["workflow_id"]
        parsed = await _parse_json_body(request, _ProgressSnapshotIn)
        if not isinstance(parsed, _ProgressSnapshotIn):
            return parsed
        record_id = _write_progress_snapshot(
            sql_backend, connection, workflow_id, parsed
        )
        body = {
            "workflow_id": workflow_id,
            "stage": parsed.stage,
            "percent": parsed.percent,
            "record_id": record_id,
        }
        return _json(body, status_code=200)


async def _parse_json_body(request: Any, model_cls: type[BaseModel]) -> BaseModel | Any:
    """Parse and validate a JSON request body.

    Returns the parsed Pydantic instance on success, or a Starlette
    ``JSONResponse`` (with status 422) on any failure mode the caller
    should return directly. The caller distinguishes the two via
    ``isinstance(parsed, model_cls)``.
    """
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001  # REST body parser → HTTP 422
        data = None
    if not isinstance(data, dict):
        return _json(
            {
                "error": "validation failed",
                "details": "body must be a JSON object with required fields",
            },
            status_code=422,
        )
    try:
        return model_cls(**data)
    except Exception as exc:  # noqa: BLE001  # REST body parser → HTTP 422
        return _json(
            {"error": "validation failed", "details": str(exc)}, status_code=422
        )
