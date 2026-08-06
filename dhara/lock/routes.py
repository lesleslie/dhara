"""REST routes for D-LOCK."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from dhara.lock.protocol import LockHandle
from dhara.lock.sql import SQLBackend, SQLBackendLock


def _handle_to_dict(handle: LockHandle) -> dict[str, Any]:
    return {
        "lock_key": handle.lock_key,
        "owner_token": handle.owner_token,
        "acquired_at": handle.acquired_at.isoformat(),
        "expires_at": handle.expires_at.isoformat() if handle.expires_at else None,
        "is_permanent": handle.is_permanent,
        "original_ttl_seconds": handle.original_ttl_seconds,
        "metadata": handle.metadata,
    }


async def _safe_json(request: Any) -> Any:
    """Parse JSON body; return JSONResponse 400 on failure."""
    from starlette.responses import JSONResponse

    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "invalid json body"}, status_code=400)
    if not isinstance(data, dict):
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
    return data


def _owner_header(request: Any) -> str | None:
    return request.headers.get("X-Owner-Token")


async def _post_lock(request: Any, store: SQLBackendLock) -> Any:
    """POST /locks/{lock_key} — try_acquire (non-blocking)."""
    from starlette.responses import JSONResponse

    lock_key = request.path_params["lock_key"]
    body = await _safe_json(request)
    if isinstance(body, JSONResponse):
        return body
    try:
        handle = store.try_acquire(
            lock_key,
            owner_token=body.get("owner_token"),
            ttl_seconds=body.get("ttl_seconds"),
            permanent=body.get("permanent", False),
            metadata=body.get("metadata"),
        )
    except ValueError as exc:
        # Mutual exclusion violation (permanent=True + ttl_seconds set) — separate from conflict
        return JSONResponse(
            {"error": "value_error", "details": str(exc)}, status_code=400
        )
    if handle is not None:
        return JSONResponse(_handle_to_dict(handle), status_code=200)
    # Held — disambiguate duplicate_permanent vs lock_lost
    current = store.get(lock_key)
    if current is not None and current.is_permanent:
        return JSONResponse(
            {
                "error": "lock_conflict",
                "reason": "duplicate_permanent",
                "lock_key": lock_key,
                "current_owner_token": current.owner_token,
            },
            status_code=409,
        )
    return JSONResponse(
        {
            "error": "lock_conflict",
            "reason": "lock_lost",
            "lock_key": lock_key,
            "current_owner_token": current.owner_token if current else None,
        },
        status_code=409,
    )


async def _post_acquire(request: Any, store: SQLBackendLock) -> Any:
    """POST /locks/{lock_key}/acquire — acquire with wait/timeout."""
    from starlette.responses import JSONResponse

    from dhara.lock.protocol import LockTimeout

    lock_key = request.path_params["lock_key"]
    body = await _safe_json(request)
    if isinstance(body, JSONResponse):
        return body
    try:
        handle = await store.acquire(
            lock_key,
            owner_token=body.get("owner_token"),
            ttl_seconds=body.get("ttl_seconds"),
            permanent=body.get("permanent", False),
            timeout_seconds=body.get("timeout_seconds"),
            metadata=body.get("metadata"),
        )
    except LockTimeout:
        return JSONResponse({"error": "lock_timeout"}, status_code=408)
    except ValueError as exc:
        return JSONResponse(
            {"error": "value_error", "details": str(exc)}, status_code=400
        )
    return JSONResponse(_handle_to_dict(handle), status_code=200)


async def _post_heartbeat(request: Any, store: SQLBackendLock) -> Any:
    """POST /locks/{lock_key}/heartbeat — extend TTL of a held lock."""
    from starlette.responses import JSONResponse

    from dhara.lock.protocol import LockLost, LockPermanentError

    lock_key = request.path_params["lock_key"]
    owner_token = _owner_header(request)
    if owner_token is None:
        return JSONResponse({"error": "missing X-Owner-Token header"}, status_code=400)
    body = await _safe_json(request)
    if isinstance(body, JSONResponse):
        return body
    body = body or {}
    # Reconstruct a handle to pass to heartbeat
    current = store.get(lock_key)
    if current is None:
        return JSONResponse(
            {
                "error": "lock_conflict",
                "reason": "lock_lost",
                "lock_key": lock_key,
            },
            status_code=409,
        )
    if current.owner_token != owner_token:
        return JSONResponse(
            {
                "error": "lock_conflict",
                "reason": "lock_lost",
                "lock_key": lock_key,
                "current_owner_token": current.owner_token,
            },
            status_code=409,
        )
    try:
        await store.heartbeat(current, extend_seconds=body.get("extend_seconds"))
    except LockPermanentError as exc:
        return JSONResponse(
            {
                "error": "lock_conflict",
                "reason": "lock_permanent",
                "lock_key": lock_key,
                "details": str(exc),
            },
            status_code=409,
        )
    except (LockLost, ValueError) as exc:
        return JSONResponse(
            {
                "error": "lock_conflict",
                "reason": "lock_lost",
                "lock_key": lock_key,
                "details": str(exc),
            },
            status_code=409,
        )
    return JSONResponse({}, status_code=204)


async def _delete_lock(request: Any, store: SQLBackendLock) -> Any:
    """DELETE /locks/{lock_key} — release a held lock."""
    from starlette.responses import JSONResponse

    from dhara.lock.protocol import LockLost, LockPermanentError

    lock_key = request.path_params["lock_key"]
    owner_token = _owner_header(request)
    if owner_token is None:
        return JSONResponse({"error": "missing X-Owner-Token header"}, status_code=400)
    current = store.get(lock_key)
    if current is None:
        return JSONResponse(
            {
                "error": "lock_conflict",
                "reason": "lock_lost",
                "lock_key": lock_key,
            },
            status_code=409,
        )
    if current.owner_token != owner_token:
        return JSONResponse(
            {
                "error": "lock_conflict",
                "reason": "lock_lost",
                "lock_key": lock_key,
                "current_owner_token": current.owner_token,
            },
            status_code=409,
        )
    try:
        await store.release(current)
    except LockPermanentError as exc:
        return JSONResponse(
            {
                "error": "lock_conflict",
                "reason": "lock_permanent",
                "lock_key": lock_key,
                "details": str(exc),
            },
            status_code=409,
        )
    except LockLost as exc:
        return JSONResponse(
            {
                "error": "lock_conflict",
                "reason": "lock_lost",
                "lock_key": lock_key,
                "details": str(exc),
            },
            status_code=409,
        )
    return JSONResponse({}, status_code=204)


async def _get_lock(request: Any, store: SQLBackendLock) -> Any:
    """GET /locks/{lock_key} — fetch a single handle."""
    from starlette.responses import JSONResponse

    lock_key = request.path_params["lock_key"]
    handle = store.get(lock_key)
    if handle is None:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return JSONResponse(_handle_to_dict(handle), status_code=200)


async def _list_locks(request: Any, store: SQLBackendLock) -> Any:
    """GET /locks?prefix=... — list handles, optionally filtered by prefix."""
    from starlette.responses import JSONResponse

    prefix = request.query_params.get("prefix")
    handles = store.list_keys(prefix)
    return JSONResponse([_handle_to_dict(h) for h in handles], status_code=200)


def _bind(handler: Any, store: SQLBackendLock) -> Any:
    """Bind ``store`` to a (request, store) async handler for FastMCP routing."""

    async def wrapper(request: Any) -> Any:
        return await handler(request, store)

    return wrapper


def register_lock_routes(server: FastMCP, sql_backend: SQLBackend) -> None:
    """Register REST routes for D-LOCK on the FastMCP server."""
    store = SQLBackendLock(sql_backend)
    routes: list[tuple[str, list[str], Any]] = [
        ("/locks/{lock_key}", ["POST"], _post_lock),
        ("/locks/{lock_key}/acquire", ["POST"], _post_acquire),
        ("/locks/{lock_key}/heartbeat", ["POST"], _post_heartbeat),
        ("/locks/{lock_key}", ["DELETE"], _delete_lock),
        ("/locks/{lock_key}", ["GET"], _get_lock),
        ("/locks", ["GET"], _list_locks),
    ]
    for path, methods, handler in routes:
        server.custom_route(path, methods=methods)(_bind(handler, store))
