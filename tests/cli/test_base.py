"""Tests for Dhara's BodaiCLIBase adoption (Phase 3 Task 4.2).

Mirrors the cascade-invariant contract tests from
``oneiric/tests/cli/test_base.py`` (20 tests) and adapts them to verify:

1. The subclass ``DharaCLI`` extends ``BodaiCLIBase``.
2. ``version`` command emits the component name + installed version.
3. ``doctor`` / ``health`` global commands return repo-specific data
   (NOT ``ExitCode.UNAVAILABLE`` from the base-class
   ``NotImplementedError`` path).
4. ``--json`` is a global flag that wraps both ``version`` and ``doctor``.
5. ``--version`` / ``-V`` are accepted with a ``DeprecationWarning``.
6. The subclass overrides ``_doctor_checks`` and ``_health_probe`` with
   real probes (settings, storage path, backup catalog, runtime health
   snapshot).
"""
from __future__ import annotations

import json
import warnings

import pytest
import typer
from oneiric.cli.base import BodaiCLIBase, ExitCode
from typer.testing import CliRunner

from dhara.cli import DharaCLI, create_cli

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    """Provide a Typer CLI test runner."""
    return CliRunner()


@pytest.fixture
def dhara_app() -> DharaCLI:
    """Build a real DharaCLI; costs an async probe or two but yields the
    full surface including MCP lifecycle + db + adapters + storage + admin.

    Tests that need to control the settings-loading surface build their own
    ``DharaCLI`` directly with monkeypatched settings.
    """
    return create_cli()


# ---------------------------------------------------------------------------
# Construction + metadata
# ---------------------------------------------------------------------------


def test_dhara_cli_extends_bodai_cli_base(dhara_app: DharaCLI) -> None:
    """``DharaCLI`` must be a ``BodaiCLIBase`` instance."""
    assert isinstance(dhara_app, BodaiCLIBase)
    assert isinstance(dhara_app, typer.Typer)


def test_dhara_cli_sets_component_name(dhara_app: DharaCLI) -> None:
    assert dhara_app.component_name == "dhara"


def test_dhara_cli_sets_component_version(dhara_app: DharaCLI) -> None:
    """Version string comes from importlib.metadata('dhara')."""
    assert isinstance(dhara_app.component_version, str)
    assert dhara_app.component_version != "(not installed)"


def test_create_cli_returns_dhara_cli_instance() -> None:
    """``create_cli`` is the canonical factory entry point."""
    app = create_cli()
    assert isinstance(app, DharaCLI)


# ---------------------------------------------------------------------------
# Global commands — version / doctor / health
# ---------------------------------------------------------------------------


def test_version_command_emits_component_name_and_version(
    runner: CliRunner, dhara_app: DharaCLI
) -> None:
    """``dhara version`` exits 0 and emits ``dhara: <version>``."""
    result = runner.invoke(dhara_app, ["version"])
    assert result.exit_code == ExitCode.SUCCESS
    assert "dhara" in result.output
    assert dhara_app.component_version in result.output


def test_doctor_returns_real_checks_not_unavailable(
    runner: CliRunner, dhara_app: DharaCLI
) -> None:
    """``dhara doctor`` must return real checks (ExitCode.SUCCESS), NOT
    ``ExitCode.UNAVAILABLE`` (which is the base class' default when
    ``_doctor_checks`` raises ``NotImplementedError``)."""
    result = runner.invoke(dhara_app, ["doctor"])
    assert result.exit_code == ExitCode.SUCCESS
    # Base-class unavailable message must NOT appear.
    assert "not yet implemented" not in result.output
    # At least one of the canonical Dhara check names must surface.
    for check_name in ("config_load", "storage_path", "backup_catalog"):
        assert check_name in result.output, (
            f"doctor output missing {check_name!r}: {result.output!r}"
        )


def test_health_returns_real_snapshot_not_unavailable(
    runner: CliRunner, dhara_app: DharaCLI
) -> None:
    """``dhara health`` must return the Dhara runtime snapshot shape,
    NOT ``ExitCode.UNAVAILABLE``."""
    result = runner.invoke(dhara_app, ["health"])
    assert result.exit_code == ExitCode.SUCCESS
    assert "not yet implemented" not in result.output
    # Snapshot keys we control in DharaCLI._health_probe.
    assert "component" in result.output
    assert "dhara" in result.output


# ---------------------------------------------------------------------------
# Global flags
# ---------------------------------------------------------------------------


def test_json_flag_wraps_version(runner: CliRunner, dhara_app: DharaCLI) -> None:
    """``--json version`` is accepted and still exits SUCCESS."""
    result = runner.invoke(dhara_app, ["--json", "version"])
    assert result.exit_code == ExitCode.SUCCESS
    assert "dhara" in result.output


def test_json_flag_emits_json_for_doctor(
    runner: CliRunner, dhara_app: DharaCLI
) -> None:
    """``dhara --json doctor`` must emit a JSON object with a ``checks``
    key (round-2 F-δ cascade invariant)."""
    result = runner.invoke(dhara_app, ["--json", "doctor"])
    assert result.exit_code == ExitCode.SUCCESS
    assert '"checks"' in result.output
    # Round-trip parse to confirm it's actually JSON.
    payload = json.loads(result.output)
    assert "checks" in payload
    assert isinstance(payload["checks"], dict)
    assert "config_load" in payload["checks"]
    assert "status" in payload["checks"]["config_load"]


def test_json_flag_emits_json_for_health(
    runner: CliRunner, dhara_app: DharaCLI
) -> None:
    """``dhara --json health`` must emit a JSON object whose keys match
    the DharaCLI._health_probe shape."""
    result = runner.invoke(dhara_app, ["--json", "health"])
    assert result.exit_code == ExitCode.SUCCESS
    payload = json.loads(result.output)
    assert payload.get("component") == "dhara"
    assert "settings_loaded" in payload
    assert "storage_accessible" in payload
    assert "current_status" in payload


def test_version_long_flag_emits_deprecation(
    runner: CliRunner, dhara_app: DharaCLI
) -> None:
    """``--version`` flag emits ``DeprecationWarning`` + version, exits 0."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = runner.invoke(dhara_app, ["--version"])

    assert result.exit_code == ExitCode.SUCCESS
    assert "dhara" in result.output
    assert any(
        issubclass(w.category, DeprecationWarning) for w in caught
    ), "Expected DeprecationWarning for --version flag"


def test_version_short_flag_emits_deprecation(
    runner: CliRunner, dhara_app: DharaCLI
) -> None:
    """``-V`` short flag works identically."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = runner.invoke(dhara_app, ["-V"])

    assert result.exit_code == ExitCode.SUCCESS
    assert "dhara" in result.output
    assert any(
        issubclass(w.category, DeprecationWarning) for w in caught
    ), "Expected DeprecationWarning for -V flag"


# ---------------------------------------------------------------------------
# Subclass override hooks (introspection)
# ---------------------------------------------------------------------------


def test_dhara_cli_overrides_doctor_checks(dhara_app: DharaCLI) -> None:
    """``_doctor_checks`` is overridden in the DharaCLI subclass — its
    base-class implementation raises ``NotImplementedError`` which would
    cascade through to ``ExitCode.UNAVAILABLE`` (round-2 F-γ invariant)."""
    assert DharaCLI._doctor_checks is not BodaiCLIBase._doctor_checks


def test_dhara_cli_overrides_health_probe(dhara_app: DharaCLI) -> None:
    """``_health_probe`` is overridden in the DharaCLI subclass."""
    assert DharaCLI._health_probe is not BodaiCLIBase._health_probe


def test_dhara_cli_doctor_checks_returns_at_least_one_check(
    dhara_app: DharaCLI,
) -> None:
    """Contract: overrides return at least 1 check (plan §G3)."""
    checks = dhara_app._doctor_checks()
    assert isinstance(checks, dict)
    assert checks
    for info in checks.values():
        assert isinstance(info, dict)
        assert "status" in info
        assert "detail" in info
        assert info["status"] in {"ok", "degraded", "failed"}


def test_dhara_cli_health_probe_returns_snapshot(
    dhara_app: DharaCLI,
) -> None:
    """Contract: the health override returns a dict with the documented
    Dhara keys (``component``, ``version``, ``current_status``, etc.)."""
    snap = dhara_app._health_probe()
    assert isinstance(snap, dict)
    assert snap.get("component") == "dhara"
    assert "version" in snap
    assert "settings_loaded" in snap
    assert "storage_accessible" in snap
    assert "current_status" in snap


# ---------------------------------------------------------------------------
# Cascade-fix design invariants (mirrored from oneiric/tests/cli/test_base.py)
# ---------------------------------------------------------------------------


def test_no_extra_callback_registered(dhara_app: DharaCLI) -> None:
    """Round-1 F-α cascade invariant: exactly ONE callback is registered
    — the unified root callback from BodaiCLIBase. ``DharaCLI`` must NOT
    redeclare ``@self.callback`` (the original ``@app.callback(...)`` for
    ``--version`` was removed when adopting the base class)."""
    callback = getattr(dhara_app, "registered_callback", None)
    assert callback is not None, "Unified callback should be registered"
    assert callback.invoke_without_command is True


def test_pre_callback_default_is_noop(runner: CliRunner) -> None:
    """The default ``_pre_callback`` is a no-op. We override it via the
    subclass by NOT touching the hook, so invoking ``version`` should
    still work — which proves the subclass didn't accidentally break the
    unified callback."""
    app = create_cli()
    result = runner.invoke(app, ["version"])
    assert result.exit_code == ExitCode.SUCCESS


def test_resolve_json_output_helper_inherited(dhara_app: DharaCLI) -> None:
    """Round-2 F-δ cascade invariant: ``_resolve_json_output(ctx)`` helper
    must be reachable through subclass instances."""
    assert hasattr(dhara_app, "_resolve_json_output")
    assert callable(dhara_app._resolve_json_output)


# ---------------------------------------------------------------------------
# End-to-end: mcp subcommand + legacy db + custom commands still wired
# ---------------------------------------------------------------------------


def test_legacy_commands_still_wired(runner: CliRunner, dhara_app: DharaCLI) -> None:
    """Adopting ``BodaiCLIBase`` must NOT regress the existing commands:
    the ``mcp``, ``db``, ``adapters``, ``storage``, ``admin`` subcommands
    surfaced by ``dhara --help`` are the plan's G4 outcome."""
    result = runner.invoke(dhara_app, ["--help"])
    assert result.exit_code == ExitCode.SUCCESS
    for cmd in ("mcp", "db", "adapters", "storage", "admin", "version", "doctor", "health"):
        assert cmd in result.output, (
            f"dhara --help missing {cmd!r}: {result.output!r}"
        )
