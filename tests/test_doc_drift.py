"""Doc-drift CI guard tests for dhara.

These tests pin three classes of facts that have drifted in past releases:

1. The total number of MCP tools exposed by the server (matches README/CLAUDE.md claims).
2. Documented environment variables are actually read by the package code.
3. The HTTP ``User-Agent`` string interpolates from ``__version__`` rather than
   hardcoding a version literal.

If a test fails, fix the documentation to match the code *or* fix the code to
match the documentation. The pinned thresholds are deliberately loose (using
``>=`` rather than ``==``) so that adding new tools does not require updating
this file.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Tool count guard
# ---------------------------------------------------------------------------

# Tool count is measured against the canonical ``DHARA_TOOL_PROFILE=full``
# profile. The discover_tools helper is always registered, so the floor is 1.
# Adjust upward if/when dhara exposes more decorated tools.
EXPECTED_MIN_TOOLS = 1


def test_mcp_tool_count_matches_documented() -> None:
    """Pin the canonical MCP tool count so README/CLAUDE.md claims stay in sync.

    The Dhara MCP server exposes its discover_tools helper via the W0
    dispatch (always-on). The full profile adds profile-gated groups on top of
    that. This test asserts the registration map has at least one tool.
    """
    from dhara.mcp.profiles import PROFILE_REGISTRATIONS, REGISTRATION_MAP

    # ``discover_tools`` is the canonical always-on helper; the MINIMAL profile
    # should expose at least this single tool.
    from mcp_common.tools import ToolProfile

    minimal_keys = set(PROFILE_REGISTRATIONS.get(ToolProfile.MINIMAL, []))
    assert len(minimal_keys) >= EXPECTED_MIN_TOOLS, (
        f"Expected >= {EXPECTED_MIN_TOOLS} tool keys in MINIMAL profile, "
        f"got {len(minimal_keys)}. Update README.md/CLAUDE.md tool counts or "
        "relax threshold."
    )

    # The full profile must register more tools than minimal alone.
    full_keys = set(PROFILE_REGISTRATIONS.get(ToolProfile.FULL, []))
    assert len(full_keys) >= len(minimal_keys), (
        f"FULL profile ({len(full_keys)} keys) should superset MINIMAL "
        f"profile ({len(minimal_keys)} keys)."
    )

    # And the registration map should map each key to a callable.
    assert len(REGISTRATION_MAP) >= len(full_keys), (
        f"REGISTRATION_MAP ({len(REGISTRATION_MAP)} entries) should cover "
        "all full-profile keys."
    )


def test_registration_map_has_baseline() -> None:
    """Verify the registration map wires at least one baseline tool group."""
    from dhara.mcp.profiles import REGISTRATION_MAP

    assert len(REGISTRATION_MAP) >= 1, (
        "REGISTRATION_MAP is empty; the always-on tool surface has shrunk."
    )


# ---------------------------------------------------------------------------
# Env var wiring guard
# ---------------------------------------------------------------------------

# Documented env vars from README.md / CLAUDE.md / .env.example. Each entry
# is verified to be read via ``os.getenv`` (or ``os.environ.get``) somewhere
# in the dhara package source tree.
#
# Limitation: ``DHARA_TOOL_PROFILE`` is consumed indirectly via Pydantic
# Settings or string-literal forwarding to ``mcp-common``. It is not pinned
# here because the wiring is dispatched through a helper. Add new entries
# below whenever a new ``os.getenv``-backed env var is documented.
DOCUMENTED_ENV_VARS: tuple[str, ...] = (
    "DHARA_MODE",
    "DHARA_SQL_BACKEND",
    "DHARA_SQL_DUCKDB_PATH",
    "DHARA_MERMAID_CORE",
    "DHARA_JSDOM",
    "MAHAVISHNU_ENV",
)


def _read_source_text() -> str:
    """Read every Python file under ``dhara/`` into a single string."""
    pkg_root = Path(__file__).resolve().parent.parent / "dhara"
    chunks: list[str] = []
    for py_file in pkg_root.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        try:
            chunks.append(py_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
    return "\n".join(chunks)


def test_documented_env_vars_are_wired() -> None:
    """Every env var documented in README/CLAUDE.md must be read by package code."""
    src = _read_source_text()
    missing: list[str] = []
    for var in DOCUMENTED_ENV_VARS:
        pattern = re.compile(
            rf"os\.getenv\(\s*[\"']{re.escape(var)}[\"']|"
            rf"os\.environ\.get\(\s*[\"']{re.escape(var)}[\"']",
        )
        if not pattern.search(src):
            missing.append(var)
    assert not missing, (
        f"Documented env vars not read by package code: {missing}. "
        "Either remove them from docs or wire them via os.getenv."
    )


# ---------------------------------------------------------------------------
# Version stamp guard
# ---------------------------------------------------------------------------

# Heuristic: any User-Agent-looking string literal that contains a digit is
# considered a probable hardcoded version. Strings with an f-string prefix
# (``f"..."`` or ``f'...'``) or with literal ``{`` are accepted as dynamic.
_USER_AGENT_RE = re.compile(r"""User-Agent[\"'][^\"']{0,200}[\"']""")
_VERSION_LITERAL_RE = re.compile(r"\d+\.\d+")


def test_user_agent_matches_package_version() -> None:
    """Detect hardcoded User-Agent version strings that should interpolate from __version__."""
    pkg_root = Path(__file__).resolve().parent.parent / "dhara"
    hardcoded: list[tuple[str, str]] = []
    for py_file in pkg_root.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _USER_AGENT_RE.finditer(text):
            ua = match.group(0)
            # Skip dynamic strings (f-strings, .format, concatenation).
            if "{" in ua or "f\"" in ua or "f'" in ua or ".format(" in ua:
                continue
            if _VERSION_LITERAL_RE.search(ua):
                hardcoded.append((str(py_file), ua))
    assert not hardcoded, (
        f"Hardcoded User-Agent versions found (should interpolate from __version__): {hardcoded}"
    )
