"""End-to-end round-trip test for ``mcp__dhara__dhara_get_agent`` (Phase 3).

Per plan §5 Phase 3 exit criteria, the test asserts:

- ``dhara_get_agent(name)`` returns ``{"success": True, "metadata": ..., "body": ...}``.
- ``metadata.system_prompt`` equals ``body`` (string equality — the
  client uses ``body`` to write ``~/.claude/agents/<name>.md``
  verbatim, so any drift between the two fields is a bug).
- ``metadata.content_hash`` equals ``sha256(body.encode("utf-8"))``
  (the body-integrity hash round-trips correctly).
- ``metadata.signature`` is non-None and ``metadata.server_pubkey_id``
  is a 16-char hex string (Phase 1.5 signing infrastructure
  reused for Phase 3 identity).
- ``metadata.id`` matches ``f"{server_key}:{name}:{version}"``.

B-4 API-boundary check: a forbidden ``name`` returns an error
envelope rather than raising past the MCP boundary.
"""

from __future__ import annotations

import hashlib
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

    The Phase 3 get_agent tool reads the signer via
    ``get_signer_feed_state()``. The singleton is normally installed
    by ``DharaMCPServer.__init__``; this fixture replicates that
    side effect so the tool can run outside the full server
    lifecycle.
    """
    state = get_signer_feed_state()
    if state is None:
        init_signer_feed_state()


def _build_mock_fastmcp() -> tuple[MagicMock, dict[str, Any]]:
    """Build a mock FastMCP server that captures registered tools."""
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
    """Build a mock ``DharaMCPServer`` for the per-group wrapper."""
    return MagicMock()


@pytest.fixture
def get_agent_fn() -> Any:
    """Return the registered ``dhara_get_agent`` function."""
    server, captured = _build_mock_fastmcp()
    instance = _build_mock_instance()
    register_agent_registry_group(server, instance)
    return captured["dhara_get_agent"]


class TestGetAgentRoundTrip:
    """Round-trip assertions for ``dhara_get_agent(name)``."""

    async def test_get_dhara_specialist_returns_success(
        self, get_agent_fn: Any
    ) -> None:
        """``dhara_get_agent('dhara-specialist')`` returns success envelope."""
        response = await get_agent_fn(name="dhara-specialist")

        assert response["success"] is True, response
        assert "metadata" in response
        assert "body" in response

    async def test_metadata_system_prompt_equals_body(
        self, get_agent_fn: Any
    ) -> None:
        """The body field matches metadata.system_prompt verbatim."""
        response = await get_agent_fn(name="dhara-specialist")

        metadata = response["metadata"]
        body = response["body"]
        assert metadata["system_prompt"] == body, (
            "metadata.system_prompt must equal body verbatim (Phase 3 B-6)"
        )

    async def test_content_hash_round_trips(
        self, get_agent_fn: Any
    ) -> None:
        """``metadata.content_hash`` equals ``sha256(body.encode("utf-8"))``.

        This is the body-integrity round-trip — if it fails, the
        catalog body and the metadata hash disagree, which would
        cause the Phase 2 installer to reject the agent on hash
        verification.
        """
        response = await get_agent_fn(name="dhara-specialist")

        metadata = response["metadata"]
        body = response["body"]
        expected_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        assert metadata["content_hash"] == expected_hash, (
            f"content_hash mismatch: "
            f"got {metadata['content_hash']!r}, "
            f"expected {expected_hash!r}"
        )

    async def test_metadata_id_format(
        self, get_agent_fn: Any
    ) -> None:
        """``metadata.id`` is ``f'{server_key}:{name}:{version}'``."""
        response = await get_agent_fn(name="dhara-specialist")

        metadata = response["metadata"]
        assert metadata["id"] == "dhara:dhara-specialist:1.0.0", (
            f"unexpected id: {metadata['id']!r}"
        )
        assert metadata["server_key"] == "dhara"
        assert metadata["name"] == "dhara-specialist"
        assert metadata["version"] == "1.0.0"

    async def test_metadata_signature_populated(
        self, get_agent_fn: Any
    ) -> None:
        """``metadata.signature`` is non-None; ``server_pubkey_id`` is 16-char hex."""
        response = await get_agent_fn(name="dhara-specialist")

        metadata = response["metadata"]
        assert metadata["signature"], (
            "metadata.signature must be populated after signing"
        )
        assert isinstance(metadata["signature"], str)
        assert metadata["server_pubkey_id"], (
            "metadata.server_pubkey_id must be populated after signing"
        )
        # 16-char hex key_id per Phase 1.5 manifest format.
        assert len(metadata["server_pubkey_id"]) == 16
        int(metadata["server_pubkey_id"], 16)  # parses as hex

    async def test_get_all_3_agents_yield_non_empty_body(
        self, get_agent_fn: Any
    ) -> None:
        """Every one of the 3 starter agents yields a body > 200 chars."""
        for agent_name in (
            "dhara-specialist",
            "time-series-query",
            "adapter-registry-check",
        ):
            response = await get_agent_fn(name=agent_name)
            assert response["success"] is True, (
                f"get_agent({agent_name!r}) failed: {response}"
            )
            body = response["body"]
            assert len(body) > 200, (
                f"agent {agent_name!r} body must be >200 chars; "
                f"got {len(body)}"
            )

    async def test_get_agent_has_scope_section_for_dhara_specialist(
        self, get_agent_fn: Any
    ) -> None:
        """Per Phase 3 task #4 (R-14): dhara-specialist MUST have ``## Scope``.

        The 3 new specialists must each have an explicit "Scope"
        section naming adjacent specialists. This test pins that
        invariant on the dhara-specialist body.
        """
        response = await get_agent_fn(name="dhara-specialist")

        body = response["body"]
        assert "## Scope" in body, (
            "dhara-specialist body MUST contain '## Scope' section "
            "(Phase 3 plan §5 task #4 / R-14)"
        )
        # The Scope section must reference the adjacent specialist.
        assert "oneiric-specialist" in body, (
            "dhara-specialist Scope section must reference adjacent "
            "oneiric-specialist"
        )


class TestGetAgentAllowlistEnforcement:
    """B-4: forbidden ``name`` values return an error envelope."""

    async def test_forbidden_name_returns_error_envelope(
        self, get_agent_fn: Any
    ) -> None:
        """A name with ``/`` returns ``{"success": False, "error": ...}``.

        Per plan §11 B-4, the API boundary rejects forbidden ``name``
        shapes BEFORE constructing the metadata — the response is a
        uniform error envelope, not a Pydantic ValidationError.
        """
        response = await get_agent_fn(name="foo/bar")

        assert response["success"] is False
        assert "error" in response
        # The error message references the allowlist (B-4 contract).
        assert "allowlist" in response["error"].lower()

    async def test_double_dot_name_returns_error_envelope(
        self, get_agent_fn: Any
    ) -> None:
        """A name with ``..`` returns an error envelope (defense-in-depth)."""
        response = await get_agent_fn(name="a..b")

        assert response["success"] is False
        assert "error" in response

    async def test_uppercase_name_returns_error_envelope(
        self, get_agent_fn: Any
    ) -> None:
        """An uppercase name returns an error envelope."""
        response = await get_agent_fn(name="FOO")

        assert response["success"] is False
        assert "error" in response

    async def test_path_traversal_name_returns_error_envelope(
        self, get_agent_fn: Any
    ) -> None:
        """``../../foo`` returns an error envelope (the canonical attack)."""
        response = await get_agent_fn(name="../../foo")

        assert response["success"] is False
        assert "error" in response

    async def test_unknown_name_returns_error_envelope(
        self, get_agent_fn: Any
    ) -> None:
        """A valid allowlist name that is not in the catalog returns
        an error envelope with a "not found" message."""
        response = await get_agent_fn(name="this-agent-does-not-exist")

        assert response["success"] is False
        assert "error" in response
        assert "not found" in response["error"].lower()
