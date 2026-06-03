"""Comprehensive tests for dhara.cli module.

Tests cover the testable functions in the CLI module:
- _validate_path: Path validation with security checks
- _probe_storage_runtime: Storage accessibility probing
- _probe_backup_runtime: Backup catalog probing
- health_probe_handler: Runtime health snapshot generation
- stop_handler: Server shutdown logic
- start_handler: Server startup and error handling
- create_cli: CLI application creation
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

# ---------------------------------------------------------------------------
# Ensure the dhara package root is importable when running from tests/
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dhara.cli import (
    _probe_backup_runtime,
    _probe_storage_runtime,
    _validate_path,
    create_cli,
    health_probe_handler,
    start_handler,
    stop_handler,
)
from dhara.core.config import DharaSettings
from mcp_common.cli import RuntimeHealthSnapshot


# ===========================================================================
# Helpers
# ===========================================================================


def _make_mock_settings(**overrides) -> MagicMock:
    """Create a mock DharaSettings with all required attributes pre-set.

    Uses a plain MagicMock (no spec) so nested attribute assignment works
    naturally, then sets the specific attributes the CLI reads.
    """
    settings = MagicMock()
    settings.storage.path = Path("/data/dhara.dhara")
    settings.storage.read_only = False
    settings.backups.enabled = False
    settings.backups.directory = Path("./backups")
    settings.health_snapshot_path.return_value = Path("/tmp/health.json")
    settings.host = None
    settings.port = None
    for key, value in overrides.items():
        # Support dotted overrides like "storage.path"
        obj = settings
        parts = key.split(".")
        for part in parts[:-1]:
            obj = getattr(obj, part)
        setattr(obj, parts[-1], value)
    return settings


def _build_cli_app(settings: MagicMock):
    """Build a real Typer app while stubbing the CLI factory."""
    from dhara.cli import create_cli

    factory = MagicMock()
    app = typer.Typer()
    factory.create_app.return_value = app

    with (
        patch("dhara.core.config.DharaSettings.load", return_value=settings),
        patch("dhara.cli.MCPServerCLIFactory", return_value=factory),
    ):
        return create_cli()


# ===========================================================================
# _validate_path
# ===========================================================================


class TestValidatePath:
    """Tests for _validate_path(file_path)."""

    def test_returns_none_for_none_input(self):
        """None input should return None without error."""
        result = _validate_path(None)
        assert result is None

    def test_valid_path_returns_resolved_path(self):
        """A valid path string should return a resolved Path object."""
        result = _validate_path("/tmp/some_file.txt")
        assert result is not None
        assert isinstance(result, Path)
        assert str(result).startswith("/")

    def test_current_directory_path(self):
        """A relative path like 'file.txt' should resolve to an absolute path."""
        result = _validate_path("file.txt")
        assert result is not None
        assert isinstance(result, Path)
        assert result.is_absolute()

    def test_path_traversal_raises_exit(self):
        """Paths containing '..' should raise typer.Exit(1)."""
        with pytest.raises(typer.Exit):
            _validate_path("/tmp/../etc/passwd")

    def test_path_traversal_nested_raises_exit(self):
        """Paths with '..' in the middle should raise typer.Exit(1)."""
        with pytest.raises(typer.Exit):
            _validate_path("/tmp/foo/../../etc/shadow")

    def test_nonexistent_path_still_resolves(self):
        """A path to a non-existent file should still resolve without error."""
        result = _validate_path("/tmp/nonexistent_file_xyz_12345.txt")
        assert result is not None
        assert isinstance(result, Path)

    def test_dot_path_resolves(self):
        """A path of '.' should resolve to the current working directory."""
        result = _validate_path(".")
        assert result is not None
        assert result.is_absolute()

    def test_path_resolution_failure_raises_exit(self):
        """A resolution failure should surface as a CLI exit."""
        with patch("pathlib.Path.resolve", side_effect=OSError("bad path")):
            with pytest.raises(typer.Exit):
                _validate_path("broken")


# ===========================================================================
# _probe_storage_runtime
# ===========================================================================


class TestProbeStorageRuntime:
    """Tests for _probe_storage_runtime(settings).

    FileStorage and Connection are imported inside the function body, so
    we must patch them at their source modules.
    """

    def test_accessible_storage(self, tmp_path):
        """When storage is accessible, return positive status with root_keys."""
        # Use a real file path so storage_path.exists() returns True
        real_file = tmp_path / "test.dhara"
        real_file.write_text("dummy")
        settings = _make_mock_settings(**{"storage.path": real_file})

        mock_root = MagicMock()
        mock_root.keys.return_value = ["key1", "key2", "key3"]

        mock_connection = MagicMock()
        mock_connection.get_root.return_value = mock_root

        mock_storage_instance = MagicMock()
        mock_storage_instance.__enter__ = MagicMock(return_value=mock_storage_instance)
        mock_storage_instance.__exit__ = MagicMock(return_value=False)

        with (
            patch("dhara.storage.file.FileStorage", return_value=mock_storage_instance),
            patch("dhara.core.connection.Connection", return_value=mock_connection),
        ):
            result = _probe_storage_runtime(settings)

        assert result["storage_exists"] is True
        assert result["storage_readable"] is True
        assert result["storage_accessible"] is True
        assert result["root_keys"] == 3

    def test_storage_error(self, tmp_path):
        """When storage raises an exception, return error status."""
        # Use a real file path so storage_path.exists() returns True
        real_file = tmp_path / "test.dhara"
        real_file.write_text("dummy")
        settings = _make_mock_settings(**{"storage.path": real_file})

        with (
            patch(
                "dhara.storage.file.FileStorage",
                side_effect=OSError("Permission denied"),
            ),
            patch("dhara.core.connection.Connection"),
        ):
            result = _probe_storage_runtime(settings)

        assert result["storage_exists"] is True
        assert result["storage_readable"] is False
        assert result["storage_accessible"] is False
        assert "storage_error" in result
        assert "Permission denied" in result["storage_error"]

    def test_connection_error(self):
        """When Connection raises, return error status."""
        settings = _make_mock_settings()

        mock_storage_instance = MagicMock()
        mock_storage_instance.__enter__ = MagicMock(return_value=mock_storage_instance)
        mock_storage_instance.__exit__ = MagicMock(return_value=False)

        with (
            patch("dhara.storage.file.FileStorage", return_value=mock_storage_instance),
            patch(
                "dhara.core.connection.Connection",
                side_effect=RuntimeError("Corrupt database"),
            ),
        ):
            result = _probe_storage_runtime(settings)

        assert result["storage_accessible"] is False
        assert "Corrupt database" in result["storage_error"]

    def test_empty_root_keys(self):
        """When root has no keys, root_keys should be 0."""
        settings = _make_mock_settings()

        mock_root = MagicMock()
        mock_root.keys.return_value = []

        mock_connection = MagicMock()
        mock_connection.get_root.return_value = mock_root

        mock_storage_instance = MagicMock()
        mock_storage_instance.__enter__ = MagicMock(return_value=mock_storage_instance)
        mock_storage_instance.__exit__ = MagicMock(return_value=False)

        with (
            patch("dhara.storage.file.FileStorage", return_value=mock_storage_instance),
            patch("dhara.core.connection.Connection", return_value=mock_connection),
        ):
            result = _probe_storage_runtime(settings)

        assert result["root_keys"] == 0


# ===========================================================================
# _probe_backup_runtime
# ===========================================================================


class TestProbeBackupRuntime:
    """Tests for _probe_backup_runtime(settings)."""

    def test_backups_disabled(self):
        """When backups are disabled, return minimal config."""
        settings = _make_mock_settings(backups_enabled=False)

        result = _probe_backup_runtime(settings)

        assert result == {"backup_configured": False}

    def test_backups_enabled_no_catalog(self):
        """When backups enabled but no catalog file, return accessible status."""
        settings = _make_mock_settings(
            **{"backups.enabled": True, "backups.directory": Path("/tmp/dhara_test_backups_no_cat")}
        )

        with (
            patch("dhara.storage.file.FileStorage"),
            patch("dhara.core.connection.Connection"),
        ):
            result = _probe_backup_runtime(settings)

        assert result["backup_configured"] is True
        assert result["backup_catalog_exists"] is False
        assert result["backup_count"] == 0
        assert result["latest_backup_id"] is None
        assert result["latest_backup_at"] is None

    def test_backups_enabled_with_catalog(self, tmp_path):
        """When the catalog exists, read the backup payloads and latest entry."""
        catalog_dir = tmp_path / "backups"
        catalog_dir.mkdir()
        (catalog_dir / "backup_catalog.dhara").write_text("catalog")
        settings = _make_mock_settings(
            **{"backups.enabled": True, "backups.directory": catalog_dir}
        )

        mock_root = MagicMock()
        mock_root.get.return_value = {
            "b0": {"backup_id": "b0", "timestamp": 123},
            "b1": {"backup_id": "b1", "timestamp": "2024-01-01T10:00:00"},
            "b2": {"backup_id": "b2", "timestamp": "2024-01-02T10:00:00"},
        }

        mock_connection = MagicMock()
        mock_connection.get_root.return_value = mock_root

        mock_storage_instance = MagicMock()
        mock_storage_instance.__enter__ = MagicMock(return_value=mock_storage_instance)
        mock_storage_instance.__exit__ = MagicMock(return_value=False)

        with (
            patch("dhara.storage.file.FileStorage", return_value=mock_storage_instance),
            patch("dhara.core.connection.Connection", return_value=mock_connection),
        ):
            result = _probe_backup_runtime(settings)

        assert result["backup_catalog_exists"] is True
        assert result["backup_count"] == 3
        assert result["latest_backup_id"] == "b2"
        assert result["latest_backup_at"] == "2024-01-02T10:00:00"

    def test_backup_error(self):
        """When backup probing raises, return error status."""
        settings = _make_mock_settings(
            **{"backups.enabled": True, "backups.directory": Path("/tmp/dhara_test_backups_err")}
        )

        with (
            patch("dhara.storage.file.FileStorage"),
            patch("dhara.core.connection.Connection"),
            patch("pathlib.Path.mkdir", side_effect=OSError("Cannot create dir")),
        ):
            result = _probe_backup_runtime(settings)

        assert result["backup_configured"] is True
        assert result["backup_catalog_accessible"] is False
        assert "backup_error" in result


# ===========================================================================
# health_probe_handler
# ===========================================================================


class TestHealthProbeHandler:
    """Tests for health_probe_handler()."""

    @patch("dhara.cli._probe_backup_runtime")
    @patch("dhara.cli._probe_storage_runtime")
    @patch("dhara.cli.load_runtime_health")
    def test_returns_runtime_health_snapshot(
        self,
        mock_load_health,
        mock_probe_storage,
        mock_probe_backup,
    ):
        """health_probe_handler should return a RuntimeHealthSnapshot."""
        mock_settings = _make_mock_settings()

        mock_load_health.side_effect = FileNotFoundError
        mock_probe_storage.return_value = {
            "storage_exists": True,
            "storage_readable": True,
            "storage_accessible": True,
            "root_keys": 5,
        }
        mock_probe_backup.return_value = {"backup_configured": False}

        with patch("dhara.core.config.DharaSettings.load", return_value=mock_settings):
            result = health_probe_handler()

        assert isinstance(result, RuntimeHealthSnapshot)
        assert result.orchestrator_pid is None
        assert result.watchers_running is True
        assert result.remote_enabled is False
        assert result.lifecycle_state is not None
        assert result.activity_state is not None
        assert result.activity_state["current_status"] == "healthy"
        assert result.activity_state["ready"] is True

    @patch("dhara.cli._probe_backup_runtime")
    @patch("dhara.cli._probe_storage_runtime")
    @patch("dhara.cli.load_runtime_health")
    def test_unhealthy_when_storage_inaccessible(
        self,
        mock_load_health,
        mock_probe_storage,
        mock_probe_backup,
    ):
        """When storage is not accessible, health should be unhealthy."""
        mock_settings = _make_mock_settings()

        mock_load_health.side_effect = FileNotFoundError
        mock_probe_storage.return_value = {
            "storage_exists": True,
            "storage_readable": False,
            "storage_accessible": False,
            "storage_error": "Permission denied",
        }
        mock_probe_backup.return_value = {"backup_configured": False}

        with patch("dhara.core.config.DharaSettings.load", return_value=mock_settings):
            result = health_probe_handler()

        assert isinstance(result, RuntimeHealthSnapshot)
        assert result.watchers_running is False
        assert result.activity_state["current_status"] == "unhealthy"
        assert result.activity_state["ready"] is False
        assert result.activity_state["storage_status"] == "error"

    @patch("dhara.cli._probe_backup_runtime")
    @patch("dhara.cli._probe_storage_runtime")
    @patch("dhara.cli.load_runtime_health")
    def test_loads_existing_snapshot_for_uptime(
        self,
        mock_load_health,
        mock_probe_storage,
        mock_probe_backup,
    ):
        """When an existing snapshot exists, uptime should be calculated from it."""
        mock_settings = _make_mock_settings()

        existing = RuntimeHealthSnapshot(
            lifecycle_state={"started_at": time.time() - 100},
        )
        mock_load_health.return_value = existing
        mock_probe_storage.return_value = {
            "storage_exists": True,
            "storage_readable": True,
            "storage_accessible": True,
            "root_keys": 0,
        }
        mock_probe_backup.return_value = {"backup_configured": False}

        with patch("dhara.core.config.DharaSettings.load", return_value=mock_settings):
            result = health_probe_handler()

        assert result.lifecycle_state["uptime_seconds"] >= 99
        assert result.lifecycle_state["uptime_seconds"] < 200

    @patch("dhara.cli._probe_backup_runtime")
    @patch("dhara.cli._probe_storage_runtime")
    @patch("dhara.cli.load_runtime_health")
    def test_malformed_snapshot_uses_current_time(
        self,
        mock_load_health,
        mock_probe_storage,
        mock_probe_backup,
    ):
        """When existing snapshot is malformed, uptime defaults to 0."""
        mock_settings = _make_mock_settings()

        mock_load_health.side_effect = ValueError("Bad JSON")
        mock_probe_storage.return_value = {
            "storage_exists": True,
            "storage_readable": True,
            "storage_accessible": True,
            "root_keys": 0,
        }
        mock_probe_backup.return_value = {"backup_configured": False}

        with patch("dhara.core.config.DharaSettings.load", return_value=mock_settings):
            result = health_probe_handler()

        assert result.lifecycle_state["uptime_seconds"] < 2

    @patch("dhara.cli._probe_backup_runtime")
    @patch("dhara.cli._probe_storage_runtime")
    @patch("dhara.cli.load_runtime_health")
    def test_lifecycle_state_includes_storage_and_backup(
        self,
        mock_load_health,
        mock_probe_storage,
        mock_probe_backup,
    ):
        """Lifecycle state should merge storage and backup status."""
        mock_settings = _make_mock_settings(**{"storage.read_only": True})

        mock_load_health.side_effect = FileNotFoundError
        mock_probe_storage.return_value = {
            "storage_exists": True,
            "storage_readable": True,
            "storage_accessible": True,
            "root_keys": 3,
        }
        mock_probe_backup.return_value = {
            "backup_configured": True,
            "backup_count": 2,
        }

        with patch("dhara.core.config.DharaSettings.load", return_value=mock_settings):
            result = health_probe_handler()

        ls = result.lifecycle_state
        assert ls["storage_accessible"] is True
        assert ls["root_keys"] == 3
        assert ls["backup_configured"] is True
        assert ls["backup_count"] == 2
        assert ls["read_only"] is True


# ===========================================================================
# stop_handler
# ===========================================================================


class TestStopHandler:
    """Tests for stop_handler(_pid)."""

    @patch("dhara.cli.write_runtime_health")
    def test_with_no_server_instance(self, mock_write_health):
        """When _server_instance is None, should still write health and not crash."""
        import dhara.cli

        original_instance = dhara.cli._server_instance
        dhara.cli._server_instance = None

        try:
            mock_settings = _make_mock_settings()

            with patch("dhara.core.config.DharaSettings.load", return_value=mock_settings):
                stop_handler(12345)

            mock_write_health.assert_called_once()
            snapshot = mock_write_health.call_args[0][1]
            assert isinstance(snapshot, RuntimeHealthSnapshot)
            assert snapshot.activity_state["current_status"] == "stopped"
        finally:
            dhara.cli._server_instance = original_instance

    @patch("dhara.cli.write_runtime_health")
    def test_with_server_instance(self, mock_write_health):
        """When _server_instance exists, should call close and set to None."""
        import dhara.cli

        mock_server = MagicMock()
        original_instance = dhara.cli._server_instance
        dhara.cli._server_instance = mock_server

        try:
            mock_settings = _make_mock_settings()

            with patch("dhara.core.config.DharaSettings.load", return_value=mock_settings):
                stop_handler(12345)

            mock_server.close.assert_called_once()
            assert dhara.cli._server_instance is None
            mock_write_health.assert_called_once()
        finally:
            dhara.cli._server_instance = original_instance

    @patch("dhara.cli.write_runtime_health")
    def test_stop_snapshot_has_stopped_at(self, mock_write_health):
        """Stopped health snapshot should contain stopped_at timestamp."""
        import dhara.cli

        original_instance = dhara.cli._server_instance
        dhara.cli._server_instance = None

        try:
            mock_settings = _make_mock_settings()

            with patch("dhara.core.config.DharaSettings.load", return_value=mock_settings):
                before = time.time()
                stop_handler(12345)
                after = time.time()

            snapshot = mock_write_health.call_args[0][1]
            stopped_at = snapshot.lifecycle_state["stopped_at"]
            assert before <= stopped_at <= after
        finally:
            dhara.cli._server_instance = original_instance


# ===========================================================================
# start_handler
# ===========================================================================


class TestStartHandler:
    """Tests for start_handler()."""

    def test_error_loading_settings_exits(self):
        """When settings fail to load, should echo error and raise typer.Exit(1)."""
        with patch(
            "dhara.core.config.DharaSettings.load",
            side_effect=RuntimeError("Config file not found"),
        ):
            with pytest.raises(typer.Exit):
                start_handler()

    def test_settings_error_exits_with_code_1(self):
        """Exit code should be 1 when settings loading fails."""
        with patch(
            "dhara.core.config.DharaSettings.load",
            side_effect=RuntimeError("Bad config"),
        ):
            with pytest.raises(typer.Exit) as exc_info:
                start_handler()
            assert exc_info.value.exit_code == 1

    @patch("dhara.cli.write_runtime_health")
    def test_start_handler_runs_and_cleans_up(self, mock_write_health):
        """A normal server start should run, close, and write snapshots."""
        import dhara.cli

        mock_settings = _make_mock_settings(**{"server_name": "dhara"})
        mock_server = MagicMock()
        mock_server.adapter_registry.count.return_value = 4

        original_instance = dhara.cli._server_instance
        dhara.cli._server_instance = None

        try:
            with (
                patch("dhara.core.config.DharaSettings.load", return_value=mock_settings),
                patch("dhara.cli.DharaMCPServer", return_value=mock_server),
            ):
                start_handler()
        finally:
            dhara.cli._server_instance = original_instance

        mock_server.run.assert_called_once_with(host="127.0.0.1", port=8683)
        mock_server.close.assert_called_once()
        assert mock_write_health.call_count == 2

    @patch("dhara.cli.write_runtime_health")
    def test_start_handler_keyboard_interrupt(self, mock_write_health):
        """KeyboardInterrupt should still trigger the cleanup path."""
        import dhara.cli

        mock_settings = _make_mock_settings(**{"server_name": "dhara"})
        mock_server = MagicMock()
        mock_server.adapter_registry.count.return_value = 2
        mock_server.run.side_effect = KeyboardInterrupt

        original_instance = dhara.cli._server_instance
        dhara.cli._server_instance = None

        try:
            with (
                patch("dhara.core.config.DharaSettings.load", return_value=mock_settings),
                patch("dhara.cli.DharaMCPServer", return_value=mock_server),
            ):
                start_handler()
        finally:
            dhara.cli._server_instance = original_instance

        mock_server.close.assert_called_once()
        assert mock_write_health.call_count == 2

    @patch("dhara.cli.write_runtime_health")
    def test_start_handler_falsey_server_skips_close(self, mock_write_health):
        """A falsey server object should skip the close call in cleanup."""
        import dhara.cli

        mock_settings = _make_mock_settings(**{"server_name": "dhara"})
        mock_server = MagicMock()
        mock_server.adapter_registry.count.return_value = 1
        mock_server.__bool__.return_value = False

        original_instance = dhara.cli._server_instance
        dhara.cli._server_instance = None

        try:
            with (
                patch("dhara.core.config.DharaSettings.load", return_value=mock_settings),
                patch("dhara.cli.DharaMCPServer", return_value=mock_server),
            ):
                start_handler()
        finally:
            dhara.cli._server_instance = original_instance

        mock_server.run.assert_called_once_with(host="127.0.0.1", port=8683)
        mock_server.close.assert_not_called()
        assert mock_write_health.call_count == 2


# ===========================================================================
# create_cli
# ===========================================================================


class TestCreateCli:
    """Tests for create_cli()."""

    @patch("dhara.cli._create_admin_command")
    @patch("dhara.cli._create_storage_command")
    @patch("dhara.cli._create_adapters_command")
    @patch("dhara.cli._create_db_commands")
    @patch("dhara.cli.MCPServerCLIFactory")
    def test_creates_typer_app(
        self,
        mock_factory_cls,
        mock_create_db,
        mock_create_adapters,
        mock_create_storage,
        mock_create_admin,
    ):
        """create_cli should return a Typer app instance."""
        mock_settings = _make_mock_settings()

        mock_factory = MagicMock()
        mock_app = MagicMock(spec=typer.Typer)
        mock_factory.create_app.return_value = mock_app
        mock_factory_cls.return_value = mock_factory

        with patch("dhara.core.config.DharaSettings.load", return_value=mock_settings):
            result = create_cli()

        assert result is mock_app
        mock_factory_cls.assert_called_once()
        mock_factory.create_app.assert_called_once()
        mock_create_db.assert_called_once_with(mock_app)
        mock_create_adapters.assert_called_once()
        mock_create_storage.assert_called_once()
        mock_create_admin.assert_called_once()

    @patch("dhara.cli._create_admin_command")
    @patch("dhara.cli._create_storage_command")
    @patch("dhara.cli._create_adapters_command")
    @patch("dhara.cli._create_db_commands")
    @patch("dhara.cli.MCPServerCLIFactory")
    def test_factory_receives_correct_params(
        self,
        mock_factory_cls,
        mock_create_db,
        mock_create_adapters,
        mock_create_storage,
        mock_create_admin,
    ):
        """Factory should receive server_name, settings, handlers, and use_mcp_subcommand."""
        mock_settings = _make_mock_settings()

        mock_factory = MagicMock()
        mock_app = MagicMock(spec=typer.Typer)
        mock_factory.create_app.return_value = mock_app
        mock_factory_cls.return_value = mock_factory

        with patch("dhara.core.config.DharaSettings.load", return_value=mock_settings):
            create_cli()

        call_kwargs = mock_factory_cls.call_args[1]
        assert call_kwargs["server_name"] == "dhara"
        assert call_kwargs["settings"] is mock_settings
        assert call_kwargs["start_handler"] is start_handler
        assert call_kwargs["stop_handler"] is stop_handler
        assert call_kwargs["health_probe_handler"] is health_probe_handler
        assert call_kwargs["use_mcp_subcommand"] is True


class TestCreateCliRuntime:
    """Tests for the runtime behavior of the Typer app built by create_cli()."""

    def test_version_option_prints_version(self):
        """The global --version flag should print the CLI version."""
        settings = _make_mock_settings()
        app = _build_cli_app(settings)

        with patch("typer.echo") as mock_echo:
            with pytest.raises(typer.Exit):
                app.registered_callback.callback(version=True)

        mock_echo.assert_called_once_with("dhara version 0.6.1")

    def test_adapters_storage_and_admin_commands(self, tmp_path):
        """Root-level custom commands should execute through the Typer app."""
        settings = _make_mock_settings()
        settings.storage.path = tmp_path / "db.dhara"
        settings.storage.path.write_text("db")
        app = _build_cli_app(settings)
        runner = CliRunner()

        mock_storage = MagicMock()
        mock_storage.__enter__ = MagicMock(return_value=mock_storage)
        mock_storage.__exit__ = MagicMock(return_value=False)
        mock_connection = MagicMock()
        mock_root = MagicMock()
        mock_root.keys.return_value = ["a", "b"]
        mock_connection.get_root.return_value = mock_root
        mock_registry = MagicMock()
        mock_registry.list_adapters.return_value = [
            {
                "adapter_id": "adapter-1",
                "version": "1.0",
                "metadata": {"description": "demo"},
            }
        ]
        mock_shell = MagicMock()

        with (
            patch("dhara.storage.file.FileStorage", return_value=mock_storage),
            patch("dhara.core.connection.Connection", return_value=mock_connection),
            patch("dhara.mcp.adapter_tools.AdapterRegistry", return_value=mock_registry),
            patch("dhara.shell.DharaShell", return_value=mock_shell),
        ):
            adapters_result = runner.invoke(app, ["adapters"])
            storage_result = runner.invoke(app, ["storage"])
            admin_denied = runner.invoke(app, ["admin"])
            admin_allowed = runner.invoke(app, ["admin", "--confirm"])

        assert adapters_result.exit_code == 0
        assert "Found 1 adapters" in adapters_result.stdout
        assert storage_result.exit_code == 0
        assert "Storage Information" in storage_result.stdout
        assert admin_denied.exit_code == 1
        assert admin_allowed.exit_code == 0
        mock_shell.start.assert_called_once()

    def test_admin_storage_errors_return_nonzero(self, tmp_path):
        """Admin command should surface file access errors cleanly."""
        settings = _make_mock_settings()
        settings.storage.path = tmp_path / "missing.dhara"
        app = _build_cli_app(settings)
        runner = CliRunner()

        with (
            patch("dhara.storage.file.FileStorage", side_effect=FileNotFoundError),
            patch("dhara.core.connection.Connection"),
            patch("dhara.shell.DharaShell"),
        ):
            result = runner.invoke(app, ["admin", "--confirm"])

        assert result.exit_code == 1

        with (
            patch("dhara.storage.file.FileStorage", side_effect=PermissionError),
            patch("dhara.core.connection.Connection"),
            patch("dhara.shell.DharaShell"),
        ):
            result = runner.invoke(app, ["admin", "--confirm"])

        assert result.exit_code == 1

    def test_db_client_start_and_pack_commands(self, tmp_path):
        """Legacy database commands should route through the helper functions."""
        settings = _make_mock_settings()
        app = _build_cli_app(settings)
        runner = CliRunner()

        db_file = tmp_path / "client.dhara"
        db_file.write_text("db")
        pack_file = tmp_path / "pack.dhara"
        pack_file.write_text("db")

        mock_interactive_client = MagicMock()
        mock_get_storage = MagicMock(return_value=MagicMock())
        mock_start_dhara = MagicMock()
        mock_connection = MagicMock()
        mock_connection.pack = MagicMock()
        mock_client_storage = MagicMock(return_value=MagicMock())

        with (
            patch("dhara.__main__.interactive_client", mock_interactive_client),
            patch("dhara.__main__.get_storage", mock_get_storage),
            patch("dhara.__main__.start_dhara", mock_start_dhara),
            patch("dhara.__main__.Connection", return_value=mock_connection),
            patch("dhara.storage.client.ClientStorage", mock_client_storage),
        ):
            client_result = runner.invoke(app, ["db", "client", "--file", str(db_file)])
            client_host_result = runner.invoke(
                app, ["db", "client", "--host", "10.0.0.8", "--port", "2980"]
            )
            start_result = runner.invoke(app, ["db", "start", "--file", str(db_file)])
            pack_file_result = runner.invoke(app, ["db", "pack", "--file", str(pack_file)])
            pack_socket_result = runner.invoke(
                app, ["db", "pack", "--host", "10.0.0.8", "--port", "2980"]
            )
            pack_missing_result = runner.invoke(
                app, ["db", "pack", "--file", str(tmp_path / "missing.dhara")]
            )

        assert client_result.exit_code == 0
        assert client_host_result.exit_code == 0
        assert start_result.exit_code == 0
        assert pack_file_result.exit_code == 0
        assert pack_socket_result.exit_code == 0
        assert pack_missing_result.exit_code == 1
        mock_interactive_client.assert_any_call(
            file=str(db_file),
            address=None,
            cache_size=10000,
            readonly=False,
            repair=False,
            startup=None,
            storage_class=None,
            tls_config=None,
        )
        mock_interactive_client.assert_any_call(
            file=None,
            address=("10.0.0.8", 2980),
            cache_size=10000,
            readonly=False,
            repair=False,
            startup=None,
            storage_class=None,
            tls_config=None,
        )
        mock_get_storage.assert_any_call(str(db_file), readonly=False)
        mock_start_dhara.assert_called()
        mock_connection.pack.assert_called()

    def test_db_pack_connection_error_returns_exit(self, tmp_path):
        """Pack should exit when the connection pack step fails."""
        settings = _make_mock_settings()
        app = _build_cli_app(settings)
        runner = CliRunner()

        pack_file = tmp_path / "pack.dhara"
        pack_file.write_text("db")

        mock_connection = MagicMock()
        mock_connection.pack.side_effect = ConnectionError("offline")

        with (
            patch("dhara.__main__.get_storage", return_value=MagicMock()),
            patch("dhara.__main__.Connection", return_value=mock_connection),
            patch("dhara.storage.client.ClientStorage", return_value=MagicMock()),
        ):
            result = runner.invoke(app, ["db", "pack", "--file", str(pack_file)])

        assert result.exit_code == 1

    def test_main_invokes_created_app(self):
        """main() should construct the app and execute it."""
        from dhara.cli import main

        mock_app = MagicMock()
        with patch("dhara.cli.create_cli", return_value=mock_app):
            main()

        mock_app.assert_called_once_with()
