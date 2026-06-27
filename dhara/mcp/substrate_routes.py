"""Substrate HTTP CRUD routes for Dhara (Workstream C).

Adds three CRUD-style HTTP routes to the FastMCP app for the substrate
features described in the Dhara Substrate Implementation Plan:

- GET/POST /adapters/{adapter_id}/active-settings-version
- GET/POST /tenants/{tenant_id}/context-versions
- GET/POST /workflows/{workflow_id}/progress-snapshots

Persistence uses the Dhara ``Connection.get_root()`` PersistentMapping so
writes survive across requests. Underlying tables (``config_snapshots``,
``context_versions``, ``workflow_progress``) are defined inline here as
a flat dict-of-lists under ``substrate.*`` root keys — Workstream D's
migration runner will formalize them as proper SQL tables. See TODO in
``_store_substrate`` for the formalization reference.

Routes are registered via ``register_substrate_routes(server)`` and use
``server.custom_route(path, methods=[...])`` to match the existing
pattern in ``dhara/mcp/server_core.py`` (see ``/health``, ``/tools/call``).
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Inline substrate schemas
# ---------------------------------------------------------------------------
#
# These mirror the future SQL tables from Workstream D's 0001_initial.sql
# but live as JSON-serializable dicts under ``substrate.*`` PersistentMapping
# keys. Each entry is shaped like:
#   {"id": str, "tenant_id": str | None, "created_at": str,
#    "payload": dict[str, Any]}
#
# TODO(Workstream D): Replace inline dict storage with SQL-backed
# `config_snapshots`, `context_versions`, `workflow_progress` tables
# from migration 0001. Keep the public HTTP shape stable.


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
    return sub[name]


def _resource_bucket(connection: Any, resource: str, resource_id: str) -> dict[str, Any]:
    """Return the per-resource bucket (e.g. ``adapter:abc:def``)."""
    parent = _bucket(connection, resource)
    if resource_id not in parent:
        parent[resource_id] = []
    return parent[resource_id]


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
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _read(connection: Any, resource: str, resource_id: str) -> list[dict[str, Any]]:
    """Return the list of stored records for the given resource."""
    parent = _bucket(connection, resource)
    items = parent.get(resource_id, [])
    return list(items)


def _store_substrate(
    connection: Any,
    resource: str,
    resource_id: str,
    payload: dict[str, Any],
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Append a new substrate record and return the persisted row."""
    from uuid import uuid4

    record: dict[str, Any] = {
        "id": uuid4().hex,
        "tenant_id": tenant_id,
        "created_at": _now_iso(),
        "payload": dict(payload),
    }
    parent = _bucket(connection, resource)
    items = list(parent.get(resource_id, []))
    items.append(record)
    parent[resource_id] = items
    # Connection root writeback happens via PersistentMapping semantics.
    return record


def _json(payload: Any, status_code: int = 200) -> Any:
    """Starlette JSONResponse wrapper (matches existing route style)."""
    from starlette.responses import JSONResponse

    return JSONResponse(payload, status_code=status_code)


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_substrate_routes(server: FastMCP, connection: Any) -> None:
    """Register the three substrate CRUD route sets on the FastMCP app.

    Args:
        server: The ``FastMCP`` instance to attach routes to.
        connection: A Dhara ``Connection`` for substrate persistence.
    """

    @server.custom_route(
        "/adapters/{adapter_id}/active-settings-version", methods=["GET"]
    )
    async def get_active_settings_version(request: Any) -> Any:
        from starlette.responses import JSONResponse

        adapter_id = request.path_params["adapter_id"]
        records = _read(connection, "active_settings_version", adapter_id)
        current = records[-1]["payload"] if records else None
        body: dict[str, Any] = {
            "adapter_id": adapter_id,
            "version": (current or {}).get("version"),
            "settings_version": (current or {}).get("version"),
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
        record = _store_substrate(
            connection,
            "active_settings_version",
            adapter_id,
            parsed.model_dump(),
        )
        body = {"adapter_id": adapter_id, "version": parsed.version, "record_id": record["id"]}
        return _json(body, status_code=200)

    @server.custom_route(
        "/tenants/{tenant_id}/context-versions", methods=["GET"]
    )
    async def get_context_versions(request: Any) -> Any:
        from starlette.responses import JSONResponse

        tenant_id = request.path_params["tenant_id"]
        records = _read(connection, "context_versions", tenant_id)
        body = {
            "tenant_id": tenant_id,
            "versions": [r["payload"] for r in records],
            "items": records,
            "total": len(records),
        }
        return JSONResponse(body, status_code=200)

    @server.custom_route(
        "/tenants/{tenant_id}/context-versions", methods=["POST"]
    )
    async def post_context_versions(request: Any) -> Any:
        tenant_id = request.path_params["tenant_id"]
        parsed = await _parse_json_body(request, _ContextVersionIn)
        if not isinstance(parsed, _ContextVersionIn):
            return parsed
        record = _store_substrate(
            connection,
            "context_versions",
            tenant_id,
            parsed.model_dump(),
            tenant_id=tenant_id,
        )
        body = {
            "tenant_id": tenant_id,
            "version": parsed.version,
            "record_id": record["id"],
        }
        return _json(body, status_code=200)

    @server.custom_route(
        "/workflows/{workflow_id}/progress-snapshots", methods=["GET"]
    )
    async def get_progress_snapshots(request: Any) -> Any:
        from starlette.responses import JSONResponse

        workflow_id = request.path_params["workflow_id"]
        records = _read(connection, "progress_snapshots", workflow_id)
        body = {
            "workflow_id": workflow_id,
            "snapshots": [r["payload"] for r in records],
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
        record = _store_substrate(
            connection,
            "progress_snapshots",
            workflow_id,
            parsed.model_dump(),
        )
        body = {
            "workflow_id": workflow_id,
            "stage": parsed.stage,
            "percent": parsed.percent,
            "record_id": record["id"],
        }
        return _json(body, status_code=200)


async def _parse_json_body(
    request: Any, model_cls: type[BaseModel]
) -> BaseModel | Any:
    """Parse and validate a JSON request body.

    Returns the parsed Pydantic instance on success, or a Starlette
    ``JSONResponse`` (with status 422) on any failure mode the caller
    should return directly. The caller distinguishes the two via
    ``isinstance(parsed, model_cls)``.
    """
    try:
        data = await request.json()
    except Exception:
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
    except Exception as exc:
        return _json(
            {"error": "validation failed", "details": str(exc)}, status_code=422
        )