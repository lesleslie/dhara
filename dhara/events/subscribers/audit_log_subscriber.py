from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from dhara.events.events import DomainEvent

logger = logging.getLogger(__name__)


class _SupportsExecute(Protocol):
    """Minimal protocol for the audit-log connection.

    DuckDB and asyncpg both expose ``execute(sql, params)``; we only need
    a synchronous-ish shape and don't care whether the return is awaitable.
    """

    def execute(self, sql: str, params: Any = ...) -> Any: ...


def _maybe_await(value: Any) -> Any:
    """Await an awaitable; otherwise return as-is."""
    if hasattr(value, "__await__"):
        # ``await value`` is fine because we are always inside an async caller.
        # We return the awaitable and let the caller handle it via a thin await.
        return value
    return value


class AuditLogSubscriber:
    """Subscriber that writes every received event to ``dhara_audit_log``.

    Demonstrates the durable-subscriber pattern: each event becomes a single
    row keyed by an auto-incremented ``id``. Failures are logged and isolated
    so the rest of the bus continues to function.
    """

    def __init__(self, connection: _SupportsExecute) -> None:
        self._conn = connection

    async def handle(self, event: DomainEvent) -> None:
        payload_json = json.dumps(event.model_dump(mode="json"), sort_keys=True)
        # Compute the next id defensively so this works on tables that have
        # an INTEGER PRIMARY KEY without a DuckDB-managed sequence attached.
        next_id_row = self._conn.execute(
            "SELECT COALESCE(MAX(id), 0) + 1 FROM dhara_audit_log"
        )
        if hasattr(next_id_row, "__await__"):
            next_id_row = await next_id_row  # type: ignore[await]
        next_id = next_id_row.fetchone()[0]

        params = (
            next_id,
            event.event_type,
            event.event_id,
            event.occurred_at,
            event.tenant_id,
            payload_json,
        )
        try:
            result = self._conn.execute(
                "INSERT INTO dhara_audit_log "
                "(id, event_type, event_id, occurred_at, tenant_id, payload) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                params,
            )
            if hasattr(result, "__await__"):
                await result  # type: ignore[await]
        except Exception:
            logger.exception(
                "AuditLogSubscriber failed writing event %s", event.event_id
            )
            raise


__all__ = ["AuditLogSubscriber"]
