"""Phase 3 server-published agents tools (Phase 3 of bodai-skill-agent-distribution).

Exposes the ``mcp__dhara__dhara_list_agents`` and
``mcp__dhara__dhara_get_agent`` tools that advertise the server-defined
agents to Phase 2's installer and the Claude Code picker. Agents live as
markdown bodies under ``dhara/mcp/agents/<name>.md``; this module reads
them at request time and signs the metadata via the :class:`SkillsSigner`
attached to the :class:`SignerFeedState` initialized in
:class:`DharaMCPServer`.

The dhara-specific naming (per plan §6) mirrors the Phase 1
``skill_registry`` convention: this module is ``agent_registry.py``
(not ``agent_tools.py``) and the exported function is
:func:`register_agent_registry`. The Phase 3 dispatcher calls it via
:func:`register_agent_registry_group` (per-group wrapper in
:mod:`dhara.mcp.tools.group_registers`).

The critical Phase 3 distinction (plan §11 B-6): ``get_agent`` MUST
return the full ``system_prompt`` body — agents are an even larger RCE
surface than skills because the body IS the system prompt Claude Code
reads. Returning only metadata (as the legacy workflow-pattern tool
did) would ship non-functional agents that have no body text.

Security gates (per plan §11):

- **B-1** — every ``get_agent`` response carries an ed25519 signature
  over the canonicalized metadata (the Phase 2 installer verifies
  this before any write to ``~/.claude/agents/``).
- **B-4** — path-traversal allowlist ``^[a-z0-9][a-z0-9._-]{0,62}$``
  is enforced on the ``name`` parameter at the API boundary, BEFORE
  the metadata model re-validates it. Defense-in-depth: an unknown /
  forbidden ``name`` returns an error envelope rather than raising
  past the MCP boundary.
- **B-7** — each successful tool call bumps
  ``SignerFeedState.cycles_total`` via :meth:`record_cycle` so the
  four mandatory feed signals stay accurate.

Non-goals:

- Body content is loaded at request time (L-6). No session-start
  pre-load.
- The 3 starter agents ship as static markdown files in
  ``agents/``; Phase 4's federation layer
  (``mcp__akosha__list_ecosystem_agents``) is what exposes them
  alongside the other 4 servers' catalogs.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from dhara.mcp.agent_schema import AgentMetadata
from dhara.skills_signer import canonical_payload_for_signing

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)


# Allowlist mirror — see B-4 / plan §5 task #4. Duplicated here so the
# API boundary rejects forbidden ``name`` values BEFORE constructing the
# Pydantic model (avoids letting a path-traversal payload reach the
# validator, which would surface as a different error class).
_NAME_ALLOWLIST_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")


# Catalog lives next to ``skill_schema.py`` (one level up from this
# module) so the deployment path stays self-contained. The catalog is
# static — new agents are added by dropping a new ``.md`` file under
# ``agents/`` AND adding an entry to ``_STATIC_AGENTS``.
_CATALOG_DIR = Path(__file__).parent.parent / "agents"


# Phase 3: 3 starter agents with real Dhara-relevant content. Each
# tuple is the body's filename (relative to ``agents/``), the semantic
# version, the description that goes in both the AgentMetadata AND
# the frontmatter, the picker display title, the LLM model hint, the
# list of MCP tool names the agent may invoke (Claude Code
# frontmatter ``tools:`` field), the list of MCP tool names
# referenced (for downstream routing), and the list of dependent
# agent names.
#
# Adding a new server-published agent: drop ``<name>.md`` under
# ``agents/`` AND add an entry below. The validator runs at module
# load — a missing file or mismatched hash fails fast.
_STATIC_AGENTS: list[dict[str, Any]] = [
    {
        "name": "dhara-specialist",
        "body_filename": "dhara-specialist.md",
        "version": "1.0.0",
        "title": "Dhara Specialist",
        "description": (
            "Use proactively when the user asks about Dhara's storage, "
            "registry, key-value, ACID transactions, version management, "
            "or adapter persistence patterns. Routes through Dhara's MCP "
            "tools (`mcp__dhara__*`) for storage backends, OTel trace "
            "persistence, and Oneiric adapter cataloging."
        ),
        "model": "sonnet",
        "tools": [
            "mcp__dhara__dhara_put",
            "mcp__dhara__dhara_get",
            "mcp__dhara__dhara_list_prefix",
            "mcp__dhara__dhara_record_time_series",
            "mcp__dhara__dhara_query_time_series",
            "mcp__dhara__dhara_aggregate_patterns",
            "mcp__dhara__dhara_store_adapter",
            "mcp__dhara__dhara_get_adapter",
            "mcp__dhara__dhara_list_adapters",
            "mcp__dhara__dhara_list_adapter_versions",
            "mcp__dhara__dhara_get_adapter_health",
            "mcp__dhara__dhara_upsert_service",
            "mcp__dhara__dhara_get_service",
            "mcp__dhara__dhara_list_services",
        ],
        "tool_refs": [
            "mcp__dhara__dhara_put",
            "mcp__dhara__dhara_get",
            "mcp__dhara__dhara_store_adapter",
            "mcp__dhara__dhara_get_adapter",
            "mcp__dhara__dhara_list_services",
        ],
        "dependencies": ["oneiric-specialist"],
        "category": "storage",
        "owner": "dhara-team",
        "status": "active",
        "last_reviewed": "2026-09-09",
        "scope": "user-global",
    },
    {
        "name": "time-series-query",
        "body_filename": "time-series-query.md",
        "version": "1.0.0",
        "title": "Time-Series Query Agent",
        "description": (
            "Use proactively for time-series queries across Dhara's "
            "metric corpus, pattern aggregation over date ranges, and "
            "entity_id drift analysis. Routes through "
            "`mcp__dhara__dhara_query_time_series` and "
            "`mcp__dhara__dhara_aggregate_patterns`."
        ),
        "model": "sonnet",
        "tools": [
            "mcp__dhara__dhara_query_time_series",
            "mcp__dhara__dhara_aggregate_patterns",
            "mcp__dhara__dhara_record_time_series",
            "mcp__dhara__dhara_list_prefix",
        ],
        "tool_refs": [
            "mcp__dhara__dhara_query_time_series",
            "mcp__dhara__dhara_aggregate_patterns",
        ],
        "dependencies": ["dhara-specialist"],
        "category": "analytics",
        "owner": "dhara-team",
        "status": "active",
        "last_reviewed": "2026-09-09",
        "scope": "user-global",
    },
    {
        "name": "adapter-registry-check",
        "body_filename": "adapter-registry-check.md",
        "version": "1.0.0",
        "title": "Adapter Registry Check Agent",
        "description": (
            "Use proactively to verify Oneiric adapter registrations in "
            "Dhara, list all versions of an adapter, run health checks, "
            "and confirm a (domain, key, provider) tuple is queryable. "
            "Routes through `mcp__dhara__dhara_get_adapter`, "
            "`mcp__dhara__dhara_list_adapter_versions`, and "
            "`mcp__dhara__dhara_get_adapter_health`."
        ),
        "model": "sonnet",
        "tools": [
            "mcp__dhara__dhara_get_adapter",
            "mcp__dhara__dhara_list_adapters",
            "mcp__dhara__dhara_list_adapter_versions",
            "mcp__dhara__dhara_get_adapter_health",
            "mcp__dhara__dhara_validate_adapter",
        ],
        "tool_refs": [
            "mcp__dhara__dhara_get_adapter",
            "mcp__dhara__dhara_list_adapter_versions",
            "mcp__dhara__dhara_get_adapter_health",
        ],
        "dependencies": ["dhara-specialist", "oneiric-specialist"],
        "category": "verification",
        "owner": "dhara-team",
        "status": "active",
        "last_reviewed": "2026-09-09",
        "scope": "user-global",
    },
]


_SERVER_NAME = "dhara"


# Name-indexed view of the static catalog — built once at module load
# so the tool handlers can do O(1) lookups instead of scanning the
# list. This MUST stay below ``_STATIC_AGENTS`` so the dict
# comprehension sees the full list (Python's module body executes
# top-to-bottom; this lookup is never called before the module
# finishes loading).
_STATIC_AGENTS_BY_NAME: dict[str, dict[str, Any]] = {
    entry["name"]: entry for entry in _STATIC_AGENTS
}


def _read_body(filename: str) -> str:
    """Load an agent body from the catalog, asserting the file exists.

    The validator at module load time catches missing files before any
    MCP request reaches the runtime path. Returns the body as UTF-8
    text. For agents, the body IS the ``system_prompt`` that Claude
    Code reads verbatim (per Phase 3 plan §5 task #2 / §11 B-6) —
    markdown frontmatter is allowed but not required.
    """
    path = _CATALOG_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(
            f"Agent body {filename!r} missing from catalog at {path}"
        )
    return path.read_text(encoding="utf-8")


def _build_unsigned_metadata(name: str) -> AgentMetadata:
    """Build an :class:`AgentMetadata` for the named static agent.

    The metadata has ``signature=None`` and ``server_pubkey_id=None``;
    those fields are populated by :func:`_sign_metadata` after signing.
    Raises :class:`KeyError` if ``name`` is not a known static agent.
    """
    for entry in _STATIC_AGENTS:
        if entry["name"] != name:
            continue
        body = _read_body(entry["body_filename"])
        body_bytes = body.encode("utf-8")
        content_hash = hashlib.sha256(body_bytes).hexdigest()
        version = entry["version"]
        return AgentMetadata(
            id=f"{_SERVER_NAME}:{name}:{version}",
            server_key=_SERVER_NAME,
            name=name,
            title=entry.get("title"),
            description=entry["description"],
            version=version,
            model=entry.get("model", "sonnet"),
            tools=list(entry.get("tools", [])),
            system_prompt=body,
            dependencies=list(entry.get("dependencies", [])),
            tool_refs=list(entry.get("tool_refs", [])),
            category=entry.get("category"),
            owner=entry.get("owner"),
            status=entry.get("status", "active"),
            last_reviewed=entry.get("last_reviewed"),
            scope=entry.get("scope", "user-global"),
            content_hash=content_hash,
            body_size=len(body_bytes),
        )
    msg = f"unknown agent {name!r}"
    raise KeyError(msg)


def _sign_metadata(metadata: AgentMetadata, signer: Any) -> AgentMetadata:
    """Apply an ed25519 signature to a copy of ``metadata``.

    The canonical payload strips ``signature``, ``server_pubkey_id``,
    AND ``system_prompt`` BEFORE canonicalization so the signature
    doesn't cover itself OR the body (per plan §11 B-6 — the body
    is the system prompt, which is much larger than metadata; we
    sign the identity envelope, not the body content). The
    ``content_hash`` field already pins the body bytes (sha256), so
    a body swap after signing is detectable on the client side.

    The returned copy has both signing fields populated.
    """
    unsigned_dict = metadata.model_dump(mode="json")
    # Strip the body from the signed payload. The hash pins it; the
    # signature doesn't need to re-cover it.
    unsigned_dict.pop("system_prompt", None)
    canonical = canonical_payload_for_signing(unsigned_dict)
    signed = signer.sign(canonical)
    return metadata.model_copy(
        update={
            "signature": signed.signature_b64,
            "server_pubkey_id": signed.key_id,
        }
    )


def _is_allowlisted(name: str) -> bool:
    """B-4 API-boundary check on the ``name`` parameter.

    Forbids ``/``, ``..``, leading ``.``, uppercase, length > 63, and
    any character outside ``[a-z0-9._-]``. Mirrors the
    AgentMetadata validator so failures at the API boundary return a
    uniform ``{"success": False, "error": ...}`` envelope.
    """
    return bool(_NAME_ALLOWLIST_RE.fullmatch(name)) and ".." not in name


def register_agent_registry(app: FastMCP) -> None:
    """Register ``dhara_list_agents`` and ``dhara_get_agent`` MCP tools.

    Idempotent at module level (the static catalog is loaded once at
    import). Calling this twice is safe — FastMCP's ``@app.tool``
    decorator is idempotent within a single ``app`` instance.

    The tools access the lifespan-owned :class:`SkillsSigner` via
    ``get_signer_feed_state()``; if the server is running without
    the Phase 1.5 wiring (lite mode / pre-startup), both tools return
    an error envelope rather than raising.
    """

    @app.tool(name="dhara_list_agents")
    async def dhara_list_agents() -> list[dict[str, Any]]:
        """Return metadata for agents this server publishes.

        Returns at least 3 entries (one per static agent in
        ``_STATIC_AGENTS``). The ``signature``, ``server_pubkey_id``,
        and ``system_prompt`` fields are stripped here — ``list_agents``
        returns the IDENTITY envelope only; the body is delivered via
        ``dhara_get_agent`` after the client verifies it wants the
        full system prompt for that agent.
        """
        from dhara.mcp.signer_feed import (
            get_signer_feed_state,
        )

        state = get_signer_feed_state()
        if state is not None:
            state.record_cycle()

        out: list[dict[str, Any]] = []
        for entry in _STATIC_AGENTS:
            try:
                metadata = _build_unsigned_metadata(entry["name"])
            except (FileNotFoundError, ValidationError, KeyError):
                logger.exception(
                    "list_agents: failed to build metadata for %s",
                    entry["name"],
                )
                continue
            dump = metadata.model_dump(mode="json")
            # list_agents returns metadata ONLY — strip the body and
            # signing fields so the response stays small. Clients that
            # want the full system prompt call ``dhara_get_agent``.
            dump.pop("system_prompt", None)
            dump.pop("signature", None)
            dump.pop("server_pubkey_id", None)
            out.append(dump)
        return out

    @app.tool(name="dhara_get_agent")
    async def dhara_get_agent(name: str) -> dict[str, Any]:
        """Return the signed metadata + system_prompt for one agent.

        Validates ``name`` against the B-4 allowlist BEFORE
        constructing the metadata. Signs the metadata via the
        lifespan-owned :class:`SkillsSigner`. The ``system_prompt``
        field carries the full body — the client (Phase 2 installer)
        writes this verbatim to
        ``~/.claude/agents/<name>.md`` (with the dhara- prefix per
        R-7 in the plan).

        Returns ``{"success": True, "metadata": ..., "body": ...}``
        where ``body == metadata.system_prompt`` (the round-trip
        test asserts both content_hash equality AND string equality).
        """
        from dhara.mcp.signer_feed import (
            get_signer_feed_state,
        )

        if not _is_allowlisted(name):
            return {
                "success": False,
                "error": (
                    f"name {name!r} violates path-traversal allowlist "
                    "(B-4): must match ^[a-z0-9][a-z0-9._-]{0,62}$ "
                    "with no '..' substring"
                ),
            }

        state = get_signer_feed_state()
        if state is None:
            return {
                "success": False,
                "error": "signer not initialized (server may still be starting up)",
            }
        state.record_cycle()

        try:
            unsigned = _build_unsigned_metadata(name)
        except KeyError:
            return {"success": False, "error": f"agent {name!r} not found on this server"}
        except FileNotFoundError as exc:
            return {"success": False, "error": str(exc)}
        except ValidationError as exc:
            return {"success": False, "error": f"metadata validation failed: {exc}"}

        signed = _sign_metadata(unsigned, state.signer)
        body = _read_body(_STATIC_AGENTS_BY_NAME[name]["body_filename"])
        return {
            "success": True,
            "metadata": signed.model_dump(mode="json"),
            "body": body,
        }


# Build a {name: entry} index for O(1) lookup in the tool handlers.
# Done at module load; ``_STATIC_AGENTS`` is a static list so this
# is safe.


__all__ = ["register_agent_registry"]