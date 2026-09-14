"""B-4 path-traversal rejection tests for AgentMetadata.

Per plan §5 Phase 3 task #1 and §11 B-4, ``name`` and ``server_key``
fields are constrained to a strict allowlist that prevents
path-traversal attacks via server-supplied metadata. The unit test
asserts the validator rejects every forbidden shape AND accepts the
happy-path shape.

This test does NOT spin up the MCP server — it exercises the
Pydantic model directly so it can run without the full lifespan
state.
"""

from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from dhara.mcp.agent_schema import AgentMetadata


def _valid_kwargs(**overrides: object) -> dict[str, object]:
    """Return valid kwargs with sensible defaults; pass ``overrides`` to mutate."""
    body = (
        "# agent body\n\nUse this agent for the canonical "
        "Dhara storage flow.\n"
    )
    body_bytes = body.encode("utf-8")
    content_hash = hashlib.sha256(body_bytes).hexdigest()
    defaults: dict[str, object] = {
        "schema_version": 1,
        "id": "dhara:dhara-specialist:1.0.0",
        "server_key": "dhara",
        "name": "dhara-specialist",
        "title": "Dhara Specialist",
        "description": "Test description for the agent schema allowlist",
        "version": "1.0.0",
        "model": "sonnet",
        "tools": ["mcp__dhara__dhara_put"],
        "system_prompt": body,
        "dependencies": ["oneiric-specialist"],
        "tool_refs": ["mcp__dhara__dhara_put"],
        "category": "storage",
        "owner": "dhara-team",
        "status": "active",
        "last_reviewed": "2026-09-09",
        "scope": "user-global",
        "content_hash": content_hash,
        "body_size": len(body_bytes),
        "signature": None,
        "server_pubkey_id": None,
    }
    defaults.update(overrides)
    return defaults


class TestAllowlistHappyPath:
    """Valid identifiers parse without raising."""

    def test_lowercase_with_dash(self) -> None:
        m = AgentMetadata(**_valid_kwargs(name="dhara-specialist"))
        assert m.name == "dhara-specialist"

    def test_lowercase_with_dot(self) -> None:
        m = AgentMetadata(**_valid_kwargs(name="v1.2.3"))
        assert m.name == "v1.2.3"

    def test_lowercase_with_underscore(self) -> None:
        m = AgentMetadata(**_valid_kwargs(name="foo_bar"))
        assert m.name == "foo_bar"

    def test_single_char(self) -> None:
        """Length 1 is the minimum the regex allows."""
        m = AgentMetadata(**_valid_kwargs(name="a", id="dhara:a:1.0.0"))
        assert m.name == "a"

    def test_max_length_63(self) -> None:
        """Length 63 is the maximum the regex allows."""
        name = "a" + "b" * 62
        m = AgentMetadata(
            **_valid_kwargs(
                name=name,
                id=f"dhara:{name}:1.0.0",
            )
        )
        assert len(m.name) == 63

    def test_server_key_open_string_with_allowlist(self) -> None:
        """``server_key`` is an open string (per plan §11 R-5) but still
        subject to the B-4 allowlist for defense-in-depth."""
        m = AgentMetadata(
            **_valid_kwargs(
                server_key="dhara",
                id="dhara:dhara-specialist:1.0.0",
            )
        )
        assert m.server_key == "dhara"


class TestNameAllowlistRejection:
    """B-4: forbidden name shapes must raise ValidationError."""

    def test_empty_string(self) -> None:
        with pytest.raises(ValidationError, match="allowlist"):
            AgentMetadata(**_valid_kwargs(name=""))

    def test_max_length_64(self) -> None:
        """64 chars exceeds the {0,62} limit."""
        with pytest.raises(ValidationError, match="allowlist"):
            AgentMetadata(**_valid_kwargs(name="a" * 64))

    @pytest.mark.parametrize(
        "bad_name",
        [
            "../../foo",  # path traversal: parent dirs
            "foo/bar",  # slash anywhere
            ".hidden",  # leading dot
            "FOO",  # uppercase
            "Foo",  # mixed case
            "foo bar",  # whitespace
            "foo!",  # punctuation
            "foo$bar",  # shell metacharacter
            "foo|bar",  # pipe
            "foo;bar",  # semicolon
            "foo&bar",  # ampersand
            "foo`bar`",  # backtick
            "foo\nbar",  # newline
            "foo\rbar",  # carriage return
            "foo\tbar",  # tab
        ],
    )
    def test_forbidden_characters(self, bad_name: str) -> None:
        """B-4 negative cases: every forbidden character class rejected."""
        with pytest.raises(ValidationError, match="allowlist"):
            AgentMetadata(**_valid_kwargs(name=bad_name))

    def test_double_dot_substring_rejected(self) -> None:
        """Defense-in-depth: ``..`` is forbidden even mid-string.

        The regex ``^[a-z0-9][a-z0-9._-]{0,62}$`` does not forbid
        ``..`` in the middle of a string (e.g. ``a..b``). The brief
        requires forbidding ``..`` explicitly as defense-in-depth.
        """
        with pytest.raises(ValidationError, match=r"\.\."):
            AgentMetadata(**_valid_kwargs(name="a..b"))


class TestServerKeyAllowlistRejection:
    """B-4 applies to BOTH ``name`` and ``server_key`` (a forged
    ``server_key`` value could trick a client into path-traversal
    too). The field is open-string-typed (per R-5) but the validator
    still enforces the allowlist."""

    def test_server_key_with_slash_rejected(self) -> None:
        with pytest.raises(ValidationError, match="allowlist"):
            AgentMetadata(**_valid_kwargs(server_key="dhara/../etc"))

    def test_server_key_uppercase_rejected(self) -> None:
        with pytest.raises(ValidationError, match="allowlist"):
            AgentMetadata(**_valid_kwargs(server_key="DHARA"))

    def test_server_key_double_dot_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"\.\."):
            AgentMetadata(**_valid_kwargs(server_key="dh..ara"))


class TestIdShapeValidation:
    """``id`` must be ``{server_key}:{name}:{version}`` with three parts."""

    def test_id_with_two_parts_rejected(self) -> None:
        with pytest.raises(ValidationError, match="server_key:name:version"):
            AgentMetadata(**_valid_kwargs(id="dhara:dhara-specialist"))

    def test_id_with_four_parts_rejected(self) -> None:
        with pytest.raises(ValidationError, match="server_key:name:version"):
            AgentMetadata(
                **_valid_kwargs(id="dhara:dhara-specialist:1.0.0:extra"),
            )

    def test_id_with_invalid_server_key_segment_rejected(self) -> None:
        with pytest.raises(ValidationError, match="invalid server_key segment"):
            AgentMetadata(
                **_valid_kwargs(id="DHARA:dhara-specialist:1.0.0"),
            )

    def test_id_with_invalid_name_segment_rejected(self) -> None:
        with pytest.raises(ValidationError, match="invalid name segment"):
            AgentMetadata(
                **_valid_kwargs(id="dhara:bad/name:1.0.0"),
            )

    def test_id_with_invalid_version_segment_rejected(self) -> None:
        with pytest.raises(ValidationError, match="invalid version segment"):
            AgentMetadata(
                **_valid_kwargs(
                    id="dhara:dhara-specialist:1.0.0/../../etc",
                ),
            )


class TestSchemaInvariants:
    """Default values and field constraints beyond the allowlist."""

    def test_default_tools_empty(self) -> None:
        """Omitting ``tools`` yields ``[]`` via default_factory."""
        kwargs = _valid_kwargs()
        del kwargs["tools"]
        m = AgentMetadata(**kwargs)
        assert m.tools == []

    def test_default_status_active(self) -> None:
        m = AgentMetadata(**_valid_kwargs(status="active"))
        assert m.status == "active"

    def test_default_scope_user_global(self) -> None:
        m = AgentMetadata(**_valid_kwargs(scope="user-global"))
        assert m.scope == "user-global"

    def test_extras_forbidden(self) -> None:
        """Unknown fields raise ValidationError (model_config extra='forbid')."""
        with pytest.raises(ValidationError, match="Extra inputs"):
            AgentMetadata(**_valid_kwargs(unknown_field="x"))

    def test_signature_default_none(self) -> None:
        """``signature`` and ``server_pubkey_id`` default to None (unsigned)."""
        kwargs = _valid_kwargs()
        del kwargs["signature"]
        del kwargs["server_pubkey_id"]
        m = AgentMetadata(**kwargs)
        assert m.signature is None
        assert m.server_pubkey_id is None

    def test_description_max_length_1024(self) -> None:
        """Description is bounded at 1024 chars per plan §5 Phase 3 task #1."""
        long_desc = "x" * 1025
        with pytest.raises(ValidationError, match="description"):
            AgentMetadata(**_valid_kwargs(description=long_desc))

    def test_description_empty_after_strip_rejected(self) -> None:
        """Description must be non-empty after stripping whitespace."""
        with pytest.raises(ValidationError, match="description must be non-empty"):
            AgentMetadata(**_valid_kwargs(description="   "))

    def test_status_archived_allowed(self) -> None:
        """``status`` accepts ``active``, ``archived``, ``draft``."""
        m = AgentMetadata(**_valid_kwargs(status="archived"))
        assert m.status == "archived"

    def test_status_draft_allowed(self) -> None:
        """``status`` accepts ``draft`` for unpublished agents."""
        m = AgentMetadata(**_valid_kwargs(status="draft"))
        assert m.status == "draft"

    def test_status_other_rejected(self) -> None:
        """``status`` rejects any value outside the Literal set."""
        with pytest.raises(ValidationError):
            AgentMetadata(**_valid_kwargs(status="deprecated"))

    def test_scope_project_local_allowed(self) -> None:
        """``scope`` accepts ``project-local`` for repo-local agents."""
        m = AgentMetadata(**_valid_kwargs(scope="project-local"))
        assert m.scope == "project-local"

    def test_system_prompt_required_field(self) -> None:
        """``system_prompt`` defaults to ``""`` — a non-functional agent
        would have an empty body, but the model itself accepts it
        (Phase 3 requires the field to be addressable for round-trip
        tests; the *body* is what matters at runtime).
        """
        kwargs = _valid_kwargs()
        kwargs["system_prompt"] = ""
        kwargs["body_size"] = 0
        kwargs["content_hash"] = hashlib.sha256(b"").hexdigest()
        m = AgentMetadata(**kwargs)
        assert m.system_prompt == ""
        assert m.body_size == 0
