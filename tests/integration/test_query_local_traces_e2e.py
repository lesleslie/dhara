"""E2E wiring test for ``dhara_query_local_traces``.

Per ``.claude/decisions/mcp-backend-wiring-discipline.md``: every
registered tool must have an integration test asserting the
registration path works end-to-end. We assert three things:

1. ``register_otel_traces_group`` is exported from
   ``dhara.mcp.tools.group_registers`` (the per-group wiring function
   the W0 dispatch invokes).
2. ``REG_KEY_OTEL_TRACES`` appears in ``profiles.REGISTRATION_MAP``,
   meaning the W0 dispatch will route the otel-traces group into the
   manifest at STANDARD profile.
3. ``dhara_query_local_traces`` is importable from
   ``dhara.mcp.tools.otel_traces`` and callable as a plain async
   function — proving the impl exists and matches the registration
   contract.

A full FastMCP-server boot + JSON-RPC round-trip would be heavier;
the unit suite already covers the validation/empty/happy-path
branches and the drift test covers the AST-level declaration match.
This test covers the W0 dispatch surface, which is what the e2e
discipline is targeting.
"""

from __future__ import annotations

import inspect
from typing import Any

from dhara.mcp.profiles import REGISTRATION_MAP
from dhara.mcp.tools import group_registers, otel_traces


def test_register_otel_traces_group_is_exported() -> None:
    """The per-group wiring function the W0 dispatch invokes is exported."""
    assert hasattr(group_registers, "register_otel_traces_group")
    assert callable(group_registers.register_otel_traces_group)


def test_otel_traces_key_routes_in_registration_map() -> None:
    """W0 dispatch routes the otel-traces registration key into the manifest."""
    # Convention: per-profile groups use group-name keys (kv_time_series,
    # adapter_registry, etc.); mandatory groups use wrapper-name keys
    # (register_*_group). otel_traces is per-profile, so its key is the
    # group name.
    assert "otel_traces" in REGISTRATION_MAP
    assert REGISTRATION_MAP["otel_traces"] is group_registers.register_otel_traces_group


async def test_dhara_query_local_traces_impl_is_async_callable() -> None:
    """The impl function exists, is async, and has the canonical signature."""
    assert hasattr(otel_traces, "dhara_query_local_traces")
    assert inspect.iscoroutinefunction(otel_traces.dhara_query_local_traces)
    sig = inspect.signature(otel_traces.dhara_query_local_traces)
    params = sig.parameters
    # Public params from the plan: task_class, time_range_minutes, system_id, limit.
    assert "task_class" in params
    assert "time_range_minutes" in params
    assert "system_id" in params
    assert "limit" in params
    # Default values match the Akosha/Mahavishnu contract.
    assert params["time_range_minutes"].default == 60
    assert params["limit"].default == 100


async def test_dhara_query_local_traces_returns_list() -> None:
    """Calling the impl with no config returns ``[]`` (lightweight path)."""
    result: list[dict[str, Any]] = await otel_traces.dhara_query_local_traces(
        task_class="code_generation"
    )
    assert result == []
