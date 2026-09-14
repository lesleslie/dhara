"""OTel/local-traces query tool for Dhara.

Exposes ``dhara_query_local_traces`` — a Bodai component endpoint that
Akosha's fitness analyzer polls to aggregate traces for fitness signal
computation (per plan §6.1 KNOWN_SERVICES and Phase 1.2c).

Mirrors the byte-for-byte shape shipped in Akosha and Mahavishnu
(``mahavishnu/mcp/tools/otel_tools.py:251-353`` is a clone of
``akosha/mcp/tools/otel_tools.py:30-31``). The underlying storage class
is ``akosha.storage.HotStore``, which is part of the optional
``otel-traces`` dep group (``uv sync --group otel-traces``).

This tool is read-only. Dhara does not currently persist OTel traces —
the tool returns ``[]`` until a component's OtelIngester points at the
same DuckDB file. The point is uniform registration so Akosha's
fitness analyzer has a stable polling target across all 5 Bodai
components (closes the routing-feedback-loop-v4 partial).

Function is a plain async callable; ``DharaMCPServer`` decorates it
with FastMCP ``@server.tool()`` at registration time. Tests import
this module directly.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from dhara.core.config import OtelTracesConfig, StorageConfig


def _resolve_database_path(
    otel_traces: OtelTracesConfig, storage: StorageConfig
) -> Path:
    """Return the DuckDB file path for traces.

    Defaults to ``<storage.path.parent>/traces.duckdb`` (sibling to the
    SHELF-1 storage file) when ``otel_traces.database_path`` is unset.
    """
    configured = otel_traces.database_path
    if configured is not None:
        return Path(configured)
    return Path(storage.path).parent / "traces.duckdb"


async def dhara_query_local_traces(
    task_class: str,
    time_range_minutes: int = 60,
    system_id: str | None = None,
    limit: int = 100,
    *,
    otel_traces: OtelTracesConfig | None = None,
    storage: StorageConfig | None = None,
) -> list[dict[str, Any]]:
    """Query OTel traces by task_class and time range.

    This is the Bodai component endpoint that Akosha's fitness analyzer
    polls to collect traces for fitness signal computation.

    Args:
        task_class: Task classification tag to filter on (e.g. ``"code_generation"``).
        time_range_minutes: How far back to query (default 60 minutes).
        system_id: Optional source system identifier (auto-detected if not provided).
        limit: Maximum number of traces to return (default 100).
        otel_traces: Dhara's OtelTracesConfig (injected by the registration wrapper).
        storage: Dhara's StorageConfig (injected by the registration wrapper).

    Returns:
        List of trace records with ``outcome``, ``duration_ms``,
        ``selector``, ``component_name``, ``task_class``, ``timestamp``.
        Empty list if the HotStore dep is missing, the file is empty,
        or the file does not yet exist.
    """
    # Input validation (C3) — mirrors Mahavishnu's contract at
    # mahavishnu/mcp/tools/otel_tools.py:271-284.
    if not task_class or not isinstance(task_class, str):
        logger.error("query_local_traces: task_class must be a non-empty string")
        return []
    if (
        not isinstance(time_range_minutes, int)
        or time_range_minutes <= 0
        or time_range_minutes > 10080
    ):
        logger.error(
            "query_local_traces: time_range_minutes must be 1-10080 (1 week max)"
        )
        return []
    if not isinstance(limit, int) or limit <= 0 or limit > 1000:
        logger.error("query_local_traces: limit must be 1-1000")
        return []

    try:
        from akosha.storage import HotStore  # ty: ignore[unresolved-import]
    except ImportError:
        logger.error(
            "query_local_traces: akosha not installed. "
            "Install with: uv sync --group otel-traces"
        )
        return []

    # Resolve path even if config is None (lightweight construction path).
    if otel_traces is None or storage is None:
        logger.error("query_local_traces: config not initialized")
        return []
    if not otel_traces.enabled:
        logger.info("query_local_traces: disabled in config")
        return []

    database_path = _resolve_database_path(otel_traces, storage)
    if not database_path.exists():
        # Forward-looking registration: the file will be created when
        # a component's OtelIngester first writes a trace. Until then,
        # return uniform ``[]`` across all 5 components.
        logger.info(
            "query_local_traces: trace database does not exist yet at %s",
            database_path,
        )
        return []

    try:
        end_time = datetime.now(UTC)
        start_time = end_time - timedelta(minutes=time_range_minutes)

        # Initialize HotStore against the configured DuckDB file.
        # `read_only=True` keeps Dhara from accidentally writing back
        # to a file owned by a different component's OtelIngester.
        hot_store = HotStore(
            database_path=database_path,
            embedding_dim=otel_traces.embedding_dim,
        )
        await hot_store.initialize()

        try:
            results = await hot_store.query_traces(
                system_id=system_id,
                start_time=start_time.isoformat(),
                end_time=end_time.isoformat(),
                task_class=task_class,
                limit=limit,
            )
        finally:
            # Always close hot_store, whether query succeeded or not.
            await hot_store.close()

        # Normalize result format for fitness analyzer consumption.
        normalized: list[dict[str, Any]] = []
        for r in results:
            metadata_raw = r.get("metadata", "{}")
            if isinstance(metadata_raw, str):
                try:
                    attrs = json.loads(metadata_raw).get("attributes", {})
                except json.JSONDecodeError:
                    attrs = {}
            else:
                attrs = (
                    metadata_raw.get("attributes", {})
                    if isinstance(metadata_raw, dict)
                    else {}
                )

            normalized.append(
                {
                    "outcome": attrs.get("outcome", "unknown"),
                    "duration_ms": attrs.get("duration_ms", 0),
                    "selector": attrs.get("selector", "unknown"),
                    "component_name": system_id or r.get("system_id", "unknown"),
                    "task_class": task_class,
                    "timestamp": str(r.get("timestamp", "")),
                }
            )

        logger.info(
            "query_local_traces returned %d records for task_class=%s",
            len(normalized),
            task_class,
        )
        return normalized

    except Exception:
        logger.exception("Error querying traces")
        return []


__all__ = ["dhara_query_local_traces"]
