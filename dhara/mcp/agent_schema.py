"""Agent metadata schema (Phase 3 of bodai-skill-agent-distribution plan).

Defines :class:`AgentMetadata`, the canonical Pydantic v2 model for agent
metadata advertised by every Bodai MCP server via ``mcp__<server>__list_agents``
and ``mcp__<server>__get_agent``. Mirrors the Phase 1 ``SkillMetadata``
allowlist semantics (B-4) on ``name``; the ``server`` field is an open
string (per plan §11 B-6 / R-5) because federation across replicas may
introduce new server keys without a redeploy.

Schema ownership
----------------

Per plan §10.3.5 (extended to Phase 3), the schema is canonical across
all 5 replicas (akosha, mahavishnu, session-buddy, dhara, crackerjack).
This file IS the canonical source; other servers either import it
directly (cross-repo import from ``akosha.mcp.agent_schema``) or copy
its contents verbatim.

The Phase 3 plan distinguishes this model from ``SkillMetadata`` by:

- carrying the FULL ``system_prompt`` body (not just metadata) so
  ``get_agent`` can return a non-empty body without a separate fetch
- ``server_key`` is open string (not Literal) to allow new server keys
  without redeploy — but the validator still rejects ``/``, ``..``,
  uppercase, length > 63, and any character outside ``[a-z0-9._-]``
- ``status`` has a Literal of ``active | archived | draft`` (server
  may publish draft entries; client must filter)
- ``scope`` is a Literal of ``user-global | project-local`` (Phase 2
  install writes to ``user-global`` for the picker)

Path-traversal allowlist (B-4)
------------------------------

Per plan §11 B-4, ``name`` and ``server_key`` fields are constrained
to the same strict allowlist as ``SkillMetadata.name`` /
``SkillMetadata.server``. The regex forbids:

- ``/`` (anywhere)
- leading ``.`` (cannot start with a dot)
- uppercase characters
- any character outside ``[a-z0-9._-]``
- total length > 63 (the regex ``{0,62}`` after the first char)

The validator runs an extra explicit check for the substring ``..``
defense-in-depth.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Same allowlist regex as SkillMetadata (B-4 / plan §5 task #4, §11).
# Anchored to the full string. The first character is one lowercase
# letter or digit; the remaining 0..62 characters are drawn from
# ``[a-z0-9._-]``. Total length is therefore 1..63 characters.
_NAME_OR_SERVER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")


class AgentMetadata(BaseModel):
    """Canonical agent metadata advertised by every Bodai MCP server.

    The schema is identical across all 5 Bodai servers (akosha,
    mahavishnu, session-buddy, dhara, crackerjack). It carries:

    - identity (``id``, ``server_key``, ``name``, ``version``)
    - picker display (``title``, ``description``)
    - routing hints (``tools``, ``dependencies``, ``tool_refs``)
    - classification (``category``, ``owner``, ``status``, ``last_reviewed``, ``scope``)
    - body integrity (``content_hash`` is the SHA-256 of ``system_prompt`` bytes)
    - signing payload (``signature``, ``server_pubkey_id``)
    - routing model (``model`` — sonnet/opus/haiku/etc.)
    - full body (``system_prompt`` — Claude Code reads this verbatim)

    The ``signature`` and ``server_pubkey_id`` fields are populated by
    :mod:`dhara.mcp.tools.agent_registry` AFTER signing. The canonical
    signing payload is the model_dump of this model with ``signature``,
    ``server_pubkey_id``, and ``system_prompt`` stripped (the body is
    not part of the signed identity envelope — see plan §11 B-6).
    """

    model_config = ConfigDict(
        extra="forbid",
        # ``str_strip_whitespace`` is intentionally NOT set: per Phase 3
        # §11 B-6, the ``system_prompt`` field carries the agent body
        # verbatim and ``content_hash`` covers those exact bytes.
        # ``validate_assignment`` lets us re-validate when the tool
        # code sets ``metadata.signature`` after construction.
        validate_assignment=True,
    )

    schema_version: Literal[1] = 1

    # ``id`` is the globally unique agent identifier —
    # ``{server_key}:{name}:{version}``. Validators below enforce the
    # allowlist on the constituent fields; ``id`` is built from them
    # and is therefore constrained transitively.
    id: str

    # Open string (NOT Literal) per plan §11 R-5 — federation may
    # introduce new server keys without a redeploy. Validated against
    # the same allowlist as ``name`` for defense-in-depth.
    server_key: str

    # Allowlist regex enforced below; regex matches ``[a-z0-9._-]``
    # with length 1..63.
    name: str

    # Picker display name (e.g. ``"Dhara Specialist"``); optional
    # because some agents don't have a human-facing title separate
    # from ``name``.
    title: str | None = None

    # Single-sentence "Use proactively for ..." description shown in
    # the Claude Code picker. Same 1024-char cap as SkillMetadata.
    description: str = Field(max_length=1024)

    # Semver string (e.g. ``1.0.0``). Required for federation tie-break
    # when the same agent name exists on multiple servers.
    version: str = "0.0.0"

    # LLM model hint for the picker / dispatcher. Open string (NOT
    # Literal) because the picker accepts user-defined model aliases.
    model: str = "sonnet"

    # EXACT tool names (Claude Code frontmatter format), NOT regex.
    # The picker forwards these to the runtime as the agent's
    # available tools.
    tools: list[str] = Field(default_factory=list)

    # Full system prompt body — Claude Code reads this verbatim, NOT
    # the metadata. Critical for Phase 3: agents without a body are
    # non-functional (plan §11 B-6).
    system_prompt: str = ""

    # Adjacent agent names this agent depends on (e.g. oneiric-specialist
    # depends on oneiric-core). Open list.
    dependencies: list[str] = Field(default_factory=list)

    # MCP tool names referenced by the body. Open list.
    tool_refs: list[str] = Field(default_factory=list)

    category: str | None = None
    owner: str | None = None
    status: Literal["active", "archived", "draft"] | None = "active"
    last_reviewed: str | None = None

    # ``user-global`` → install to ``~/.claude/agents/<name>.md``
    # ``project-local`` → install to ``<repo>/.claude/agents/<name>.md``
    scope: Literal["user-global", "project-local"] = "user-global"

    # Body integrity. ``content_hash`` is the lowercase hex SHA-256 of
    # the ``system_prompt`` bytes; the round-trip test asserts they
    # match. ``body_size`` is the byte length.
    content_hash: str
    body_size: int

    # Signing payload. Both fields are populated by the tool handler
    # AFTER signing; ``signature`` carries the base64 ed25519 signature
    # and ``server_pubkey_id`` is the 16-char hex ``key_id`` from the
    # server's pubkey manifest.
    signature: str | None = None
    server_pubkey_id: str | None = None

    @field_validator("server_key", "name")
    @classmethod
    def _validate_allowlist(cls, value: str) -> str:
        """Enforce B-4 path-traversal allowlist on ``name`` and ``server_key``.

        Forbids ``/``, leading ``.``, uppercase characters, any character
        outside ``[a-z0-9._-]``, total length > 63, and the literal
        substring ``..`` (defense-in-depth).
        """
        if not _NAME_OR_SERVER_RE.fullmatch(value):
            raise ValueError(
                f"value {value!r} does not match allowlist regex "
                r"'^[a-z0-9][a-z0-9._-]{0,62}$' "
                "(forbidden: '/', uppercase, leading '.', length > 63)"
            )
        if ".." in value:
            raise ValueError(f"value {value!r} contains forbidden substring '..'")
        return value

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        """Description must be non-empty after stripping whitespace."""
        if not value.strip():
            raise ValueError("description must be non-empty")
        return value

    @field_validator("id")
    @classmethod
    def _validate_id_shape(cls, value: str) -> str:
        """``id`` must be ``{server_key}:{name}:{version}`` with no leading dot or slash.

        The constituent fields are individually validated by their own
        validators; this check ensures the composite matches the
        documented format and disallows extra colons in unexpected places.
        """
        if not value:
            raise ValueError("id must be non-empty")
        parts = value.split(":")
        if len(parts) != 3:
            raise ValueError(
                f"id {value!r} must be 'server_key:name:version' "
                "(exactly 3 colon-separated parts)"
            )
        server_key, name, version = parts
        if not _NAME_OR_SERVER_RE.fullmatch(server_key):
            raise ValueError(
                f"id {value!r} has invalid server_key segment {server_key!r}"
            )
        if not _NAME_OR_SERVER_RE.fullmatch(name):
            raise ValueError(f"id {value!r} has invalid name segment {name!r}")
        if not version or "/" in version or ".." in version:
            raise ValueError(f"id {value!r} has invalid version segment {version!r}")
        return value


__all__ = ["AgentMetadata"]
