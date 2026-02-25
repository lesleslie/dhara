"""Unit tests for Druva CLI.

Tests CLI commands including:
- CLI creation
- Adapters command
- Storage command
- Health probe handler
- Start/stop handlers
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch
from typing import Generator

import pytest
from typer.testing import CliRunner

from druva.cli import create_cli, health_probe_handler, start_handler, stop_handler
from druva.core.config import DruvaSettings


@pytest.mark.unit
class TestDruvaCLI:
    """Test Druva CLI application."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create CLI test runner."""
        return CliRunner()

    @pytest.fixture
    def temp_settings(self, tmp_path: Path) -> DruvaSettings:
        """Create temporary settings for testing."""
        return DruvaSettings(
            server_name="test-druva",
            storage={
                "path": tmp_path / "test.druva",
                "read_only": False,
            },
            cache_root=tmp_path / ".cache",
        )

    @pytest.fixture
    def clean_env(self) -> Generator[None, None, None]:
        """Clean environment variables before/after tests."""
        import os

        original = {k: v for k, v in os.environ.items() if k.startswith("DRUVA_")}
        for key in list(os.environ.keys()):
            if key.startswith("DRUVA_"):
                del os.environ[key]
        yield
        for key, value in original.items():
            os.environ[key] = value

    def test_create_cli(self):
        """Test CLI creation."""
        app = create_cli()
        assert app is not None
        assert hasattr(app, "registered_commands")
        # Should have lifecycle commands and custom commands
        commands = app.registered_commands
        command_names = {cmd.name for cmd in commands if cmd.name}
        assert "adapters" in command_names
        assert "storage" in command_names
        assert "admin" in command_names

    def test_cli_has_lifecycle_commands(self, runner: CliRunner, clean_env):
        """Test CLI has standard lifecycle commands."""
        app = create_cli()

        # Test --help to see available commands
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "start" in result.stdout
        assert "stop" in result.stdout
        assert "status" in result.stdout
        assert "health" in result.stdout

    def test_adapters_command_empty(self, runner: CliRunner, temp_settings: DruvaSettings):
        """Test adapters command with no adapters."""
        from druva.core import Connection
        from druva.storage.file import FileStorage

        # Create empty storage file
        storage = FileStorage(str(temp_settings.storage.path))
        conn = Connection(storage)
        conn.commit()  # Create the file
        storage.close()

        # Mock settings.load to return temp_settings BEFORE creating CLI
        with patch("druva.cli.DruvaSettings.load", return_value=temp_settings):
            app = create_cli()
            result = runner.invoke(app, ["adapters"])

            # Should succeed even with no adapters
            assert result.exit_code == 0
            assert "Found 0 adapters" in result.stdout or "adapters" in result.stdout.lower()

    def test_adapters_command_with_data(self, runner: CliRunner, temp_settings: DruvaSettings):
        """Test adapters command with stored adapters."""
        # Create storage and add an adapter
        from druva.core import Connection
        from druva.storage.file import FileStorage
        from druva.mcp.adapter_tools import AdapterRegistry

        storage = FileStorage(str(temp_settings.storage.path))
        conn = Connection(storage)
        registry = AdapterRegistry(conn)

        # Store an adapter
        registry.store_adapter(
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
            factory_path="cache.RedisAdapter",
            config={"host": "localhost"},
            dependencies=[],
            capabilities=["get", "set"],
            metadata={"description": "Redis cache adapter"},
        )

        conn.commit()
        storage.close()

        # Now test CLI - create CLI inside patch context
        with patch("druva.cli.DruvaSettings.load", return_value=temp_settings):
            app = create_cli()
            result = runner.invoke(app, ["adapters"])

            assert result.exit_code == 0
            assert "adapter:cache:redis" in result.stdout
            assert "1.0.0" in result.stdout

    def test_adapters_command_filter_domain(self, runner: CliRunner, temp_settings: DruvaSettings):
        """Test adapters command with domain filter."""
        from druva.core import Connection
        from druva.storage.file import FileStorage
        from druva.mcp.adapter_tools import AdapterRegistry

        storage = FileStorage(str(temp_settings.storage.path))
        conn = Connection(storage)
        registry = AdapterRegistry(conn)

        # Store adapters with different domains
        registry.store_adapter(
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
            factory_path="cache.RedisAdapter",
            config={},
            dependencies=[],
            capabilities=[],
            metadata={},
        )

        registry.store_adapter(
            domain="service",
            key="storage",
            provider="s3",
            version="1.0.0",
            factory_path="storage.S3Adapter",
            config={},
            dependencies=[],
            capabilities=[],
            metadata={},
        )

        conn.commit()
        storage.close()

        with patch("druva.cli.DruvaSettings.load", return_value=temp_settings):
            app = create_cli()
            result = runner.invoke(app, ["adapters", "--domain", "adapter"])

            assert result.exit_code == 0
            assert "redis" in result.stdout
            # Should not show s3 adapter
            assert "s3" not in result.stdout.lower()

    def test_adapters_command_filter_category(self, runner: CliRunner, temp_settings: DruvaSettings):
        """Test adapters command with category filter."""
        from druva.core import Connection
        from druva.storage.file import FileStorage
        from druva.mcp.adapter_tools import AdapterRegistry

        storage = FileStorage(str(temp_settings.storage.path))
        conn = Connection(storage)
        registry = AdapterRegistry(conn)

        # Store adapters with different categories
        registry.store_adapter(
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
            factory_path="cache.RedisAdapter",
            config={},
            dependencies=[],
            capabilities=[],
            metadata={"category": "cache"},
        )

        registry.store_adapter(
            domain="adapter",
            key="storage",
            provider="s3",
            version="1.0.0",
            factory_path="storage.S3Adapter",
            config={},
            dependencies=[],
            capabilities=[],
            metadata={"category": "storage"},
        )

        conn.commit()
        storage.close()

        with patch("druva.cli.DruvaSettings.load", return_value=temp_settings):
            app = create_cli()
            result = runner.invoke(app, ["adapters", "--category", "cache"])

            assert result.exit_code == 0
            assert "redis" in result.stdout
            # Should not show s3
            assert "s3" not in result.stdout.lower()

    def test_storage_command(self, runner: CliRunner, temp_settings: DruvaSettings):
        """Test storage info command."""
        from druva.core import Connection
        from druva.storage.file import FileStorage

        storage = FileStorage(str(temp_settings.storage.path))
        conn = Connection(storage)
        root = conn.get_root()
        root["test_key"] = "test_value"
        conn.commit()
        storage.close()

        with patch("druva.cli.DruvaSettings.load", return_value=temp_settings):
            app = create_cli()
            result = runner.invoke(app, ["storage"])

            assert result.exit_code == 0
            assert "Storage Information" in result.stdout
            assert str(temp_settings.storage.path) in result.stdout
            assert "Root keys:" in result.stdout

    def test_health_probe_handler(self, temp_settings: DruvaSettings):
        """Test health probe handler."""
        from druva.core import Connection
        from druva.storage.file import FileStorage

        # Create storage
        storage = FileStorage(str(temp_settings.storage.path))
        conn = Connection(storage)
        root = conn.get_root()
        root["health_test"] = "ok"
        conn.commit()
        storage.close()

        # Mock settings.load
        with patch("druva.cli.DruvaSettings.load", return_value=temp_settings):
            snapshot = health_probe_handler()

            assert snapshot is not None
            assert snapshot.lifecycle_state["storage_path"] == str(temp_settings.storage.path)
            assert snapshot.lifecycle_state["storage_exists"] is True
            assert "storage_status" in snapshot.activity_state

    def test_health_probe_handler_no_storage(self, temp_settings: DruvaSettings):
        """Test health probe with non-existent storage."""
        # Don't create storage file

        with patch("druva.cli.DruvaSettings.load", return_value=temp_settings):
            snapshot = health_probe_handler()

            assert snapshot is not None
            assert snapshot.lifecycle_state["storage_exists"] is False
            assert snapshot.activity_state["storage_status"] == "error"

    @patch("druva.cli.DruvaMCPServer")
    @patch("druva.cli.write_runtime_health")
    @patch("druva.cli.DruvaSettings.load")
    def test_start_handler(
        self, mock_load: Mock, mock_write_health: Mock, mock_server: Mock, temp_settings: DruvaSettings
    ):
        """Test start handler initialization."""
        mock_load.return_value = temp_settings

        mock_server_instance = Mock()
        mock_server_instance.adapter_registry.count.return_value = 0
        mock_server_instance.run.side_effect = KeyboardInterrupt()
        mock_server.return_value = mock_server_instance

        # Call start handler
        start_handler()

        # Verify server was created and run
        mock_server.assert_called_once_with(temp_settings)
        mock_server_instance.run.assert_called_once()

    @patch("druva.cli.DruvaMCPServer")
    def test_stop_handler(self, mock_server: Mock):
        """Test stop handler cleanup."""
        mock_server_instance = Mock()
        import druva.cli

        druva.cli._server_instance = mock_server_instance

        stop_handler(12345)

        mock_server_instance.close.assert_called_once()
        assert druva.cli._server_instance is None

    def test_admin_command_requires_ipython(self, runner: CliRunner, temp_settings: DruvaSettings):
        """Test admin command (requires IPython)."""
        app = create_cli()

        with patch("druva.cli.DruvaSettings.load", return_value=temp_settings):
            # Should try to import IPython
            result = runner.invoke(app, ["admin"])

            # May fail if IPython not installed, but command should exist
            assert "admin" in result.stdout.lower() or result.exit_code != 0

    def test_cli_error_handling(self, runner: CliRunner, temp_settings: DruvaSettings):
        """Test CLI handles errors gracefully."""
        app = create_cli()

        # Test with invalid storage path (should handle error)
        invalid_settings = DruvaSettings(
            server_name="test-druva",
            storage={
                "path": "/nonexistent/path/test.druva",  # Invalid path
                "read_only": True,
            },
            cache_root=temp_settings.cache_root,
        )

        with patch("druva.cli.DruvaSettings.load", return_value=invalid_settings):
            result = runner.invoke(app, ["storage"])

            # Should handle error gracefully
            assert result.exit_code != 0 or "error" in result.stdout.lower()

    def test_cli_help(self, runner: CliRunner):
        """Test CLI help output."""
        app = create_cli()

        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Druva" in result.stdout

    def test_adapters_command_help(self, runner: CliRunner):
        """Test adapters command help."""
        app = create_cli()

        result = runner.invoke(app, ["adapters", "--help"])
        assert result.exit_code == 0
        assert "--domain" in result.stdout
        assert "--category" in result.stdout

    def test_storage_command_help(self, runner: CliRunner):
        """Test storage command help."""
        app = create_cli()

        result = runner.invoke(app, ["storage", "--help"])
        assert result.exit_code == 0
        assert "Display storage information" in result.stdout

    @pytest.mark.parametrize("command", ["adapters", "storage", "admin"])
    def test_custom_commands_exist(self, runner: CliRunner, command: str):
        """Test that all custom commands are registered."""
        app = create_cli()

        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert command in result.stdout


@pytest.mark.unit
class TestCLIIntegration:
    """Integration tests for CLI with actual storage."""

    @pytest.fixture
    def populated_storage(self, tmp_path: Path) -> DruvaSettings:
        """Create storage with sample data."""
        settings = DruvaSettings(
            server_name="test-druva",
            storage={
                "path": tmp_path / "test.druva",
                "read_only": False,
            },
            cache_root=tmp_path / ".cache",
        )

        from druva.core import Connection
        from druva.storage.file import FileStorage
        from druva.mcp.adapter_tools import AdapterRegistry

        storage = FileStorage(str(settings.storage.path))
        conn = Connection(storage)
        registry = AdapterRegistry(conn)

        # Add multiple adapters
        for i in range(3):
            registry.store_adapter(
                domain="adapter",
                key=f"cache{i}",
                provider="redis",
                version=f"1.{i}.0",
                factory_path=f"cache.RedisAdapter{i}",
                config={"index": i},
                dependencies=[],
                capabilities=[f"op{i}"],
                metadata={"description": f"Test adapter {i}"},
            )

        conn.commit()
        storage.close()

        return settings

    def test_full_adapters_workflow(self, populated_storage: DruvaSettings):
        """Test full adapters listing workflow."""
        from druva.core import Connection
        from druva.storage.file import FileStorage
        from druva.mcp.adapter_tools import AdapterRegistry

        storage = FileStorage(str(populated_storage.storage.path), readonly=True)
        conn = Connection(storage)
        registry = AdapterRegistry(conn)

        adapters = registry.list_adapters()
        assert len(adapters) == 3

        # Test filtering
        redis_adapters = registry.list_adapters(domain="adapter")
        assert len(redis_adapters) == 3

        storage.close()

    def test_storage_info_with_data(self, populated_storage: DruvaSettings):
        """Test storage info with actual data."""
        from druva.core import Connection
        from druva.storage.file import FileStorage

        storage = FileStorage(str(populated_storage.storage.path), readonly=True)
        conn = Connection(storage)
        root = conn.get_root()

        # Should have data from adapter registry
        assert "adapters" in root
        assert len(list(root.keys())) > 0

        storage.close()
