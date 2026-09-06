"""Regression test for the FastMCP ecosystem pin baseline.

Ensures the installed ``fastmcp`` runtime version meets the ecosystem-wide
floor (>=3.4) that the mcp-common foundation pins for every consumer repo.

Also asserts the pyproject.toml pin (read from disk at test time) matches
the post-v4-migration ecosystem-wide pin ``fastmcp>=3.4.0,<5`` (FastMCP v4
migration completed 2026-09-06, commit ``01722ec``) so a regression in the
declared floor trips this test independently of the lockfile state.

If this test ever fails, it means either:
- The lockfile resolved to a FastMCP version below the ecosystem baseline, or
- The pyproject.toml pin regressed to anything outside ``>=3.4.0,<5``.
"""

from __future__ import annotations

import re
from pathlib import Path

from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _read_pyproject_pin() -> str:
    """Return the raw fastmcp dependency declaration line from pyproject.toml.

    Returns the substring that follows the ``fastmcp`` package key in the
    ``[project] dependencies`` list. Empty string if no pin is declared.
    """
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'"fastmcp(~=|>=|==)[^"]*"', text)
    return match.group(0).strip('"') if match else ""


def test_fastmcp_version_meets_ecosystem_floor() -> None:
    """Installed fastmcp must be >=3.4.0 (Plan 7 ecosystem baseline)."""
    import fastmcp

    installed = Version(fastmcp.__version__)
    minimum = Version("3.4")
    assert installed >= minimum, (
        f"fastmcp {installed} is below the Plan 7 ecosystem floor "
        f"({minimum}); pin fastmcp>=3.4.0,<5 in pyproject.toml."
    )


def test_pyproject_pin_matches_plan7_baseline() -> None:
    """The pyproject.toml fastmcp pin must be ``>=3.4.0,<5`` (post-v4-migration)."""
    pin = _read_pyproject_pin()
    assert pin, "fastmcp pin missing from pyproject.toml dependencies"
    # Accept only the exact post-v4-migration pin format.
    assert pin == "fastmcp>=3.4.0,<5", (
        f"pyproject.toml fastmcp pin is {pin!r}; the FastMCP v4 migration "
        f"(commit 01722ec, 2026-09-06) requires the exact pin "
        f"'fastmcp>=3.4.0,<5'."
    )
