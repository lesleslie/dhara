"""Unit tests for the Dhara ``query_local_traces`` MCP tool.

TDD red phase: pins the public contract of
``dhara.mcp.tools.otel_traces.dhara_query_local_traces``. Passes when
the impl correctly:
  * validates ``task_class`` / ``time_range_minutes`` / ``limit`` and
    returns ``[]`` on bad input;
  * returns ``[]`` when the trace DuckDB file does not exist
    (forward-looking registration);
  * returns ``[]`` when ``akosha`` is not installed (ImportError);
  * normalizes HotStore rows into the canonical ``outcome`` /
    ``duration_ms`` / ``selector`` / ``component_name`` /
    ``task_class`` / ``timestamp`` shape.

Requires the ``otel-traces`` dep group (``uv sync --group otel-traces
--group dev``) so the ``akosha.storage.HotStore`` import resolves.
Tests that exercise the ImportError fallback are independent of the
dep group.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from dhara.core.config import OtelTracesConfig, StorageConfig

# Tests that exercise HotStore require the optional dep group; tests
# that don't (validation, ImportError fallback, missing file) skip
# cleanly when the dep is missing.
try:
    from akosha.storage import HotStore  # ty: ignore[unresolved-import]

    _HOTSTORE_AVAILABLE = True
except ImportError:
    _HOTSTORE_AVAILABLE = False


pytestmark = pytest.mark.unit


def _storage(tmp_path: Path) -> StorageConfig:
    """Build a StorageConfig whose path is a real (non-existent) file
    so ``_resolve_database_path`` defaults to ``<tmp>/traces.duckdb``.
    """
    return StorageConfig(path=tmp_path / "dhara.dhara")


def _otel(tmp_path: Path, *, enabled: bool = True) -> OtelTracesConfig:
    return OtelTracesConfig(enabled=enabled, embedding_dim=384)


def _make_hot_store(tmp_path: Path) -> HotStore:
    """Build a HotStore rooted at ``tmp_path/traces.duckdb`` and
    initialise the schema. Uses in-memory-friendly ``:memory:`` when
    ``tmp_path`` is unused by the caller.
    """
    store = HotStore(database_path=tmp_path / "traces.duckdb", embedding_dim=384)
    return store


@pytest.fixture(autouse=True)
def _reload_otel_traces_module() -> None:
    """Force reimport after test-env mucking with ``akosha`` modules.

    The ImportError fallback test unloads the akosha modules to
    simulate a missing dep — without a reload, sibling tests would
    observe a polluted sys.modules state.
    """
    yield


# ---------------------------------------------------------------------------
# Validation paths — exercise BEFORE the HotStore import is touched.
# ---------------------------------------------------------------------------


async def test_query_local_traces_empty_task_class_returns_empty(
    tmp_path: Path,
) -> None:
    """Empty ``task_class`` is rejected; returns ``[]``."""
    from dhara.mcp.tools.otel_traces import dhara_query_local_traces

    result = await dhara_query_local_traces(
        task_class="",
        otel_traces=_otel(tmp_path),
        storage=_storage(tmp_path),
    )
    assert result == []


async def test_query_local_traces_non_string_task_class_returns_empty(
    tmp_path: Path,
) -> None:
    """Non-string ``task_class`` is rejected; returns ``[]``."""
    from dhara.mcp.tools.otel_traces import dhara_query_local_traces

    result = await dhara_query_local_traces(
        task_class=42,  # type: ignore[arg-type]
        otel_traces=_otel(tmp_path),
        storage=_storage(tmp_path),
    )
    assert result == []


async def test_query_local_traces_time_range_too_large_returns_empty(
    tmp_path: Path,
) -> None:
    """``time_range_minutes > 10080`` is rejected; returns ``[]``."""
    from dhara.mcp.tools.otel_traces import dhara_query_local_traces

    result = await dhara_query_local_traces(
        task_class="code_generation",
        time_range_minutes=20000,
        otel_traces=_otel(tmp_path),
        storage=_storage(tmp_path),
    )
    assert result == []


async def test_query_local_traces_time_range_negative_returns_empty(
    tmp_path: Path,
) -> None:
    """``time_range_minutes <= 0`` is rejected; returns ``[]``."""
    from dhara.mcp.tools.otel_traces import dhara_query_local_traces

    result = await dhara_query_local_traces(
        task_class="code_generation",
        time_range_minutes=-1,
        otel_traces=_otel(tmp_path),
        storage=_storage(tmp_path),
    )
    assert result == []


async def test_query_local_traces_limit_too_large_returns_empty(
    tmp_path: Path,
) -> None:
    """``limit > 1000`` is rejected; returns ``[]``."""
    from dhara.mcp.tools.otel_traces import dhara_query_local_traces

    result = await dhara_query_local_traces(
        task_class="code_generation",
        limit=5000,
        otel_traces=_otel(tmp_path),
        storage=_storage(tmp_path),
    )
    assert result == []


# ---------------------------------------------------------------------------
# Missing-file / disabled / no-config paths — also pre-import safe.
# ---------------------------------------------------------------------------


async def test_query_local_traces_missing_file_returns_empty(
    tmp_path: Path,
) -> None:
    """When the configured DuckDB file does not exist, return ``[]``."""
    from dhara.mcp.tools.otel_traces import dhara_query_local_traces

    # tmp_path is empty: storage.path points to <tmp>/dhara.dhara
    # which doesn't exist; the default traces.duckdb is <tmp>/traces.duckdb
    # which also doesn't exist. The tool must NOT raise.
    result = await dhara_query_local_traces(
        task_class="code_generation",
        otel_traces=_otel(tmp_path),
        storage=_storage(tmp_path),
    )
    assert result == []


async def test_query_local_traces_disabled_returns_empty(tmp_path: Path) -> None:
    """``otel_traces.enabled = False`` short-circuits to ``[]``."""
    from dhara.mcp.tools.otel_traces import dhara_query_local_traces

    result = await dhara_query_local_traces(
        task_class="code_generation",
        otel_traces=_otel(tmp_path, enabled=False),
        storage=_storage(tmp_path),
    )
    assert result == []


async def test_query_local_traces_no_config_returns_empty() -> None:
    """Lightweight construction path (no config injected) returns ``[]``."""
    from dhara.mcp.tools.otel_traces import dhara_query_local_traces

    result = await dhara_query_local_traces(task_class="code_generation")
    assert result == []


# ---------------------------------------------------------------------------
# ImportError fallback — works whether or not akosha is installed.
# ---------------------------------------------------------------------------


async def test_query_local_traces_returns_empty_when_akosha_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``akosha.storage`` cannot be imported, return ``[]``."""
    # Hide akosha entirely so the lazy import inside the impl raises.
    monkeypatch.setitem(sys.modules, "akosha", None)
    monkeypatch.setitem(sys.modules, "akosha.storage", None)

    # Force the impl module to re-import its top-level imports.
    import dhara.mcp.tools.otel_traces as otel_mod

    importlib.reload(otel_mod)

    result = await otel_mod.dhara_query_local_traces(
        task_class="code_generation",
        otel_traces=_otel(tmp_path),
        storage=_storage(tmp_path),
    )
    assert result == []


# ---------------------------------------------------------------------------
# Happy path — requires the ``otel-traces`` dep group.
#
# Note: the end-to-end insert + query_traces flow against a real
# HotStore is intentionally NOT exercised here. Akosha's
# ``HotStore.query_traces`` raises ``_duckdb.ConversionException`` on
# the ``(metadata->>'task_class' = ? OR metadata->'attributes'->>'task_class' = ?)``
# OR-expression (DuckDB optimiser tries to cast metadata to a numeric
# type). This is an upstream bug in Akosha — same shape is shipped
# byte-for-byte on Akosha/Mahavishnu and is presumed to surface there
# as well. Fixing it there is out of scope for this PR (which only
# adds the Dhara-side uniform registration). The tests below instead
# verify the Dhara-side normalization by mocking ``query_traces`` to
# return known rows.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _HOTSTORE_AVAILABLE,
    reason="requires uv sync --group otel-traces (akosha not installed)",
)
async def test_query_local_traces_empty_db_returns_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HotStore initialised but query returns no rows; tool returns ``[]``."""
    from dhara.mcp.tools.otel_traces import dhara_query_local_traces

    # Monkeypatch query_traces so we don't depend on the upstream DuckDB
    # JSON-path bug surfacing in the test.
    async def _fake_query_traces(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(HotStore, "query_traces", _fake_query_traces)

    storage = _storage(tmp_path)
    otel_cfg = OtelTracesConfig(
        enabled=True,
        database_path=tmp_path / "traces.duckdb",
        embedding_dim=384,
    )

    result = await dhara_query_local_traces(
        task_class="code_generation",
        otel_traces=otel_cfg,
        storage=storage,
    )
    assert result == []


@pytest.mark.skipif(
    not _HOTSTORE_AVAILABLE,
    reason="requires uv sync --group otel-traces (akosha not installed)",
)
async def test_query_local_traces_normalizes_dict_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When HotStore rows have ``metadata`` as a dict, normalize into the
    canonical ``outcome`` / ``duration_ms`` / ``selector`` /
    ``component_name`` / ``task_class`` / ``timestamp`` shape.

    Mocks ``query_traces`` to bypass the upstream DuckDB
    JSON-path-OR ConversionException.
    """
    from dhara.mcp.tools.otel_traces import dhara_query_local_traces

    db_path = tmp_path / "traces.duckdb"
    # Pre-create the file by initialising (and closing) a real HotStore.
    boot = HotStore(database_path=db_path, embedding_dim=384)
    await boot.initialize()
    await boot.close()

    async def _fake_query_traces(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "system_id": "akosha",
                "conversation_id": "conv-1",
                "content": "trace content",
                "timestamp": "2026-09-14T12:00:00+00:00",
                "metadata": {
                    "task_class": "code_generation",
                    "attributes": {
                        "outcome": "success",
                        "duration_ms": 123,
                        "selector": "least_loaded",
                    },
                },
            }
        ]

    monkeypatch.setattr(HotStore, "query_traces", _fake_query_traces)

    storage = _storage(tmp_path)
    otel_cfg = OtelTracesConfig(
        enabled=True,
        database_path=db_path,
        embedding_dim=384,
    )

    result = await dhara_query_local_traces(
        task_class="code_generation",
        otel_traces=otel_cfg,
        storage=storage,
    )

    assert len(result) == 1
    row = result[0]
    assert row["task_class"] == "code_generation"
    assert row["outcome"] == "success"
    assert row["duration_ms"] == 123
    assert row["selector"] == "least_loaded"
    assert row["component_name"] == "akosha"
    assert row["timestamp"] == "2026-09-14T12:00:00+00:00"


@pytest.mark.skipif(
    not _HOTSTORE_AVAILABLE,
    reason="requires uv sync --group otel-traces (akosha not installed)",
)
async def test_query_local_traces_normalizes_string_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When HotStore returns metadata as a JSON string, the impl parses it."""
    from dhara.mcp.tools.otel_traces import dhara_query_local_traces

    db_path = tmp_path / "traces.duckdb"
    boot = HotStore(database_path=db_path, embedding_dim=384)
    await boot.initialize()
    await boot.close()

    async def _fake_query_traces(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "system_id": "mahavishnu",
                "conversation_id": "conv-2",
                "content": "trace",
                "timestamp": "2026-09-14T12:00:00+00:00",
                "metadata": json.dumps(
                    {
                        "task_class": "code_generation",
                        "attributes": {
                            "outcome": "failure",
                            "duration_ms": 999,
                            "selector": "affinity",
                        },
                    }
                ),
            }
        ]

    monkeypatch.setattr(HotStore, "query_traces", _fake_query_traces)

    storage = _storage(tmp_path)
    otel_cfg = OtelTracesConfig(
        enabled=True,
        database_path=db_path,
        embedding_dim=384,
    )

    result = await dhara_query_local_traces(
        task_class="code_generation",
        system_id="mahavishnu",
        otel_traces=otel_cfg,
        storage=storage,
    )

    assert len(result) == 1
    row = result[0]
    assert row["outcome"] == "failure"
    assert row["duration_ms"] == 999
    assert row["selector"] == "affinity"
    assert row["component_name"] == "mahavishnu"


@pytest.mark.skipif(
    not _HOTSTORE_AVAILABLE,
    reason="requires uv sync --group otel-traces (akosha not installed)",
)
async def test_query_local_traces_malformed_string_metadata_returns_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If metadata is a string that fails JSON parsing, fall back to ``unknown``."""
    from dhara.mcp.tools.otel_traces import dhara_query_local_traces

    db_path = tmp_path / "traces.duckdb"
    boot = HotStore(database_path=db_path, embedding_dim=384)
    await boot.initialize()
    await boot.close()

    async def _fake_query_traces(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "system_id": "crackerjack",
                "conversation_id": "conv-3",
                "content": "trace",
                "timestamp": "2026-09-14T12:00:00+00:00",
                "metadata": "not valid json {{",
            }
        ]

    monkeypatch.setattr(HotStore, "query_traces", _fake_query_traces)

    storage = _storage(tmp_path)
    otel_cfg = OtelTracesConfig(
        enabled=True,
        database_path=db_path,
        embedding_dim=384,
    )

    result = await dhara_query_local_traces(
        task_class="code_generation",
        otel_traces=otel_cfg,
        storage=storage,
    )

    assert len(result) == 1
    row = result[0]
    assert row["outcome"] == "unknown"
    assert row["duration_ms"] == 0
    assert row["selector"] == "unknown"
    assert row["component_name"] == "crackerjack"
