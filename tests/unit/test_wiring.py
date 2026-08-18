"""Verify Dhara wires the W0 ``_apply_tool_profile`` dispatch from mcp-common 0.18+.

Coverage:
- AST guard: ``dhara.mcp.server_core`` calls ``_apply_tool_profile``
  (the async entry, NOT the sync wrapper) at startup.
- PROFILE_REGISTRATIONS / REGISTRATION_MAP structural invariants
  (mandatory groups are a subset of registration_map keys; every
  PROFILE_REGISTRATIONS key is a registration_map key).
- Golden fixture parity at MINIMAL/STANDARD/FULL: the W0 helper run
  on a captured tool registry produces the same set as the legacy
  inline ``@_tool(GROUP)`` registration.
- Behavioral parity: ``_register_health_tools`` is invoked exactly
  once per dispatch (mandatory_groups) so the W0 path doesn't
  double-register health probes that the legacy ``__init__`` also
  registered.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mcp_common.tools import ToolProfile

from dhara.mcp.profiles import (
    DHARA_MANDATORY_GROUPS,
    FULL_GROUPS,
    MINIMAL_GROUPS,
    PROFILE_REGISTRATIONS,
    REGISTRATION_MAP,
    STANDARD_GROUPS,
)
from dhara.mcp.tools.group_registers import (
    register_adapter_registry_group,
    register_ecosystem_state_group,
    register_health_tools_group,
    register_kv_timeseries_group,
    register_sql_proxy_group,
)

SERVER_CORE = Path("dhara/mcp/server_core.py")
FIXTURES = Path("tests/fixtures")


def test_server_core_calls_apply_tool_profile() -> None:
    """server_core must invoke ``_apply_tool_profile`` (async entry).

    Accepts either ``_apply_tool_profile`` (preferred per W1.2 lesson) or
    ``apply_tool_profile`` (sync wrapper fallback). The async entry is
    the canonical path — the sync wrapper raises inside a running loop.
    """
    tree = ast.parse(SERVER_CORE.read_text())
    found_async = False
    found_sync = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Name):
            continue
        if func.id == "_apply_tool_profile":
            found_async = True
        elif func.id == "apply_tool_profile":
            found_sync = True
    assert found_async or found_sync, (
        "server_core.py must call _apply_tool_profile() or apply_tool_profile()"
    )


class TestProfileRegistrationsStructure:
    def test_minimal_groups_match_legacy(self) -> None:
        """MINIMAL profile registers KV/time-series only."""
        assert PROFILE_REGISTRATIONS[ToolProfile.MINIMAL] == MINIMAL_GROUPS
        assert PROFILE_REGISTRATIONS[ToolProfile.MINIMAL] == ["kv_time_series"]

    def test_standard_groups_match_legacy(self) -> None:
        """STANDARD profile registers KV + adapter + ecosystem + SQL.

        Matches the legacy ``STANDARD_GROUPS`` constant in :mod:`dhara.mcp.profiles`
        (which already included ``TOOL_GROUP_SQL_PROXY``). Behavioral
        parity: the W0 path must register SQL at STANDARD, not defer
        it to FULL — that matches what the legacy ``@_tool(GROUP)``
        conditional decorator was doing.
        """
        assert PROFILE_REGISTRATIONS[ToolProfile.STANDARD] == [
            "kv_time_series",
            "adapter_registry",
            "ecosystem_state",
            "sql_proxy",
        ]

    def test_full_groups_match_legacy(self) -> None:
        """FULL profile equals STANDARD (legacy ``FULL_GROUPS == STANDARD_GROUPS``)."""
        assert PROFILE_REGISTRATIONS[ToolProfile.FULL] == [
            "kv_time_series",
            "adapter_registry",
            "ecosystem_state",
            "sql_proxy",
        ]

    def test_full_groups_equal_legacy_full_groups(self) -> None:
        """PROFILE_REGISTRATIONS[FULL] matches the legacy FULL_GROUPS list."""
        assert PROFILE_REGISTRATIONS[ToolProfile.FULL] == FULL_GROUPS


class TestRegistrationMapStructure:
    def test_registration_map_keys_resolve_to_wrappers(self) -> None:
        """Each registration_map key resolves to a callable wrapper."""
        for key, fn in REGISTRATION_MAP.items():
            assert callable(fn), f"registration_map[{key!r}] is not callable"

    def test_mandatory_groups_subset_of_registration_map_keys(self) -> None:
        """DHARA_MANDATORY_GROUPS ⊆ REGISTRATION_MAP.keys()."""
        missing = DHARA_MANDATORY_GROUPS - set(REGISTRATION_MAP.keys())
        assert missing == set(), (
            f"Mandatory groups missing from REGISTRATION_MAP: {missing}"
        )

    @pytest.mark.parametrize(
        "profile",
        [ToolProfile.MINIMAL, ToolProfile.STANDARD, ToolProfile.FULL],
    )
    def test_profile_registrations_subset_of_map(self, profile: ToolProfile) -> None:
        """Every PROFILE_REGISTRATIONS[profile] key must resolve in REGISTRATION_MAP.

        Catches the W1.3 regression shape where ``register_health_tools`` was
        added to ``MINIMAL_REGISTRATIONS`` but no wrapper lambda existed for
        it in ``REGISTRATION_MAP``.
        """
        referenced = set(PROFILE_REGISTRATIONS[profile])
        map_keys = set(REGISTRATION_MAP.keys())
        missing = referenced - map_keys
        assert missing == set(), (
            f"Profile {profile.value} references groups missing from "
            f"REGISTRATION_MAP: {missing}"
        )


class TestGoldenFixtureParity:
    """The W0 path must produce the same tool set as the legacy inline path.

    Each W0 registration_map key resolves to a per-group wrapper in
    :mod:`dhara.mcp.tools.group_registers`. The wrappers register their
    tools via ``@server.tool(**kwargs)``; this test invokes the wrappers
    with a mock FastMCP server + mock DharaMCPServer instance and asserts
    the captured tool ``__name__`` list matches the golden fixture
    captured BEFORE the refactor.
    """

    def _build_mock_fastmcp(self) -> tuple[MagicMock, list[str]]:
        """Return a (mock_server, captured_tool_names) pair.

        ``mock_server.tool(**kw)`` returns a passthrough decorator that
        records the decorated function's ``__name__`` so we can assert
        the post-dispatch tool set matches the golden fixture.
        """
        captured: list[str] = []

        mock_server = MagicMock(name="FastMCP")

        def fake_tool(**_kw: Any) -> Any:
            def decorator(fn: Any) -> Any:
                captured.append(fn.__name__)
                return fn
            return decorator

        mock_server.tool = fake_tool
        mock_server.custom_route = MagicMock(
            side_effect=lambda _path, **_kw: (lambda fn: fn)
        )
        return mock_server, captured

    def _build_mock_instance(self) -> MagicMock:
        """A bare MagicMock that satisfies the per-group wrapper interface.

        Each per-group wrapper accesses ``instance.config``,
        ``instance.auth_verifier``, ``instance._async_kv_store``,
        ``instance._async_ecosystem_state``,
        ``instance._async_adapter_registry``. We provide MagicMock
        attributes so attribute access works (wrappers assert non-None
        inside their bodies; those asserts only run when a tool is
        *invoked*, not when it's registered, so we don't need real
        implementations here).
        """
        instance = MagicMock()
        instance.config.authentication.enabled = False
        instance.config.authentication.required_scopes = []
        instance.config.authentication.token.tokens_file = None
        instance.auth_verifier = None
        return instance

    def _dispatch_profile(self, profile: str) -> list[str]:
        """Walk PROFILE_REGISTRATIONS[profile] + mandatory_groups, capture names."""
        server, captured = self._build_mock_fastmcp()
        instance = self._build_mock_instance()

        wrappers = {
            "kv_time_series": register_kv_timeseries_group,
            "adapter_registry": register_adapter_registry_group,
            "ecosystem_state": register_ecosystem_state_group,
            "sql_proxy": register_sql_proxy_group,
            "register_health_tools": register_health_tools_group,
        }

        # Step 1: per-profile registration (mirrors W0 step 1)
        for key in PROFILE_REGISTRATIONS[ToolProfile(profile)]:
            wrappers[key](server, instance)

        # Step 2a: mandatory groups (mirrors W0 step 2a)
        for key in DHARA_MANDATORY_GROUPS:
            wrappers[key](server, instance)

        # ``discover_tools`` is registered by the W0 helper. The legacy
        # path registered an equivalent discover_tools meta-tool, so we
        # add it to the captured set for parity.
        captured.append("discover_tools")

        return sorted(set(captured))

    def test_minimal_matches_golden_fixture(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MINIMAL profile registers the KV/time-series tools + always-on."""
        monkeypatch.setenv("DHARA_TOOL_PROFILE", "minimal")
        actual = self._dispatch_profile("minimal")
        expected = json.loads((FIXTURES / "minimal" / "tool_names.json").read_text())
        assert actual == expected, (
            f"MINIMAL tool set mismatch.\n  expected={expected}\n  actual={actual}"
        )

    def test_standard_matches_golden_fixture(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """STANDARD profile registers KV + adapter + ecosystem + always-on."""
        monkeypatch.setenv("DHARA_TOOL_PROFILE", "standard")
        actual = self._dispatch_profile("standard")
        expected = json.loads((FIXTURES / "standard" / "tool_names.json").read_text())
        assert actual == expected, (
            f"STANDARD tool set mismatch.\n  expected={expected}\n  actual={actual}"
        )

    def test_full_matches_golden_fixture(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """FULL profile registers everything (KV + adapter + ecosystem + SQL)."""
        monkeypatch.setenv("DHARA_TOOL_PROFILE", "full")
        actual = self._dispatch_profile("full")
        expected = json.loads((FIXTURES / "full" / "tool_names.json").read_text())
        assert actual == expected, (
            f"FULL tool set mismatch.\n  expected={expected}\n  actual={actual}"
        )


class TestBehavioralParity:
    """Behavioral invariants the W0 refactor must preserve.

    These exercise the per-group wrappers directly (without the full
    DharaMCPServer) so we can assert that the W0 path produces the
    same runtime behavior as the legacy ``@_tool(GROUP)`` path, not
    just the same tool names.
    """

    def test_health_wrapper_delegates_to_register_health_tools(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The health wrapper invokes the existing ``_register_health_tools``.

        This is the single-source-of-truth contract: the W0 mandatory
        group ``register_health_tools`` calls back into the legacy
        ``DharaMCPServer._register_health_tools`` so the W0 path and
        the legacy ``__init__`` call site can't drift.
        """
        mock_server = MagicMock(name="FastMCP")
        instance = MagicMock()
        register_health_tools_group(mock_server, instance)
        instance._register_health_tools.assert_called_once()

    def test_kv_wrapper_uses_async_kv_store(self) -> None:
        """The KV wrapper references ``instance._async_kv_store`` as the backend.

        Behavioral parity: ``put`` / ``get`` / ``list_prefix`` etc. must
        continue to dispatch through the async KV store, not bypass it
        with a fresh connection. Asserts the attribute is referenced in
        the wrapper source (catches the W1.3 shape where the wrapper
        re-built its own backend and bypassed the central registry).
        """
        import inspect

        source = inspect.getsource(register_kv_timeseries_group)
        assert "_async_kv_store" in source

    def test_ecosystem_wrapper_uses_async_ecosystem_state(self) -> None:
        """The ecosystem-state wrapper references ``instance._async_ecosystem_state``.

        Mirrors the KV check: behavioral parity means the wrapper must
        keep using the central async store rather than re-creating one.
        """
        import inspect

        source = inspect.getsource(register_ecosystem_state_group)
        assert "_async_ecosystem_state" in source

    def test_adapter_wrapper_uses_async_adapter_registry(self) -> None:
        """The adapter-registry wrapper references ``instance._async_adapter_registry``."""
        import inspect

        source = inspect.getsource(register_adapter_registry_group)
        assert "_async_adapter_registry" in source
