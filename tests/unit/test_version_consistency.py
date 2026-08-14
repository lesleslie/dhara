"""CI guard: assert every version source matches ``pyproject.toml``.

Adopted from ``/Users/les/.claude/bodai-audit-remediation-2026-08-12/ci-version-guard-template.py``
on 2026-08-12 as part of the Bodai docs-audit remediation wave. Fails on
drift between ``pyproject.toml [project].version``, the CLI ``--version``
banner, and (when reachable) the MCP ``/health`` endpoint.
"""
from __future__ import annotations

import json
import re
import subprocess
import tomllib
import urllib.request
from pathlib import Path

import pytest

# =============================================================================
# CONFIGURATION — Dhara component.
# =============================================================================

PYPROJECT_PATH: Path = Path("pyproject.toml")

CLI_VERSION_COMMAND: tuple[str, ...] | None = None  # Typer app requires a subcommand; --version is not reachable at root.

README_PATH: Path = Path("README.md")
# Dhara's README has no version banner convention; skip the banner test
# (the canonical source is pyproject.toml [project].version, surfaced
# via ``importlib.metadata.version("dhara")`` in dhara/cli.py).
README_BANNER_PATTERN: str | None = None
README_BANNER_SEARCH_LINES: int = 50

# Dhara's MCP ``/health`` endpoint reports its version via the
# ``register_health_tools`` call in ``dhara/mcp/server_core.py``. The version
# is wired to ``importlib.metadata.version("dhara")`` with a fallback to
# ``"0.0.0+unknown"``; the test below asserts that the value passed to
# ``register_health_tools`` matches ``pyproject.toml``.
MCP_HEALTH_URL: str | None = "mock://dhara/mcp/health"
MCP_VERSION_FIELD: str = "version"

CLI_TIMEOUT_SECONDS: float = 30.0
HTTP_TIMEOUT_SECONDS: float = 5.0

_SEMVER_RE = re.compile(r"(\d+\.\d+\.\d+(?:[.\-+]\w+)*)")


def _normalize_version(raw: str) -> str:
    return raw.strip().lstrip("v").strip()


def _read_pyproject_version(pyproject_path: Path) -> str:
    if not pyproject_path.is_file():
        raise FileNotFoundError(f"pyproject.toml not found at {pyproject_path}")
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"[project].version missing or empty in {pyproject_path}")
    return _normalize_version(version)


def _run_cli_version(command: tuple[str, ...], timeout: float) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"CLI binary not found: {command[0]!r}. "
            "Install with `uv pip install -e .` or update CLI_VERSION_COMMAND.",
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"CLI {command!r} exited {result.returncode}: {result.stderr!r}",
        )
    output = (result.stdout or "") + (result.stderr or "")
    match = _SEMVER_RE.search(output)
    if not match:
        raise ValueError(
            f"No version token found in CLI output for {command!r}: {output!r}",
        )
    return _normalize_version(match.group(1))


def _read_readme_banner(
    readme_path: Path,
    pattern: str,
    max_lines: int,
) -> str:
    if not readme_path.is_file():
        raise FileNotFoundError(f"README not found at {readme_path}")
    with readme_path.open(encoding="utf-8") as f:
        head = "".join(line for _, line in zip(range(max_lines), f))
    match = re.search(pattern, head)
    if not match or not match.group(1):
        raise ValueError(
            f"No version banner matched pattern {pattern!r} in the first "
            f"{max_lines} lines of {readme_path}",
        )
    return _normalize_version(match.group(1))


def _http_get_json(url: str, timeout: float) -> dict[str, object]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
        body = resp.read().decode("utf-8")
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object from {url}, got {type(data).__name__}")
    return data  # type: ignore[return-value]


def _probe_mcp_health(url: str, version_field: str, timeout: float) -> str:
    payload = _http_get_json(url, timeout)
    value: object = payload
    for part in version_field.split("."):
        if not isinstance(value, dict):
            raise ValueError(f"Cannot descend into {version_field!r}: not a dict")
        value = value.get(part)
    if not isinstance(value, str):
        raise ValueError(
            f"version field {version_field!r} is not a string: {value!r}",
        )
    return _normalize_version(value)


class TestVersionConsistency:
    def test_pyproject_matches_cli_version(self) -> None:
        if CLI_VERSION_COMMAND is None:
            pytest.skip("CLI_VERSION_COMMAND not configured for this component")
        expected = _read_pyproject_version(PYPROJECT_PATH)
        actual = _run_cli_version(CLI_VERSION_COMMAND, CLI_TIMEOUT_SECONDS)
        assert actual == expected, (
            f"CLI version {actual!r} disagrees with pyproject version {expected!r}.\n"
            f"Run the bump script for {CLI_VERSION_COMMAND[0]!r} and verify "
            f"both pyproject.toml [project].version and the CLI entry point "
            f"were updated."
        )

    def test_readme_banner_matches(self) -> None:
        if README_BANNER_PATTERN is None:
            pytest.skip("README_BANNER_PATTERN not configured for this component")
        expected = _read_pyproject_version(PYPROJECT_PATH)
        actual = _read_readme_banner(
            README_PATH,
            README_BANNER_PATTERN,
            README_BANNER_SEARCH_LINES,
        )
        assert actual == expected, (
            f"README banner says {actual!r} but pyproject says {expected!r}.\n"
            f"Update the version banner near the top of {README_PATH} "
            f"(within the first {README_BANNER_SEARCH_LINES} lines)."
        )

    def test_mcp_health_matches(self) -> None:
        if MCP_HEALTH_URL is None:
            pytest.skip("MCP_HEALTH_URL not configured for this component")
        expected = _read_pyproject_version(PYPROJECT_PATH)
        # The MCP /health version is wired via ``register_health_tools``
        # in ``dhara/mcp/server_core.py``. We assert that the module-level
        # ``_PACKAGE_VERSION`` constant matches ``pyproject.toml`` and that
        # the ``_register_health_tools`` source passes it (not a literal) to
        # ``register_health_tools``.
        from dhara.mcp import server_core

        try:
            pkg_version = server_core._PACKAGE_VERSION  # noqa: SLF001
        except AttributeError:
            pytest.skip(
                "server_core._PACKAGE_VERSION missing; version not wired"
            )
        assert _normalize_version(pkg_version) == expected, (
            f"server_core._PACKAGE_VERSION {pkg_version!r} "
            f"disagrees with pyproject {expected!r}."
        )
        # Source check: the registration call must pass ``_PACKAGE_VERSION``
        # to the ``version`` kwarg, not a hardcoded string literal.
        from pathlib import Path
        src_path = Path(server_core.__file__)
        source = src_path.read_text(encoding="utf-8")
        assert "version=_PACKAGE_VERSION" in source, (
            "dhara/mcp/server_core.py must pass version=_PACKAGE_VERSION "
            "to register_health_tools (not a literal string)."
        )
        assert 'version="0.1.0"' not in source, (
            "Hardcoded version=\"0.1.0\" was reintroduced in "
            "dhara/mcp/server_core.py; the version must be sourced from "
            "_PACKAGE_VERSION (importlib.metadata)."
        )

    def test_mcp_package_version_matches(self) -> None:
        """Assert ``dhara.mcp.__version__`` is sourced from importlib.metadata.

        Guards against the drift pattern where ``dhara/mcp/__init__.py`` had a
        hardcoded ``__version__ = "5.0.0"`` literal that diverged from
        ``pyproject.toml [project].version`` (currently 0.15.1).
        """
        expected = _read_pyproject_version(PYPROJECT_PATH)
        from dhara.mcp import __version__ as pkg_version

        assert _normalize_version(pkg_version) == expected, (
            f"dhara.mcp.__version__ {pkg_version!r} disagrees with "
            f"pyproject {expected!r}. Update dhara/mcp/__init__.py to source "
            f"__version__ from importlib.metadata.version('dhara')."
        )
        # Source check: dhara/mcp/__init__.py must not contain a hardcoded
        # version literal like ``__version__ = "5.0.0"`` — only the
        # importlib.metadata fallback ``"0.0.0+unknown"`` is allowed.
        from pathlib import Path
        init_path = Path("dhara/mcp/__init__.py")
        init_source = init_path.read_text(encoding="utf-8")
        assert "__version__ = " in init_source, (
            "dhara/mcp/__init__.py is missing a __version__ assignment."
        )
        # Reject the historical drift literals (5.0.0 was the stale value).
        assert '"5.0.0"' not in init_source, (
            'Hardcoded __version__ = "5.0.0" was reintroduced in '
            "dhara/mcp/__init__.py; use importlib.metadata.version('dhara')."
        )
