"""AuditLogQueryTool — read-back MCP tool returning validated audit_records.

Queries the audit_log table by entity_type and optional time window,
decoding each row's JSON payload via :func:`from_dict` from the schema
registry. Records whose payload fails validation (e.g. older schema
drift) are silently skipped so a single bad row cannot break reads.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from oneiric.core.logging import get_logger

from dhara.schema import AuditRecord, from_dict

if TYPE_CHECKING:
    import duckdb

_logger = get_logger("dhara.audit.query_tool")


class AuditLogQueryTool:
    """Query audit_log by entity_type; return validated AuditRecord list."""

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn

    def query(
        self,
        entity_type: str,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditRecord]:
        sql = (
            "SELECT entity_type, entity_id, recorded_at, payload "
            "FROM audit_log WHERE entity_type = ?"
        )
        params: list[object] = [entity_type]
        if since is not None:
            sql += " AND recorded_at >= ?"
            params.append(since)
        if until is not None:
            sql += " AND recorded_at <= ?"
            params.append(until)
        sql += " ORDER BY recorded_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()

        results: list[AuditRecord] = []
        for row in rows:
            payload = json.loads(row[3])
            try:
                validated = from_dict("audit_record", payload)
            except Exception as exc:  # noqa: BLE001 — schema drift; skip row
                _logger.warning(
                    "audit_record_decode_skipped",
                    entity_id=row[1],
                    error=str(exc),
                )
                continue
            if isinstance(validated, AuditRecord):
                results.append(validated)
        return results
