"""Tests for dhara/mcp/server_core.py -- DharaMCPServer core logic.

Covers server initialization, tool registration, health/ready probes,
backup probing, runtime status, the discover_tools meta-tool, and
server lifecycle (close, run).  External dependencies (FastMCP, storage,
auth) are mocked so these tests run without a running server or file I/O.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from dhara.core.config import (
    AuthenticationConfig,
    AuthenticationTokenConfig,
    BackupRuntimeConfig,
    DharaSettings,
    StorageConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides: Any) -> DharaSettings:
    """Build a DharaSettings with sensible test defaults."""
    defaults: dict[str, Any] = {
        "server_name": "test-dhara",
        "storage": StorageConfig(path=Path("/tmp/test_dhara_server.dhara")),
        "authentication": AuthenticationConfig(enabled=False),
        "backups": BackupRuntimeConfig(enabled=False),
    }
    defaults.update(overrides)
    return DharaSettings(**defaults)


# A shared set of patches used by every test that instantiates DharaMCPServer.
# Patches are applied top-down so that server_core imports the mock objects.
PATCHES = (
    # Mock Connection so no real storage is opened
    patch("dhara.mcp.server_core.Connection"),
    # Mock FileStorage so no real file is created
    patch("dhara.mcp.server_core.FileStorage"),
    # Mock FastMCP class
    patch("dhara.mcp.server_core.FastMCP"),
    # Auth builder returns None (auth disabled)
    patch("dhara.mcp.server_core.build_token_verifier", return_value=None),
    # Health tools registration
    patch("dhara.mcp.server_core.register_health_tools"),
    # Adapter tool impls (imported into server_core namespace)
    patch("dhara.mcp.server_core.get_adapter_health_impl"),
    patch("dhara.mcp.server_core.get_adapter_impl"),
    patch("dhara.mcp.server_core.list_adapter_versions_impl"),
    patch("dhara.mcp.server_core.list_adapters_impl"),
    patch("dhara.mcp.server_core.store_adapter_impl"),
    patch("dhara.mcp.server_core.validate_adapter_impl"),
)


def _apply_patches():
    """Start all patches and return the list of mock objects."""
    mocks = [p.start() for p in PATCHES]
    return mocks


def _stop_patches():
    for p in PATCHES:
        p.stop()


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure env vars do not leak between tests."""
    monkeypatch.delenv("DHARA_TOOL_PROFILE", raising=False)
    monkeypatch.delenv("DHARA_MODE", raising=False)


@pytest.fixture()
def mock_config(tmp_path: Path) -> DharaSettings:
    return _make_config(
        storage=StorageConfig(path=tmp_path / "test.dhara"),
        backups=BackupRuntimeConfig(
            enabled=False,
            directory=tmp_path / "backups",
        ),
    )


@pytest.fixture()
def mock_config_with_backups(tmp_path: Path) -> DharaSettings:
    return _make_config(
        storage=StorageConfig(path=tmp_path / "test.dhara"),
        backups=BackupRuntimeConfig(
            enabled=True,
            directory=tmp_path / "backups",
        ),
    )


@pytest.fixture()
def mock_config_auth_enabled(tmp_path: Path) -> DharaSettings:
    return _make_config(
        storage=StorageConfig(path=tmp_path / "test.dhara"),
        authentication=AuthenticationConfig(
            enabled=True,
            token=AuthenticationTokenConfig(
                tokens_file=tmp_path / "tokens.json",
            ),
        ),
    )


def _make_mock_fastmcp() -> MagicMock:
    """Return a MagicMock that behaves like a FastMCP server instance.

    The .tool() decorator returns a passthrough so that decorated functions
    are still callable in tests.
    """
    server = MagicMock(name="FastMCP")
    server.tool = MagicMock(side_effect=lambda **_kw: (lambda fn: fn))
    server.custom_route = MagicMock(
        side_effect=lambda _path, **_kw: (lambda fn: fn),
    )
    return server


def _make_capturing_fastmcp(target_name: str) -> tuple[MagicMock, dict]:
    """Return a mock FastMCP that captures a tool function by name.

    Returns (mock_server, {target_name: <function>}).
    """
    captured: dict[str, Any] = {}

    mock_server = MagicMock(name="FastMCP")

    def fake_tool(**_kw: Any) -> Any:
        def decorator(fn: Any) -> Any:
            if fn.__name__ == target_name:
                captured[target_name] = fn
            return fn
        return decorator

    mock_server.tool = fake_tool
    mock_server.custom_route = MagicMock(
        side_effect=lambda _path, **_kw: (lambda fn: fn),
    )
    return mock_server, captured


# ---------------------------------------------------------------------------
# Tests -- Server Initialization
# ---------------------------------------------------------------------------


class TestDharaMCPServerInit:
    """Test DharaMCPServer.__init__ configuration and wiring."""

    def test_creates_fastmcp_with_config_name(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            DharaMCPServer(mock_config)

            mock_fm_cls.assert_called_once()
            call_kwargs = mock_fm_cls.call_args[1]
            assert call_kwargs["name"] == "test-dhara"
        finally:
            _stop_patches()

    def test_auth_verifier_none_when_disabled(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            server = DharaMCPServer(mock_config)

            mock_build_auth.assert_called_once_with(
                enabled=False,
                tokens_file=mock_config.authentication.token.tokens_file,
                require_auth=mock_config.authentication.token.require_auth,
                default_role=mock_config.authentication.token.default_role,
                required_scopes=mock_config.authentication.required_scopes,
            )
            assert server.auth_verifier is None
        finally:
            _stop_patches()

    def test_auth_verifier_set_when_enabled(self, mock_config_auth_enabled: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            fake_verifier = MagicMock(name="DharaTokenVerifier")
            mock_build_auth.return_value = fake_verifier

            server = DharaMCPServer(mock_config_auth_enabled)

            assert server.auth_verifier is fake_verifier
            mock_build_auth.assert_called_once_with(
                enabled=True,
                tokens_file=mock_config_auth_enabled.authentication.token.tokens_file,
                require_auth=mock_config_auth_enabled.authentication.token.require_auth,
                default_role=mock_config_auth_enabled.authentication.token.default_role,
                required_scopes=mock_config_auth_enabled.authentication.required_scopes,
            )
        finally:
            _stop_patches()

    def test_creates_file_storage_with_config_path(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            DharaMCPServer(mock_config)

            mock_fs.assert_called_once_with(
                str(mock_config.storage.path.expanduser()),
                readonly=mock_config.storage.read_only,
            )
        finally:
            _stop_patches()

    def test_creates_connection_with_storage(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_storage = MagicMock()
            mock_fs.return_value = mock_storage

            DharaMCPServer(mock_config)

            mock_conn.assert_called_once_with(mock_storage)
        finally:
            _stop_patches()

    def test_registers_custom_routes(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_server_instance = _make_mock_fastmcp()
            mock_fm_cls.return_value = mock_server_instance

            DharaMCPServer(mock_config)

            route_paths = [call.args[0] for call in mock_server_instance.custom_route.call_args_list]
            assert "/health" in route_paths
            assert "/healthz" in route_paths
            assert "/ready" in route_paths
            assert "/readyz" in route_paths
            assert "/metrics" in route_paths
        finally:
            _stop_patches()

    def test_registers_health_tools(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            DharaMCPServer(mock_config)

            mock_reg_health.assert_called_once()
            call_kwargs = mock_reg_health.call_args[1]
            assert call_kwargs["service_name"] == "dhara"
            assert call_kwargs["version"] == "0.1.0"
            assert "dependencies" in call_kwargs
            deps = call_kwargs["dependencies"]
            assert "session_buddy" in deps
            assert "mahavishnu" in deps
            assert "akosha" in deps
        finally:
            _stop_patches()

    def test_adapter_registry_initialized(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            server = DharaMCPServer(mock_config)

            from dhara.mcp.adapter_tools import AdapterRegistry
            assert isinstance(server.adapter_registry, AdapterRegistry)
        finally:
            _stop_patches()

    def test_kv_store_initialized(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer
            from dhara.mcp.kv_timeseries import KVTimeSeriesStore

            server = DharaMCPServer(mock_config)

            assert isinstance(server.kv_store, KVTimeSeriesStore)
        finally:
            _stop_patches()

    def test_ecosystem_state_initialized(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer
            from dhara.mcp.ecosystem_state import EcosystemStateStore

            server = DharaMCPServer(mock_config)

            assert isinstance(server.ecosystem_state, EcosystemStateStore)
        finally:
            _stop_patches()

    def test_start_time_captured(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            before = time.time()
            server = DharaMCPServer(mock_config)
            after = time.time()

            assert before <= server._start_time <= after
        finally:
            _stop_patches()


# ---------------------------------------------------------------------------
# Tests -- Tool Registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Test _register_tools and tool profile gating."""

    def test_minimal_profile_registers_kv_tools_only(
        self,
        mock_config: DharaSettings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            monkeypatch.setenv("DHARA_TOOL_PROFILE", "minimal")

            tool_names_registered: list[str] = []

            mock_server_instance = MagicMock()

            def fake_tool(**kw):
                def decorator(fn):
                    tool_names_registered.append(fn.__name__)
                    return fn
                return decorator

            mock_server_instance.tool = fake_tool
            mock_server_instance.custom_route = MagicMock(
                side_effect=lambda _path, **_kw: (lambda fn: fn),
            )
            mock_fm_cls.return_value = mock_server_instance

            DharaMCPServer(mock_config)

            # discover_tools is always registered
            assert "discover_tools" in tool_names_registered
        finally:
            _stop_patches()

    def test_full_profile_registers_all_tools(
        self,
        mock_config: DharaSettings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            monkeypatch.setenv("DHARA_TOOL_PROFILE", "full")

            tool_names_registered: list[str] = []

            mock_server_instance = MagicMock()

            def fake_tool(**kw):
                def decorator(fn):
                    tool_names_registered.append(fn.__name__)
                    return fn
                return decorator

            mock_server_instance.tool = fake_tool
            mock_server_instance.custom_route = MagicMock(
                side_effect=lambda _path, **_kw: (lambda fn: fn),
            )
            mock_fm_cls.return_value = mock_server_instance

            DharaMCPServer(mock_config)

            expected_tools = [
                "store_adapter",
                "get_contract_info",
                "upsert_service",
                "get_service",
                "list_services",
                "record_event",
                "list_events",
                "put",
                "get",
                "record_time_series",
                "query_time_series",
                "aggregate_patterns",
                "get_adapter",
                "list_adapters",
                "list_adapter_versions",
                "validate_adapter",
                "get_adapter_health",
                "discover_tools",
            ]
            for name in expected_tools:
                assert name in tool_names_registered, (
                    f"{name} not registered in full profile"
                )
        finally:
            _stop_patches()

    def test_auth_decorator_returns_none_when_auth_disabled(
        self,
        mock_config: DharaSettings,
    ) -> None:
        """When authentication is disabled, the inner auth() helper returns None."""
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_config.authentication.enabled = False

            mock_server_instance = _make_mock_fastmcp()
            mock_fm_cls.return_value = mock_server_instance

            # Should not raise
            DharaMCPServer(mock_config)
        finally:
            _stop_patches()


# ---------------------------------------------------------------------------
# Tests -- Storage Probing
# ---------------------------------------------------------------------------


class TestProbeStorage:
    """Test _probe_storage for readiness reporting."""

    def test_probe_storage_accessible(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            server = DharaMCPServer(mock_config)
            result = server._probe_storage()

            assert result["accessible"] is True
            assert result["path"] == str(mock_config.storage.path.expanduser())
            assert result["read_only"] is mock_config.storage.read_only
            assert "root_keys" in result
        finally:
            _stop_patches()

    def test_probe_storage_handles_error(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            server = DharaMCPServer(mock_config)

            # Force get_root to raise
            server.connection.get_root = MagicMock(side_effect=RuntimeError("storage down"))

            result = server._probe_storage()

            assert result["accessible"] is False
            assert "storage down" in result["error"]
        finally:
            _stop_patches()


# ---------------------------------------------------------------------------
# Tests -- Backup Probing
# ---------------------------------------------------------------------------


class TestProbeBackups:
    """Test _probe_backups for backup catalog visibility."""

    def test_probe_backups_disabled(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            server = DharaMCPServer(mock_config)
            result = server._probe_backups()

            assert result == {"configured": False}
        finally:
            _stop_patches()

    def test_probe_backups_enabled_no_catalog(
        self,
        mock_config_with_backups: DharaSettings,
    ) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            server = DharaMCPServer(mock_config_with_backups)
            result = server._probe_backups()

            assert result["configured"] is True
            assert result["catalog_accessible"] is True
            assert result["catalog_exists"] is False
            assert result["total_backups"] == 0
            assert result["latest_backup_id"] is None
        finally:
            _stop_patches()

    def test_probe_backups_with_catalog(
        self,
        tmp_path: Path,
    ) -> None:
        """Test backup probing with an existing catalog containing data.

        This test uses real FileStorage/Connection for the catalog file,
        while the main server storage remains mocked.  We patch only at
        the server_core module level and let _probe_backups use the real
        classes for its own catalog access.
        """
        # Do NOT apply the global Connection/FileStorage patches.
        # Instead, only patch the external deps that block server init.
        patches_for_init = [
            patch("dhara.mcp.server_core.FastMCP"),
            patch("dhara.mcp.server_core.build_token_verifier", return_value=None),
            patch("dhara.mcp.server_core.register_health_tools"),
            patch("dhara.mcp.server_core.get_adapter_health_impl"),
            patch("dhara.mcp.server_core.get_adapter_impl"),
            patch("dhara.mcp.server_core.list_adapter_versions_impl"),
            patch("dhara.mcp.server_core.list_adapters_impl"),
            patch("dhara.mcp.server_core.store_adapter_impl"),
            patch("dhara.mcp.server_core.validate_adapter_impl"),
        ]
        started = [p.start() for p in patches_for_init]
        (
            mock_fm_cls, mock_build_auth, mock_reg_health, *_impls
        ) = started

        try:
            from dhara.core import Connection as RealConnection
            from dhara.storage import FileStorage as RealFileStorage
            from dhara.collections.dict import PersistentDict

            config = _make_config(
                storage=StorageConfig(path=tmp_path / "test.dhara"),
                backups=BackupRuntimeConfig(
                    enabled=True,
                    directory=tmp_path / "backups",
                ),
            )

            # Create a backup catalog with real storage before server init
            backup_dir = tmp_path / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            catalog_path = backup_dir / "backup_catalog.durus"

            real_storage = RealFileStorage(str(catalog_path))
            real_conn = RealConnection(real_storage)
            root = real_conn.get_root()
            backups = PersistentDict()
            backups["bk-001"] = PersistentDict(
                backup_id="bk-001",
                timestamp="2026-04-20T10:00:00",
            )
            backups["bk-002"] = PersistentDict(
                backup_id="bk-002",
                timestamp="2026-04-25T12:00:00",
            )
            root["backups"] = backups
            real_conn.commit()
            real_storage.close()

            from dhara.mcp.server_core import DharaMCPServer

            server = DharaMCPServer(config)

            result = server._probe_backups()

            assert result["configured"] is True
            assert result["catalog_exists"] is True
            assert result["total_backups"] == 2
            assert result["latest_backup_id"] == "bk-002"
            assert result["latest_backup_at"] == "2026-04-25T12:00:00"
        finally:
            for p in patches_for_init:
                p.stop()


# ---------------------------------------------------------------------------
# Tests -- Runtime Status
# ---------------------------------------------------------------------------


class TestRuntimeStatus:
    """Test _runtime_status aggregation."""

    def test_runtime_status_healthy(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            server = DharaMCPServer(mock_config)
            status = server._runtime_status()

            assert status["status"] == "ok"
            assert status["ready"] is True
            assert status["service"] == "dhara"
            assert status["version"] == "0.1.0"
            assert "uptime_seconds" in status
            assert isinstance(status["uptime_seconds"], float)
            assert status["uptime_seconds"] >= 0
            assert "storage" in status
            assert "backups" in status
            assert "authentication" in status
            assert status["authentication"]["enabled"] is False
            assert status["authentication"]["mode"] == "none"
        finally:
            _stop_patches()

    def test_runtime_status_storage_error(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            server = DharaMCPServer(mock_config)

            # Mock _probe_storage to simulate storage failure, and keep
            # adapter_registry.count working so _runtime_status completes.
            server._probe_storage = MagicMock(return_value={
                "path": str(mock_config.storage.path.expanduser()),
                "exists": True,
                "accessible": False,
                "read_only": False,
                "error": "broken",
            })

            status = server._runtime_status()

            assert status["status"] == "error"
            assert status["ready"] is False
            assert status["storage"]["accessible"] is False
        finally:
            _stop_patches()

    def test_runtime_status_with_auth_enabled(
        self,
        mock_config_auth_enabled: DharaSettings,
    ) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            fake_verifier = MagicMock(name="DharaTokenVerifier")
            mock_build_auth.return_value = fake_verifier

            server = DharaMCPServer(mock_config_auth_enabled)
            status = server._runtime_status()

            assert status["authentication"]["enabled"] is True
            assert status["authentication"]["mode"] == "token"
        finally:
            _stop_patches()


# ---------------------------------------------------------------------------
# Tests -- Health Endpoints
# ---------------------------------------------------------------------------


class TestHealthEndpoints:
    """Test the custom_route handler functions for health/readiness."""

    def _setup_with_captured_routes(
        self, mock_config: DharaSettings, mock_fm_cls: MagicMock,
    ) -> dict[str, Any]:
        """Set up mock FastMCP that captures route handlers, return them."""
        registered_routes: dict[str, Any] = {}

        mock_server_instance = MagicMock()

        def capture_route(path: str, **_kw: Any) -> Any:
            def decorator(fn: Any) -> Any:
                registered_routes[path] = fn
                return fn
            return decorator

        mock_server_instance.tool = MagicMock(side_effect=lambda **_kw: (lambda fn: fn))
        mock_server_instance.custom_route = capture_route
        mock_fm_cls.return_value = mock_server_instance

        from dhara.mcp.server_core import DharaMCPServer
        DharaMCPServer(mock_config)

        return registered_routes

    def test_healthz_returns_ok(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            routes = self._setup_with_captured_routes(mock_config, mock_fm_cls)

            result = asyncio.get_event_loop().run_until_complete(
                routes["/healthz"](MagicMock()),
            )
            assert result.body == b'{"status":"ok"}'
        finally:
            _stop_patches()

    def test_health_endpoint_returns_200_when_ready(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            routes = self._setup_with_captured_routes(mock_config, mock_fm_cls)

            result = asyncio.get_event_loop().run_until_complete(
                routes["/health"](MagicMock()),
            )
            assert result.status_code == 200
            body = json.loads(result.body)
            assert body["ready"] is True
        finally:
            _stop_patches()

    def test_health_endpoint_returns_503_when_not_ready(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            captured_routes: dict[str, Any] = {}

            mock_server_instance = MagicMock()

            def capture_route(path: str, **_kw: Any) -> Any:
                def decorator(fn: Any) -> Any:
                    captured_routes[path] = fn
                    return fn
                return decorator

            mock_server_instance.tool = MagicMock(side_effect=lambda **_kw: (lambda fn: fn))
            mock_server_instance.custom_route = capture_route
            mock_fm_cls.return_value = mock_server_instance

            from dhara.mcp.server_core import DharaMCPServer

            server = DharaMCPServer(mock_config)

            # Mock _runtime_status to return not-ready state.
            # This is simpler than breaking the connection, which also
            # breaks adapter_registry.count().
            server._runtime_status = MagicMock(return_value={
                "status": "error",
                "service": "dhara",
                "version": "0.1.0",
                "ready": False,
                "uptime_seconds": 10.0,
                "adapters": 0,
                "authentication": {"enabled": False, "mode": "none"},
                "storage": {"accessible": False, "error": "down"},
                "backups": {"configured": False},
            })

            result = asyncio.get_event_loop().run_until_complete(
                captured_routes["/health"](MagicMock()),
            )
            assert result.status_code == 503
            body = json.loads(result.body)
            assert body["ready"] is False
        finally:
            _stop_patches()

    def test_ready_endpoint_same_as_health(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            routes = self._setup_with_captured_routes(mock_config, mock_fm_cls)

            result = asyncio.get_event_loop().run_until_complete(
                routes["/ready"](MagicMock()),
            )
            assert result.status_code == 200
        finally:
            _stop_patches()

    def test_readyz_endpoint(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            routes = self._setup_with_captured_routes(mock_config, mock_fm_cls)

            result = asyncio.get_event_loop().run_until_complete(
                routes["/readyz"](MagicMock()),
            )
            body = json.loads(result.body)
            assert body["ready"] is True
        finally:
            _stop_patches()

    def test_metrics_endpoint_returns_string(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            # get_server_metrics is imported lazily inside the handler from
            # dhara.monitoring.metrics, so patch it there.
            with patch(
                "dhara.monitoring.metrics.get_server_metrics",
                return_value="# HELP test\n# TYPE test counter\ntest 1\n",
            ):
                routes = self._setup_with_captured_routes(mock_config, mock_fm_cls)

                result = asyncio.get_event_loop().run_until_complete(
                    routes["/metrics"](MagicMock()),
                )
                assert result.status_code == 200
                assert b"test 1" in result.body
        finally:
            _stop_patches()

    def test_metrics_endpoint_json_fallback(self, mock_config: DharaSettings) -> None:
        """When get_server_metrics returns a dict, /metrics returns JSON."""
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            with patch(
                "dhara.monitoring.metrics.get_server_metrics",
                return_value={"enabled": False},
            ):
                routes = self._setup_with_captured_routes(mock_config, mock_fm_cls)

                result = asyncio.get_event_loop().run_until_complete(
                    routes["/metrics"](MagicMock()),
                )
                body = json.loads(result.body)
                assert body["enabled"] is False
        finally:
            _stop_patches()


# ---------------------------------------------------------------------------
# Tests -- Discover Tools Meta-Tool
# ---------------------------------------------------------------------------


class TestDiscoverTools:
    """Test the discover_tools meta-tool function."""

    def test_discover_tools_no_query(
        self,
        mock_config: DharaSettings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            monkeypatch.setenv("DHARA_TOOL_PROFILE", "full")

            mock_server, captured = _make_capturing_fastmcp("discover_tools")
            mock_fm_cls.return_value = mock_server

            DharaMCPServer(mock_config)

            discover_fn = captured["discover_tools"]
            result = asyncio.get_event_loop().run_until_complete(discover_fn(query=None))

            assert result["status"] == "success"
            assert result["query"] is None
            assert result["loaded_count"] > 0
        finally:
            _stop_patches()

    def test_discover_tools_with_query_filter(
        self,
        mock_config: DharaSettings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            monkeypatch.setenv("DHARA_TOOL_PROFILE", "full")

            mock_server, captured = _make_capturing_fastmcp("discover_tools")
            mock_fm_cls.return_value = mock_server

            DharaMCPServer(mock_config)

            discover_fn = captured["discover_tools"]
            result = asyncio.get_event_loop().run_until_complete(
                discover_fn(query="adapter"),
            )

            assert result["status"] == "success"
            assert result["query"] == "adapter"
            assert "store_adapter" in result["loaded_tools"]
        finally:
            _stop_patches()

    def test_discover_tools_minimal_profile(
        self,
        mock_config: DharaSettings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            monkeypatch.setenv("DHARA_TOOL_PROFILE", "minimal")

            mock_server, captured = _make_capturing_fastmcp("discover_tools")
            mock_fm_cls.return_value = mock_server

            DharaMCPServer(mock_config)

            discover_fn = captured["discover_tools"]
            result = asyncio.get_event_loop().run_until_complete(
                discover_fn(query=None),
            )

            assert result["profile"] == "minimal"
            assert "put" in result["loaded_tools"]
            assert "store_adapter" not in result["loaded_tools"]
            assert "upsert_service" not in result["loaded_tools"]
        finally:
            _stop_patches()

    def test_discover_tools_hint_in_response(
        self,
        mock_config: DharaSettings,
    ) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_server, captured = _make_capturing_fastmcp("discover_tools")
            mock_fm_cls.return_value = mock_server

            DharaMCPServer(mock_config)

            discover_fn = captured["discover_tools"]
            result = asyncio.get_event_loop().run_until_complete(
                discover_fn(query=None),
            )

            assert "hint" in result
            assert "DHARA_TOOL_PROFILE" in result["hint"]
        finally:
            _stop_patches()


# ---------------------------------------------------------------------------
# Tests -- Get Contract Info Tool
# ---------------------------------------------------------------------------


class TestGetContractInfo:
    """Test the get_contract_info tool."""

    def test_contract_info_no_auth(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_server, captured = _make_capturing_fastmcp("get_contract_info")
            mock_fm_cls.return_value = mock_server

            server = DharaMCPServer(mock_config)

            contract_fn = captured["get_contract_info"]
            result = asyncio.get_event_loop().run_until_complete(contract_fn())

            assert result["ok"] is True
            assert result["server"]["name"] == "test-dhara"
            assert result["server"]["transport"] == "FastMCP HTTP"
            assert result["authentication"]["runtime_mode"] == "none"
            assert result["authentication"]["canonical_fastmcp_wired"] is False
            assert "adapter_registry" in result["tool_groups"]
            assert "kv_time_series" in result["tool_groups"]
            assert "ecosystem_state" in result["tool_groups"]
            assert result["schema_versions"]["adapter_registry"] == 1
        finally:
            _stop_patches()

    def test_contract_info_http_endpoints(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_server, captured = _make_capturing_fastmcp("get_contract_info")
            mock_fm_cls.return_value = mock_server

            DharaMCPServer(mock_config)

            contract_fn = captured["get_contract_info"]
            result = asyncio.get_event_loop().run_until_complete(contract_fn())

            endpoints = result["server"]["http_endpoints"]
            assert "/health" in endpoints
            assert "/metrics" in endpoints
        finally:
            _stop_patches()

    def test_contract_info_deprecated_surfaces(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_server, captured = _make_capturing_fastmcp("get_contract_info")
            mock_fm_cls.return_value = mock_server

            DharaMCPServer(mock_config)

            contract_fn = captured["get_contract_info"]
            result = asyncio.get_event_loop().run_until_complete(contract_fn())

            assert "deprecated_surfaces" in result
            assert "dhara.mcp.server" in result["deprecated_surfaces"]["module"]
        finally:
            _stop_patches()


# ---------------------------------------------------------------------------
# Tests -- Server Lifecycle
# ---------------------------------------------------------------------------


class TestServerLifecycle:
    """Test server close and run methods."""

    def test_close_calls_storage_close(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_storage = MagicMock()
            mock_fs.return_value = mock_storage

            server = DharaMCPServer(mock_config)
            server.close()

            mock_storage.close.assert_called_once()
        finally:
            _stop_patches()

    def test_close_safe_when_no_storage(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            server = DharaMCPServer(mock_config)
            # Delete storage attribute to simulate init failure
            del server.storage

            # Should not raise
            server.close()
        finally:
            _stop_patches()

    def test_run_invokes_asyncio_run(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_server_instance = _make_mock_fastmcp()
            mock_fm_cls.return_value = mock_server_instance

            server = DharaMCPServer(mock_config)

            with patch("asyncio.run") as mock_asyncio_run:
                server.run(host="0.0.0.0", port=9999)

                mock_asyncio_run.assert_called_once()
                mock_server_instance.run_http_async.assert_called_once_with(
                    host="0.0.0.0",
                    port=9999,
                )
        finally:
            _stop_patches()

    def test_run_default_host_port(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_server_instance = _make_mock_fastmcp()
            mock_fm_cls.return_value = mock_server_instance

            server = DharaMCPServer(mock_config)

            with patch("asyncio.run"):
                server.run()

                mock_server_instance.run_http_async.assert_called_once_with(
                    host="127.0.0.1",
                    port=8683,
                )
        finally:
            _stop_patches()


# ---------------------------------------------------------------------------
# Tests -- Backward-Compatible Alias
# ---------------------------------------------------------------------------


class TestDruvaAlias:
    """Test the DruvaMCPServer backward-compatible alias."""

    def test_alias_exists(self) -> None:
        from dhara.mcp.server_core import DruvaMCPServer, DharaMCPServer

        assert DruvaMCPServer is DharaMCPServer


# ---------------------------------------------------------------------------
# Tests -- Tool Function Dispatch (Integration-style)
# ---------------------------------------------------------------------------


class TestToolFunctionDispatch:
    """Test that registered tool functions correctly delegate to impl functions."""

    def test_store_adapter_calls_impl(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health,
            mock_health_impl, mock_get_impl, mock_list_versions_impl,
            mock_list_impl, mock_store_impl, mock_validate_impl,
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_store_impl.return_value = {"success": True, "adapter_id": "a:b:c"}

            mock_server, captured = _make_capturing_fastmcp("store_adapter")
            mock_fm_cls.return_value = mock_server

            DharaMCPServer(mock_config)

            store_fn = captured["store_adapter"]
            result = asyncio.get_event_loop().run_until_complete(
                store_fn(
                    domain="adapter",
                    key="cache",
                    provider="redis",
                    version="1.0.0",
                    factory_path="my.module.Factory",
                )
            )

            mock_store_impl.assert_called_once()
            assert result["success"] is True
        finally:
            _stop_patches()

    def test_store_adapter_passes_defaults(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health,
            mock_health_impl, mock_get_impl, mock_list_versions_impl,
            mock_list_impl, mock_store_impl, mock_validate_impl,
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_store_impl.return_value = {"success": True, "adapter_id": "a:b:c"}

            mock_server, captured = _make_capturing_fastmcp("store_adapter")
            mock_fm_cls.return_value = mock_server

            DharaMCPServer(mock_config)

            store_fn = captured["store_adapter"]
            asyncio.get_event_loop().run_until_complete(
                store_fn(
                    domain="adapter",
                    key="cache",
                    provider="redis",
                    version="1.0.0",
                    factory_path="my.module.Factory",
                    # config, dependencies, capabilities, metadata omitted
                )
            )

            call_kwargs = mock_store_impl.call_args[1]
            assert call_kwargs["config"] == {}
            assert call_kwargs["dependencies"] == []
            assert call_kwargs["capabilities"] == []
            assert call_kwargs["metadata"] == {}
        finally:
            _stop_patches()

    def test_get_adapter_calls_impl(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health,
            mock_health_impl, mock_get_impl, mock_list_versions_impl,
            mock_list_impl, mock_store_impl, mock_validate_impl,
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_get_impl.return_value = {"success": True, "adapter": {"domain": "adapter"}}

            mock_server, captured = _make_capturing_fastmcp("get_adapter")
            mock_fm_cls.return_value = mock_server

            DharaMCPServer(mock_config)

            get_fn = captured["get_adapter"]
            result = asyncio.get_event_loop().run_until_complete(
                get_fn(domain="adapter", key="cache", provider="redis"),
            )

            mock_get_impl.assert_called_once()
            assert result["success"] is True
        finally:
            _stop_patches()

    def test_list_adapters_calls_impl(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health,
            mock_health_impl, mock_get_impl, mock_list_versions_impl,
            mock_list_impl, mock_store_impl, mock_validate_impl,
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_list_impl.return_value = {"success": True, "count": 0, "adapters": []}

            mock_server, captured = _make_capturing_fastmcp("list_adapters")
            mock_fm_cls.return_value = mock_server

            DharaMCPServer(mock_config)

            list_fn = captured["list_adapters"]
            result = asyncio.get_event_loop().run_until_complete(
                list_fn(domain="adapter"),
            )

            mock_list_impl.assert_called_once()
            assert result["count"] == 0
        finally:
            _stop_patches()

    def test_list_adapter_versions_calls_impl(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health,
            mock_health_impl, mock_get_impl, mock_list_versions_impl,
            mock_list_impl, mock_store_impl, mock_validate_impl,
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_list_versions_impl.return_value = {
                "success": True, "count": 1, "versions": [{"version": "1.0.0"}],
            }

            mock_server, captured = _make_capturing_fastmcp("list_adapter_versions")
            mock_fm_cls.return_value = mock_server

            DharaMCPServer(mock_config)

            versions_fn = captured["list_adapter_versions"]
            result = asyncio.get_event_loop().run_until_complete(
                versions_fn(domain="adapter", key="cache", provider="redis"),
            )

            mock_list_versions_impl.assert_called_once()
            assert result["count"] == 1
        finally:
            _stop_patches()

    def test_validate_adapter_calls_impl(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health,
            mock_health_impl, mock_get_impl, mock_list_versions_impl,
            mock_list_impl, mock_store_impl, mock_validate_impl,
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_validate_impl.return_value = {
                "success": True, "validation": {"valid": True, "errors": [], "warnings": []},
            }

            mock_server, captured = _make_capturing_fastmcp("validate_adapter")
            mock_fm_cls.return_value = mock_server

            DharaMCPServer(mock_config)

            validate_fn = captured["validate_adapter"]
            result = asyncio.get_event_loop().run_until_complete(
                validate_fn(domain="adapter", key="cache", provider="redis"),
            )

            mock_validate_impl.assert_called_once()
            assert result["validation"]["valid"] is True
        finally:
            _stop_patches()

    def test_get_adapter_health_calls_impl(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health,
            mock_health_impl, mock_get_impl, mock_list_versions_impl,
            mock_list_impl, mock_store_impl, mock_validate_impl,
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_health_impl.return_value = {
                "success": True, "health": {"healthy": True},
            }

            mock_server, captured = _make_capturing_fastmcp("get_adapter_health")
            mock_fm_cls.return_value = mock_server

            DharaMCPServer(mock_config)

            health_fn = captured["get_adapter_health"]
            result = asyncio.get_event_loop().run_until_complete(
                health_fn(domain="adapter", key="cache", provider="redis"),
            )

            mock_health_impl.assert_called_once()
            assert result["health"]["healthy"] is True
        finally:
            _stop_patches()

    def test_put_and_get_kv_tools(self, mock_config: DharaSettings) -> None:
        """Test that put/get tool functions delegate to the kv_store."""
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            captured_fns: dict[str, Any] = {}

            mock_server_instance = MagicMock()

            def fake_tool(**kw):
                def decorator(fn):
                    captured_fns[fn.__name__] = fn
                    return fn
                return decorator

            mock_server_instance.tool = fake_tool
            mock_server_instance.custom_route = MagicMock(
                side_effect=lambda _path, **_kw: (lambda fn: fn),
            )
            mock_fm_cls.return_value = mock_server_instance

            server = DharaMCPServer(mock_config)

            # Mock kv_store to avoid real storage interactions
            server.kv_store.put = MagicMock(return_value={"ok": True, "key": "test"})
            server.kv_store.get = MagicMock(return_value={"ok": True, "key": "test", "value": 42})

            put_fn = captured_fns["put"]
            get_fn = captured_fns["get"]

            put_result = asyncio.get_event_loop().run_until_complete(
                put_fn(key="test", value=42),
            )
            assert put_result["ok"] is True
            server.kv_store.put.assert_called_once_with(key="test", value=42, ttl=None)

            get_result = asyncio.get_event_loop().run_until_complete(
                get_fn(key="test"),
            )
            assert get_result["value"] == 42
            server.kv_store.get.assert_called_once_with(key="test")
        finally:
            _stop_patches()

    def test_put_with_ttl(self, mock_config: DharaSettings) -> None:
        """Test put with TTL parameter."""
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            captured_fns: dict[str, Any] = {}

            mock_server_instance = MagicMock()

            def fake_tool(**kw):
                def decorator(fn):
                    captured_fns[fn.__name__] = fn
                    return fn
                return decorator

            mock_server_instance.tool = fake_tool
            mock_server_instance.custom_route = MagicMock(
                side_effect=lambda _path, **_kw: (lambda fn: fn),
            )
            mock_fm_cls.return_value = mock_server_instance

            server = DharaMCPServer(mock_config)
            server.kv_store.put = MagicMock(return_value={"ok": True, "key": "ttl-test"})

            put_fn = captured_fns["put"]
            result = asyncio.get_event_loop().run_until_complete(
                put_fn(key="ttl-test", value="data", ttl=3600),
            )

            server.kv_store.put.assert_called_once_with(key="ttl-test", value="data", ttl=3600)
            assert result["ok"] is True
        finally:
            _stop_patches()

    def test_record_and_query_time_series(self, mock_config: DharaSettings) -> None:
        """Test time-series record/query tool delegation."""
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            captured_fns: dict[str, Any] = {}

            mock_server_instance = MagicMock()

            def fake_tool(**kw):
                def decorator(fn):
                    captured_fns[fn.__name__] = fn
                    return fn
                return decorator

            mock_server_instance.tool = fake_tool
            mock_server_instance.custom_route = MagicMock(
                side_effect=lambda _path, **_kw: (lambda fn: fn),
            )
            mock_fm_cls.return_value = mock_server_instance

            server = DharaMCPServer(mock_config)
            server.kv_store.record_time_series = MagicMock(
                return_value={"ok": True, "metric_type": "cpu", "entity_id": "host1"},
            )
            server.kv_store.query_time_series = MagicMock(
                return_value=[{"ts": "2026-01-01", "value": 42}],
            )
            server.kv_store.aggregate_patterns = MagicMock(
                return_value=[{"pattern": "error", "count": 5}],
            )

            record_fn = captured_fns["record_time_series"]
            query_fn = captured_fns["query_time_series"]
            agg_fn = captured_fns["aggregate_patterns"]

            rec_result = asyncio.get_event_loop().run_until_complete(
                record_fn(metric_type="cpu", entity_id="host1", record={"value": 42}),
            )
            assert rec_result["ok"] is True

            query_result = asyncio.get_event_loop().run_until_complete(
                query_fn(metric_type="cpu", entity_id="host1"),
            )
            assert len(query_result) == 1

            agg_result = asyncio.get_event_loop().run_until_complete(
                agg_fn(start_date="2026-01-01"),
            )
            assert agg_result[0]["pattern"] == "error"
        finally:
            _stop_patches()

    def test_ecosystem_state_tools(self, mock_config: DharaSettings) -> None:
        """Test ecosystem state tool delegation."""
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            captured_fns: dict[str, Any] = {}

            mock_server_instance = MagicMock()

            def fake_tool(**kw):
                def decorator(fn):
                    captured_fns[fn.__name__] = fn
                    return fn
                return decorator

            mock_server_instance.tool = fake_tool
            mock_server_instance.custom_route = MagicMock(
                side_effect=lambda _path, **_kw: (lambda fn: fn),
            )
            mock_fm_cls.return_value = mock_server_instance

            server = DharaMCPServer(mock_config)

            server.ecosystem_state.upsert_service = MagicMock(
                return_value={"service_id": "svc-1", "service_type": "orchestrator"},
            )
            server.ecosystem_state.get_service = MagicMock(
                return_value={"service_id": "svc-1", "service_type": "orchestrator"},
            )
            server.ecosystem_state.list_services = MagicMock(
                return_value=[{"service_id": "svc-1", "service_type": "orchestrator"}],
            )
            server.ecosystem_state.record_event = MagicMock(
                return_value={"event_type": "deploy", "source_service": "mahavishnu"},
            )
            server.ecosystem_state.list_events = MagicMock(
                return_value=[{"event_type": "deploy"}],
            )

            upsert_result = asyncio.get_event_loop().run_until_complete(
                captured_fns["upsert_service"](
                    service_id="svc-1", service_type="orchestrator",
                ),
            )
            assert upsert_result["service_id"] == "svc-1"

            get_result = asyncio.get_event_loop().run_until_complete(
                captured_fns["get_service"](service_id="svc-1"),
            )
            assert get_result["ok"] is True

            list_result = asyncio.get_event_loop().run_until_complete(
                captured_fns["list_services"](),
            )
            assert list_result["count"] == 1

            event_result = asyncio.get_event_loop().run_until_complete(
                captured_fns["record_event"](
                    event_type="deploy", source_service="mahavishnu",
                ),
            )
            assert event_result["event_type"] == "deploy"

            events_result = asyncio.get_event_loop().run_until_complete(
                captured_fns["list_events"](),
            )
            assert events_result["count"] == 1
        finally:
            _stop_patches()

    def test_upsert_service_passes_all_params(self, mock_config: DharaSettings) -> None:
        """Test that upsert_service forwards all parameters."""
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            captured_fns: dict[str, Any] = {}

            mock_server_instance = MagicMock()

            def fake_tool(**kw):
                def decorator(fn):
                    captured_fns[fn.__name__] = fn
                    return fn
                return decorator

            mock_server_instance.tool = fake_tool
            mock_server_instance.custom_route = MagicMock(
                side_effect=lambda _path, **_kw: (lambda fn: fn),
            )
            mock_fm_cls.return_value = mock_server_instance

            server = DharaMCPServer(mock_config)
            server.ecosystem_state.upsert_service = MagicMock(
                return_value={"service_id": "svc-1"},
            )

            upsert_fn = captured_fns["upsert_service"]
            asyncio.get_event_loop().run_until_complete(
                upsert_fn(
                    service_id="svc-1",
                    service_type="orchestrator",
                    capabilities=["sweep", "schedule"],
                    metadata={"version": "0.6.0"},
                    status="healthy",
                    lease_expires_at="2026-12-31T23:59:59",
                    heartbeat_at="2026-04-26T10:00:00",
                ),
            )

            server.ecosystem_state.upsert_service.assert_called_once_with(
                service_id="svc-1",
                service_type="orchestrator",
                capabilities=["sweep", "schedule"],
                metadata={"version": "0.6.0"},
                status="healthy",
                lease_expires_at="2026-12-31T23:59:59",
                heartbeat_at="2026-04-26T10:00:00",
            )
        finally:
            _stop_patches()
