"""End-to-end test for ``mcp__dhara__dhara_list_agents`` (Phase 3).

Per plan §5 Phase 3 exit criteria, ``mcp__dhara__dhara_list_agents()``
MUST return ≥3 entries AND every entry MUST have a non-empty
``system_prompt`` field (the picker reads the system prompt, not the
metadata — an agent with an empty body is non-functional).

This test wires the Phase 3 ``register_agent_registry_group`` into a
mock FastMCP server, captures the registered
``dhara_list_agents`` tool, and invokes it directly. The lifespan-owned
:class:`SkillsSigner` is initialized via ``init_signer_feed_state``
so the metadata gets signed (Phase 1.5 infrastructure reused for
Phase 3 identity signing).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from dhara.mcp.signer_feed import (
    get_signer_feed_state,
    init_signer_feed_state,
)
from dhara.mcp.tools.group_registers import register_agent_registry_group


@pytest.fixture(scope="module", autouse=True)
def _ensure_signer_feed_state() -> None:
    """Initialize the module-level signer feed singleton for this test module.

    The Phase 3 list_agents / get_agent tools read the signer via
    ``get_signer_feed_state()``. The singleton is normally installed
    by ``DharaMCPServer.__init__``; this fixture replicates that
    side effect so the tools can run outside the full server
    lifecycle.
    """
    state = get_signer_feed_state()
    if state is None:
        init_signer_feed_state()


def _build_mock_fastmcp() -> tuple[MagicMock, dict[str, Any]]:
    """Build a mock FastMCP server that captures registered tools.

    Mirrors the helper in ``tests/unit/test_wiring.py`` so the
    behavior of ``@server.tool(name=...)`` matches what FastMCP does
    in production (record ``fn`` under the ``name=`` key for later
    invocation).
    """
    captured: dict[str, Any] = {}

    mock_server = MagicMock(name="FastMCP")

    def fake_tool(**kw: Any) -> Any:
        def decorator(fn: Any) -> Any:
            tool_name = kw.get("name", fn.__name__)
            captured[tool_name] = fn
            return fn

        return decorator

    mock_server.tool = fake_tool
    return mock_server, captured


def _build_mock_instance() -> MagicMock:
    """Build a mock ``DharaMCPServer`` instance for the per-group wrapper.

    The agent_registry wrapper does NOT touch any ``_async_*`` stores
    — it reads the signer singleton — so we only need the bare
    surface that the wrapper signature demands.
    """
    return MagicMock()


@pytest.fixture
def captured_tools() -> dict[str, Any]:
    """Capture tools registered by ``register_agent_registry_group``."""
    server, captured = _build_mock_fastmcp()
    instance = _build_mock_instance()
    register_agent_registry_group(server, instance)
    return captured


class TestListAgentsE2E:
    """End-to-end assertions for ``dhara_list_agents``."""

    async def test_wrapper_registers_dhara_list_agents(
        self, captured_tools: dict[str, Any]
    ) -> None:
        """The agent_registry wrapper registers ``dhara_list_agents``."""
        assert "dhara_list_agents" in captured_tools, (
            "agent_registry wrapper should register 'dhara_list_agents'"
        )
        assert "dhara_get_agent" in captured_tools, (
            "agent_registry wrapper should register 'dhara_get_agent'"
        )

    async def test_list_agents_returns_at_least_3_entries(
        self, captured_tools: dict[str, Any]
    ) -> None:
        """Phase 3 exit criteria: list returns ≥3 entries."""
        list_fn = captured_tools["dhara_list_agents"]
        result = await list_fn()

        assert isinstance(result, list)
        assert len(result) >= 3, (
            f"list_agents must return ≥3 entries; got {len(result)}"
        )

    async def test_list_agents_every_entry_has_non_empty_body(
        self, captured_tools: dict[str, Any]
    ) -> None:
        """Phase 3 exit criteria: every entry references a non-empty body.

        ``list_agents`` strips the body + signing fields from the
        metadata dump (per Phase 3 plan §5 task #2 / B-6 — clients
        that want the full system prompt call ``get_agent``). But
        for picker parity the metadata itself must signal that the
        agent has a body. We assert each entry has ``body_size > 0``
        so a non-functional agent (body_size == 0) is detectable
        from the list payload alone.
        """
        list_fn = captured_tools["dhara_list_agents"]
        result = await list_fn()

        assert len(result) >= 3
        for entry in result:
            assert entry.get("id"), f"entry missing id: {entry}"
            assert entry.get("name"), f"entry missing name: {entry}"
            # ``body_size > 0`` confirms the catalog body is non-empty
            # (a non-functional agent would have body_size == 0).
            assert entry.get("body_size", 0) > 0, (
                f"entry has empty body: {entry}"
            )

    async def test_list_agents_get_agent_round_trip_yields_non_empty_system_prompt(
        self, captured_tools: dict[str, Any]
    ) -> None:
        """Phase 3 B-6 critical assertion: ``get_agent`` returns a body.

        Without this, the installer would ship non-functional agents
        that have no system prompt text. The list_agents call returns
        metadata only; the get_agent call returns the full body.
        """
        list_fn = captured_tools["dhara_list_agents"]
        get_fn = captured_tools["dhara_get_agent"]

        listed = await list_fn()
        assert len(listed) >= 3

        # Pick the first listed entry and fetch its full body
        first_name = listed[0]["name"]
        response = await get_fn(name=first_name)

        assert response["success"] is True, response
        metadata = response["metadata"]
        body = response["body"]
        assert metadata["name"] == first_name
        assert metadata["system_prompt"] == body, (
            "metadata.system_prompt must equal body verbatim"
        )
        assert len(body) > 200, (
            f"agent body must be >200 chars (Phase 3 catalog invariant); "
            f"got {len(body)} chars for {first_name}"
        )

    async def test_list_agents_returns_distinct_dhara_agents(
        self, captured_tools: dict[str, Any]
    ) -> None:
        """The 3 starter agents are distinct (no name collisions)."""
        list_fn = captured_tools["dhara_list_agents"]
        result = await list_fn()

        names = [entry["name"] for entry in result]
        assert "dhara-specialist" in names, (
            f"missing dhara-specialist in {names}"
        )
        assert "time-series-query" in names, (
            f"missing time-series-query in {names}"
        )
        assert "adapter-registry-check" in names, (
            f"missing adapter-registry-check in {names}"
        )
        # Names are unique (no collision).
        assert len(names) == len(set(names)), (
            f"duplicate agent names: {names}"
        )