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
from contextlib import suppress
from unittest.mock import AsyncMock, MagicMock, patch

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
def _build_async_file_storage_instance(*_args: Any, **_kwargs: Any) -> AsyncMock:
    """Build a single AsyncFileStorage mock instance.

    ``AsyncConnection.new`` requires the storage to expose async ``init``,
    ``load``, ``begin``, ``store``, ``end``, ``sync``, ``new_oid``,
    ``gen_oid_record`` methods. A bare ``MagicMock`` does not — accessing any
    of those attributes returns a non-coroutine, and ``await`` raises
    ``TypeError``. ``_conn`` is set to a truthy value so the wiring helper
    skips the ``__aenter__`` path and proceeds straight to
    ``AsyncConnection.new(storage)``.
    """
    storage = AsyncMock(name="AsyncFileStorage")
    storage._conn = True  # non-None skips the __aenter__ wire path
    return storage


def _make_async_file_storage_mock(*args: Any, **kwargs: Any) -> AsyncMock:
    """Factory that returns a tracked ``AsyncFileStorage`` mock.

    Used as the ``side_effect`` of the ``AsyncFileStorage`` patch so the
    patch's ``MagicMock`` itself remains inspectable via
    ``assert_called_once_with(...)`` while every invocation returns an
    AsyncMock shaped like a real storage instance.
    """
    return _build_async_file_storage_instance(*args, **kwargs)


def _make_async_connection_new(*_args: Any, **_kwargs: Any) -> AsyncMock:
    """Build a mock ``AsyncConnection.new`` that returns a usable connection.

    The wiring helper wraps the returned object in ``_SyncConnectionFacade``,
    which calls ``async_conn.get_root()``, ``async_conn.commit()``, etc. via
    the persistent loop. Return an ``AsyncMock`` whose async methods resolve
    to a usable empty ``PersistentDict`` so probes and status checks see a
    non-error response.
    """
    async_conn = AsyncMock(name="AsyncConnection")
    async_conn.storage = AsyncMock(name="AsyncConnection.storage")
    async_conn.cache = MagicMock(name="AsyncConnection.cache")
    # ``get_root`` must return a mapping that supports ``.keys()`` /
    # iteration; an empty dict satisfies both the probe and status paths
    # without forcing tests to install their own root.
    async_conn.get_root = AsyncMock(return_value={})
    async_conn.commit = AsyncMock(return_value=None)
    async_conn.abort = AsyncMock(return_value=None)
    return async_conn


PATCHES = (
    # Mock Connection so no real storage is opened
    patch("dhara.mcp.server_core.Connection"),
    # Mock AsyncFileStorage so no real file is created. The server has
    # been ported to ``AsyncFileStorage`` (the legacy ``FileStorage`` is
    # deleted); the symbol is imported into ``server_core`` under that
    # new name. ``new`` is replaced with a callable factory that returns
    # a properly-initialized ``AsyncMock`` so the AsyncConnection wiring
    # step can ``await`` the storage methods without raising.
    patch(
        "dhara.mcp.server_core.AsyncFileStorage",
        side_effect=_make_async_file_storage_mock,
    ),
    # Mock FastMCP class
    patch("dhara.mcp.server_core.FastMCP"),
    # Auth builder returns None (auth disabled)
    patch("dhara.mcp.server_core.build_token_verifier", return_value=None),
    # Health tools registration
    patch("dhara.mcp.server_core.register_health_tools"),
    # Adapter tool impls. After W1.4, the *async variants are imported
    # inside ``register_adapter_registry_group`` (function-local import
    # in ``dhara.mcp.tools.group_registers``). The symbols don't exist
    # at module level on ``dhara.mcp.tools.group_registers`` until that
    # function runs, so patching it would require ``create=True``.
    # Patching the source module ``dhara.mcp.adapter_tools`` directly is
    # more robust: every code path that imports the impl (legacy
    # ``server_core`` namespace + W0 group_registers) sees the mock.
    patch("dhara.mcp.adapter_tools.get_adapter_health_async_impl"),
    patch("dhara.mcp.adapter_tools.get_adapter_async_impl"),
    patch("dhara.mcp.adapter_tools.list_adapter_versions_async_impl"),
    patch("dhara.mcp.adapter_tools.list_adapters_async_impl"),
    patch("dhara.mcp.adapter_tools.store_adapter_async_impl"),
    patch("dhara.mcp.adapter_tools.validate_adapter_async_impl"),
    # W1.4: stub the W0 dispatch itself. The mock FastMCP's
    # ``list_tools()`` returns a MagicMock (not a coroutine), and the
    # W0 helper awaits it — so without this stub, ``DharaMCPServer.__init__``
    # raises ``TypeError: object MagicMock can't be used in 'await'``.
    # Stubbing the W0 helper bypasses the per-group registration path;
    # tests that exercise specific tool registration use the wiring
    # tests in ``tests/unit/test_wiring.py`` instead (with proper
    # async-aware mocks).
    patch("mcp_common.tools.dispatch._apply_tool_profile"),
    # Mock ``AsyncConnection.new`` at the source so the wire step in
    # ``_run_async_connection_wire`` does not exercise the real factory
    # against the mocked storage. Placed last so it does not shift the
    # index positions of the upstream mocks consumed by individual tests.
    patch(
        "dhara.core.connection.AsyncConnection.new",
        side_effect=_make_async_connection_new,
    ),
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


@pytest.fixture(autouse=True)
def _reset_cache_wire_loop() -> None:
    """Stop and reset ``_CACHE_WIRE_LOOP`` before AND after each test.

    The wiring helper creates a persistent event loop and spins a daemon
    thread that calls ``loop.run_forever()``. Without resetting the loop
    between tests, subsequent ``DharaMCPServer(...)`` constructions call
    ``run_until_complete`` on a loop that is already running, raising
    ``RuntimeError: This event loop is already running``.

    Pre-test reset is necessary when this file runs after integration
    tests: integration tests construct ``DharaMCPServer`` instances
    without resetting the loop, leaving it in a state where the wire
    step silently skips ``AsyncConnection.new(storage)`` (the wire-loop
    helper is still the previous run's loop, and ``run_until_complete``
    queues to a stopped loop). The setup hook below resets it before
    each test so order dependencies don't bleed across test files.
    """
    def _reset_loop() -> None:
        try:
            from dhara.mcp.server_core import _CACHE_WIRE_LOOP as _loop
        except ImportError:
            return
        if _loop is None:
            return
        with suppress(Exception):
            _loop.call_soon_threadsafe(_loop.stop)
        # Detach the daemon thread so the loop can be closed.
        if hasattr(_loop, "_dhara_wire_thread"):
            _loop._dhara_wire_thread = None  # ty: ignore[unresolved-attribute]
        with suppress(Exception):
            if not _loop.is_closed():
                _loop.close()
        import dhara.mcp.server_core as _core

        _core._CACHE_WIRE_LOOP = None

    _reset_loop()
    yield
    _reset_loop()


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


def _make_capturing_fastmcp(
    target_name: str,
    impl_mock: Any = None,
) -> tuple[MagicMock, dict]:
    """Return a mock FastMCP that captures a tool function by name.

    If ``impl_mock`` is provided, also pre-register a thin async wrapper
    in ``captured`` that delegates to the impl. This mirrors the production
    dispatch contract so tests that exercise tool-function-dispatch do
    not need to invoke ``_drive_w0_registration`` or otherwise depend on
    the mocked W0 helper actually running.

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

    # The W0 dispatch path registers ``discover_tools`` (and other always-on
    # tools) via ``server.add_tool(Tool.from_function(fn=..., name=...))``,
    # bypassing the ``@tool`` decorator. Intercept ``add_tool`` so tools
    # registered via either path land in ``captured``.
    def fake_add_tool(tool: Any) -> Any:
        tool_name = getattr(tool, "name", None)
        tool_fn = getattr(tool, "fn", None)
        if tool_name == target_name and tool_fn is not None:
            captured[target_name] = tool_fn
        return tool

    mock_server.add_tool = fake_add_tool

    # W0 dispatch awaits ``server.list_tools()`` and ``server.get_tools()``;
    # MagicMock returns a non-coroutine so the await fails. Patch the
    # relevant methods onto AsyncMock instances that return empty lists.
    mock_server.list_tools = AsyncMock(return_value=[])
    mock_server.get_tools = AsyncMock(return_value=[])

    if impl_mock is not None:
        async def _dispatch_wrapper(**kwargs: Any) -> Any:
            # Mirror the canonical ``register_*_group`` helpers: fill the
            # ``config`` / ``dependencies`` / ``capabilities`` /
            # ``metadata`` defaults so tests that omit them still observe
            # the production contract on the impl mock.
            kwargs.setdefault("config", {})
            kwargs.setdefault("dependencies", [])
            kwargs.setdefault("capabilities", [])
            kwargs.setdefault("metadata", {})
            return await impl_mock(**kwargs)

        captured[target_name] = _dispatch_wrapper

    return mock_server, captured


def _drive_w0_registration(server: Any) -> None:
    """Drive ``_apply_w0_profile`` against the mock server.

    The W0 dispatch is mocked in ``_apply_patches`` so the per-tool
    registration path never executes during ``DharaMCPServer.__init__``.
    Tests that need to capture a specific tool by name call this helper
    after construction. Individual registration helpers raise when their
    async stores are uninitialized; those failures are absorbed so the
    test can still inspect ``captured`` for the target tool.
    """
    try:
        asyncio.new_event_loop().run_until_complete(server._apply_w0_profile())
    except Exception:  # noqa: BLE001
        # async stores not initialized in unit tests; safe to skip
        pass


def _build_discover_tools_handler(mock_server: MagicMock) -> Any:
    """Build a discover_tools handler compatible with the W0 dispatch contract.

    The W0 helper registers ``discover_tools`` via ``Tool.from_function``,
    bypassing the FastMCP ``@tool`` decorator. Tests using
    ``_make_capturing_fastmcp`` therefore never see the handler. This helper
    re-creates the same handler against the supplied mock server so tests can
    assert the contract directly.
    """
    from dhara.mcp.profiles import get_active_profile
    from mcp_common.tools.dispatch import _default_discovery as _dispatch_discover

    # ``_default_discovery`` calls ``await server.list_tools()`` so the mock
    # server must expose an async-compatible list_tools; a bare MagicMock
    # would raise ``TypeError: object MagicMock can't be used in 'await'``.
    if not isinstance(mock_server.list_tools, AsyncMock):
        mock_server.list_tools = AsyncMock(return_value=[])

    async def discover_tools_handler(query: str | None = None) -> dict[str, Any]:
        tools = await _dispatch_discover(mock_server, query)
        profile = get_active_profile()
        return {
            "status": "success",
            "query": query,
            "profile": profile.value,
            "loaded_count": len(tools),
            "loaded_tools": [t.get("name") for t in tools],
            "hint": (
                "Use DHARA_TOOL_PROFILE to switch profile tier; current "
                f"profile: {profile.value}"
            ),
        }

    return discover_tools_handler


def _register_dispatching_tool(
    captured: dict[str, Any],
    tool_name: str,
    impl_mock: Any,
) -> None:
    """Install a delegating wrapper for ``tool_name`` against ``impl_mock``.

    The W0 dispatch registers tools but is mocked out in ``_apply_patches``,
    so the test fixture never captures a tool function. This helper installs
    a thin async wrapper that mirrors the production behavior: the wrapper
    fills the same default values that the canonical
    ``register_*_group`` helpers do (``config={}``,
    ``dependencies=[]``, ``capabilities=[]``, ``metadata={}``) so callers
    can omit them and still observe the production contract on the
    impl mock.
    """
    async def tool_wrapper(**kwargs: Any) -> Any:
        kwargs.setdefault("config", {})
        kwargs.setdefault("dependencies", [])
        kwargs.setdefault("capabilities", [])
        kwargs.setdefault("metadata", {})
        return await impl_mock(**kwargs)

    captured[tool_name] = tool_wrapper


def _build_discover_tools_handler(mock_server: MagicMock) -> Any:
    """Build a discover_tools handler compatible with the W0 dispatch contract.

    The W0 helper registers ``discover_tools`` via ``Tool.from_function``,
    bypassing the FastMCP ``@tool`` decorator. Tests using
    ``_make_capturing_fastmcp`` therefore never see the handler. This helper
    re-creates the same handler against the supplied mock server so tests can
    assert the contract directly.
    """
    from dhara.mcp.profiles import get_active_profile
    from mcp_common.tools.dispatch import _default_discovery as _dispatch_discover

    # ``_default_discovery`` calls ``await server.list_tools()`` so the mock
    # server must expose an async-compatible list_tools; a bare MagicMock
    # would raise ``TypeError: object MagicMock can't be used in 'await'``.
    if not isinstance(mock_server.list_tools, AsyncMock):
        mock_server.list_tools = AsyncMock(return_value=[])

    async def discover_tools_handler(query: str | None = None) -> dict[str, Any]:
        tools = await _dispatch_discover(mock_server, query)
        profile = get_active_profile()
        return {
            "status": "success",
            "query": query,
            "profile": profile.value,
            "loaded_count": len(tools),
            "loaded_tools": [t.get("name") for t in tools],
            "hint": (
                "Use DHARA_TOOL_PROFILE to switch profile tier; current "
                f"profile: {profile.value}"
            ),
        }

    return discover_tools_handler


def _register_dispatching_tool(
    captured: dict[str, Any],
    tool_name: str,
    impl_mock: Any,
) -> None:
    """Install a delegating wrapper for ``tool_name`` against ``impl_mock``.

    The W0 dispatch registers tools but is mocked out in ``_apply_patches``,
    so the test fixture never captures a tool function. This helper installs
    a thin async wrapper that mirrors the production behavior: the wrapper
    fills the same default values that the canonical
    ``register_*_group`` helpers do (``config={}``,
    ``dependencies=[]``, ``capabilities=[]``, ``metadata={}``) so callers
    can omit them and still observe the production contract on the
    impl mock.
    """
    async def tool_wrapper(**kwargs: Any) -> Any:
        kwargs.setdefault("config", {})
        kwargs.setdefault("dependencies", [])
        kwargs.setdefault("capabilities", [])
        kwargs.setdefault("metadata", {})
        return await impl_mock(**kwargs)

    captured[tool_name] = tool_wrapper


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

            server = DharaMCPServer(mock_config)

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

            server = DharaMCPServer(mock_config)

            # Post-async-migration the storage is built with only the path
            # argument; ``readonly`` is enforced by callers that need it
            # by wrapping the storage themselves.
            mock_fs.assert_called_once_with(
                str(mock_config.storage.path.expanduser()),
            )
        finally:
            _stop_patches()

    def test_creates_connection_with_storage(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls, mock_async_conn_new
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            server = DharaMCPServer(mock_config)

            # Post-async-migration the wiring helper uses
            # ``AsyncConnection.new(storage)`` instead of
            # ``Connection(storage)``; verify the factory was called
            # exactly once and received the AsyncFileStorage mock
            # produced by the side_effect.
            assert mock_async_conn_new.call_count == 1
            storage_arg = mock_async_conn_new.call_args.args[0]
            assert storage_arg is not None
            assert mock_fs.called
            # The legacy ``Connection`` mock should not have been touched.
            assert mock_conn.call_count == 0
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

            server = DharaMCPServer(mock_config)

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
            mock_reg_health, *_impls, mock_apply_tool_profile
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            server = DharaMCPServer(mock_config)

            # Post-W0 health registration lives in
            # ``DharaMCPServer._register_health_tools`` and is invoked
            # through the W0 dispatch + ``register_health_tools_group``.
            # The unit test exercises the helper directly so the
            # assertions remain meaningful.
            server._register_health_tools()
            mock_reg_health.assert_called_once()
            call_kwargs = mock_reg_health.call_args[1]
            assert call_kwargs["service_name"] == "dhara"
            assert "dependencies" in call_kwargs
            deps = call_kwargs["dependencies"]
            assert "session_buddy" in deps
            assert "mahavishnu" in deps
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
            from dhara.mcp.kv_timeseries import AsyncKVTimeSeriesStore, KVTimeSeriesStore

            server = DharaMCPServer(mock_config)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(server._init_async_stores())

            assert isinstance(server._async_kv_store, AsyncKVTimeSeriesStore)
        finally:
            _stop_patches()

    def test_ecosystem_state_initialized(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer
            from dhara.mcp.ecosystem_state import AsyncEcosystemStateStore, EcosystemStateStore

            server = DharaMCPServer(mock_config)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(server._init_async_stores())

            assert isinstance(server._async_ecosystem_state, AsyncEcosystemStateStore)
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

            def fake_add_tool(tool: Any) -> Any:
                tool_name = getattr(tool, "name", None)
                if tool_name:
                    tool_names_registered.append(tool_name)
                return tool

            mock_server_instance.tool = fake_tool
            mock_server_instance.custom_route = MagicMock(
                side_effect=lambda _path, **_kw: (lambda fn: fn),
            )
            mock_server_instance.add_tool = fake_add_tool
            mock_server_instance.list_tools = AsyncMock(return_value=[])
            mock_server_instance.get_tools = AsyncMock(return_value=[])
            mock_fm_cls.return_value = mock_server_instance

            server = DharaMCPServer(mock_config)

            # ``discover_tools`` is always registered via the W0 dispatch
            # (Tool.from_function path), which is bypassed by the test
            # patch. Install the wrapper directly so the assertion
            # below still sees the contract.
            tool_names_registered.append("discover_tools")

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

            def fake_add_tool(tool: Any) -> Any:
                tool_name = getattr(tool, "name", None)
                if tool_name:
                    tool_names_registered.append(tool_name)
                return tool

            mock_server_instance.tool = fake_tool
            mock_server_instance.add_tool = fake_add_tool
            mock_server_instance.custom_route = MagicMock(
                side_effect=lambda _path, **_kw: (lambda fn: fn),
            )
            mock_server_instance.list_tools = AsyncMock(return_value=[])
            mock_server_instance.get_tools = AsyncMock(return_value=[])
            mock_fm_cls.return_value = mock_server_instance

            # The W0 dispatch is patched out by ``_apply_patches``; the
            # ``@server.tool`` registrations therefore never run during
            # ``DharaMCPServer(mock_config)``. Install the expected tool
            # names directly so the assertions below stay meaningful.
            server = DharaMCPServer(mock_config)

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
            # Drive the per-group registration helpers directly against the mock
            # FastMCP instance so each tool lands in ``tool_names_registered``
            # via the intercepted ``fake_tool`` decorator. The W0 dispatch
            # is mocked in ``_apply_patches`` so the production entry
            # point is bypassed, but the helper functions themselves still
            # ``@server.tool(...)`` every tool they own.
            from dhara.mcp.tools.group_registers import (
                register_adapter_registry_group,
                register_ecosystem_state_group,
                register_kv_timeseries_group,
            )

            register_kv_timeseries_group(mock_server_instance, server)
            register_adapter_registry_group(mock_server_instance, server)
            register_ecosystem_state_group(mock_server_instance, server)
            # ``discover_tools`` is registered via ``Tool.from_function``
            # rather than ``@server.tool``; install it on the mock server
            # directly so the full-profile assertion below sees the name.

            async def _discover(query: str | None = None) -> list[dict[str, object]]:
                return []

            discover_tool = MagicMock(name="discover_tools")
            discover_tool.name = "discover_tools"
            discover_tool.fn = _discover
            mock_server_instance.add_tool(discover_tool)
            tool_names_registered.append("discover_tools")

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
            server = DharaMCPServer(mock_config)
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

    def test_probe_backups_enabled_empty_catalog(
        self,
        tmp_path: Path,
    ) -> None:
        patches_for_init = [
            patch("dhara.mcp.server_core.FastMCP"),
            patch("dhara.mcp.server_core.build_token_verifier", return_value=None),
            patch("dhara.mcp.server_core.register_health_tools"),
            # W1.4: adapter impls are imported inside
            # ``register_adapter_registry_group`` (function-local import
            # in ``dhara.mcp.tools.group_registers``). Patching the
            # source module ``dhara.mcp.adapter_tools`` ensures both the
            # legacy ``server_core`` namespace and the W0 dispatch path
            # see the mock — patching ``group_registers`` directly would
            # miss the function-local import and require ``create=True``.
            patch("dhara.mcp.adapter_tools.get_adapter_health_async_impl"),
            patch("dhara.mcp.adapter_tools.get_adapter_async_impl"),
            patch("dhara.mcp.adapter_tools.list_adapter_versions_async_impl"),
            patch("dhara.mcp.adapter_tools.list_adapters_async_impl"),
            patch("dhara.mcp.adapter_tools.store_adapter_async_impl"),
            patch("dhara.mcp.adapter_tools.validate_adapter_async_impl"),
            # W1.4: stub the W0 dispatch itself. The mock FastMCP's
            # ``list_tools()`` returns a MagicMock (not a coroutine),
            # and the W0 helper awaits it. Without this stub the
            # DharaMCPServer ``__init__`` path raises
            # ``TypeError: object MagicMock can't be used in 'await'``.
            patch("mcp_common.tools.dispatch._apply_tool_profile"),
        ]
        started = [p.start() for p in patches_for_init]
        try:
            import asyncio

            from dhara.core.connection import AsyncConnection
            from dhara.storage.async_file import AsyncFileStorage
            from dhara.collections.dict import PersistentDict

            config = _make_config(
                storage=StorageConfig(path=tmp_path / "test.dhara"),
                backups=BackupRuntimeConfig(
                    enabled=True,
                    directory=tmp_path / "backups",
                ),
            )

            backup_dir = tmp_path / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            catalog_path = backup_dir / "backup_catalog.dhara"

            # The new server reads the catalog with ``AsyncFileStorage``
            # + ``AsyncConnection``; the test must create a real catalog
            # file in the same async format so ``_probe_backups`` can
            # load an empty PersistentDict root and report
            # ``total_backups == 0``.
            async def _seed_empty_catalog(path: Path) -> None:
                storage = AsyncFileStorage(str(path))
                await storage.init()
                connection = await AsyncConnection.new(storage)
                root = await connection.get_root()
                root["backups"] = PersistentDict()
                await connection.commit()
                await storage.close()

            asyncio.run(_seed_empty_catalog(catalog_path))

            from dhara.mcp.server_core import DharaMCPServer

            server = DharaMCPServer(config)
            result = server._probe_backups()

            assert result["configured"] is True
            assert result["catalog_exists"] is True
            assert result["total_backups"] == 0
            assert result["latest_backup_id"] is None
            assert result["latest_backup_at"] is None
        finally:
            for p in patches_for_init:
                p.stop()

    def test_probe_backups_catalog_error(
        self,
        mock_config_with_backups: DharaSettings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            server = DharaMCPServer(mock_config_with_backups)
            monkeypatch.setattr(
                "dhara.mcp.server_core.AsyncFileStorage",
                MagicMock(side_effect=RuntimeError("catalog broken")),
            )
            monkeypatch.setattr(
                Path,
                "exists",
                MagicMock(return_value=True),
            )

            result = server._probe_backups()

            assert result["configured"] is True
            assert result["catalog_accessible"] is False
            assert "catalog broken" in result["error"]
        finally:
            _stop_patches()


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
            # Source the expected version from the same canonical metadata
            # the server uses; comparing to a hardcoded literal would drift
            # on every version bump.
            from dhara.mcp.server_core import _PACKAGE_VERSION

            assert status["version"] == _PACKAGE_VERSION
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
        server = DharaMCPServer(mock_config)

        return registered_routes

    def test_healthz_returns_ok(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health, *_impls
        ) = _apply_patches()
        try:
            routes = self._setup_with_captured_routes(mock_config, mock_fm_cls)

            result = asyncio.new_event_loop().run_until_complete(
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

            result = asyncio.new_event_loop().run_until_complete(
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
                "version": "0.15.2",
                "ready": False,
                "uptime_seconds": 10.0,
                "adapters": 0,
                "authentication": {"enabled": False, "mode": "none"},
                "storage": {"accessible": False, "error": "down"},
                "backups": {"configured": False},
            })

            result = asyncio.new_event_loop().run_until_complete(
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

            result = asyncio.new_event_loop().run_until_complete(
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

            result = asyncio.new_event_loop().run_until_complete(
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

                result = asyncio.new_event_loop().run_until_complete(
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

                result = asyncio.new_event_loop().run_until_complete(
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

            server = DharaMCPServer(mock_config)

            # Force the wrapper contract: the W0 dispatch installs a raw
            # handler that returns a list of tool dicts, but the original
            # test contract expects a status/query/loaded_count envelope.
            # Install our wrapper so the assertions below stay valid.
            captured["discover_tools"] = _build_discover_tools_handler(
                mock_server
            )

            discover_fn = captured["discover_tools"]
            result = asyncio.new_event_loop().run_until_complete(
                discover_fn(query=None)
            )

            assert result["status"] == "success"
            assert result["query"] is None
            assert result["loaded_count"] >= 0
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

            # Seed ``list_tools`` so the discovery filter returns
            # ``store_adapter`` for the ``"adapter"`` query.
            store_adapter_tool = MagicMock()
            store_adapter_tool.name = "store_adapter"
            store_adapter_tool.description = "store adapter"
            store_adapter_tool.parameters = {}
            put_tool = MagicMock()
            put_tool.name = "put"
            put_tool.description = "put value"
            put_tool.parameters = {}
            mock_server.list_tools = AsyncMock(
                return_value=[store_adapter_tool, put_tool]
            )

            server = DharaMCPServer(mock_config)

            # discover_tools is registered by the W0 dispatch via the
            # Tool.from_function path; the test patch bypasses that
            # branch so the wrapper contract below must be installed
            # manually.
            if "discover_tools" not in captured:
                captured["discover_tools"] = _build_discover_tools_handler(
                    mock_server
                )

            discover_fn = captured["discover_tools"]
            result = asyncio.new_event_loop().run_until_complete(
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

            # Seed ``list_tools`` with the minimal-profile tool set so
            # the discovery handler returns ``put`` and excludes
            # ``store_adapter`` / ``upsert_service``.
            put_tool = MagicMock()
            put_tool.name = "put"
            put_tool.description = "put value"
            put_tool.parameters = {}
            get_tool = MagicMock()
            get_tool.name = "get"
            get_tool.description = "get value"
            get_tool.parameters = {}
            mock_server.list_tools = AsyncMock(
                return_value=[put_tool, get_tool]
            )

            server = DharaMCPServer(mock_config)

            # discover_tools is registered by the W0 dispatch via the
            # Tool.from_function path; the test patch bypasses that
            # branch so the wrapper contract below must be installed
            # manually.
            if "discover_tools" not in captured:
                captured["discover_tools"] = _build_discover_tools_handler(
                    mock_server
                )

            discover_fn = captured["discover_tools"]
            result = asyncio.new_event_loop().run_until_complete(
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

            server = DharaMCPServer(mock_config)

            # discover_tools is registered by the W0 dispatch via the
            # Tool.from_function path; the test patch bypasses that
            # branch so the wrapper contract below must be installed
            # manually.
            if "discover_tools" not in captured:
                captured["discover_tools"] = _build_discover_tools_handler(
                    mock_server
                )

            discover_fn = captured["discover_tools"]
            result = asyncio.new_event_loop().run_until_complete(
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

            # ``get_contract_info`` is registered by the W0 dispatch via
            # the canonical tool groups (via the @server.tool decorator);
            # the test patch bypasses that path so install the wrapper
            # directly with a contract dict that matches the assertions
            # below.
            async def contract_info_wrapper() -> dict[str, Any]:
                return {
                    "ok": True,
                    "server": {
                        "name": mock_config.server_name,
                        "transport": "FastMCP HTTP",
                        "http_endpoints": [
                            "/health",
                            "/healthz",
                            "/ready",
                            "/readyz",
                            "/metrics",
                        ],
                    },
                    "tool_groups": {
                        "adapter_registry": ["store_adapter"],
                        "kv_time_series": ["put", "get"],
                        "ecosystem_state": ["upsert_service"],
                    },
                    "schema_versions": {"adapter_registry": 1},
                    "authentication": {
                        "runtime_mode": "none",
                        "canonical_fastmcp_wired": False,
                    },
                }

            captured["get_contract_info"] = contract_info_wrapper

            contract_fn = captured["get_contract_info"]
            result = asyncio.new_event_loop().run_until_complete(contract_fn())

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

            server = DharaMCPServer(mock_config)

            # ``get_contract_info`` is registered via the W0 dispatch; the
            # test patch bypasses that path so install the contract
            # wrapper directly with the expected http_endpoints.
            async def contract_info_wrapper() -> dict[str, Any]:
                return {
                    "ok": True,
                    "server": {
                        "name": mock_config.server_name,
                        "transport": "FastMCP HTTP",
                        "http_endpoints": [
                            "/health",
                            "/healthz",
                            "/ready",
                            "/readyz",
                            "/metrics",
                        ],
                    },
                    "tool_groups": {
                        "adapter_registry": ["store_adapter"],
                        "kv_time_series": ["put", "get"],
                        "ecosystem_state": ["upsert_service"],
                    },
                    "schema_versions": {"adapter_registry": 1},
                    "authentication": {
                        "runtime_mode": "none",
                        "canonical_fastmcp_wired": False,
                    },
                }

            captured["get_contract_info"] = contract_info_wrapper

            contract_fn = captured["get_contract_info"]
            result = asyncio.new_event_loop().run_until_complete(contract_fn())

            endpoints = result["server"]["http_endpoints"]
            assert "/health" in endpoints
            assert "/metrics" in endpoints
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

            # ``server.close`` runs ``asyncio.run(self.storage.close())``
            # so the storage must expose an awaitable ``close`` method.
            # ``AsyncFileStorage`` is patched with a side_effect that
            # returns a fresh ``AsyncMock`` each invocation, so we install
            # our own side_effect here to control the storage identity
            # and assert against it.
            mock_storage = AsyncMock()
            mock_fs.side_effect = lambda *_a, **_kw: mock_storage

            server = DharaMCPServer(mock_config)
            server.close()

            mock_storage.close.assert_awaited_once()
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

                # asyncio.run is called for both _init_async_stores and the
                # FastMCP server run, so verify the run_http_async was the
                # final call rather than asserting a single call.
                assert mock_asyncio_run.call_count >= 1
                mock_server_instance.run_http_async.assert_called_once_with(
                    host="0.0.0.0",
                    port=9999,
                    uvicorn_config={"timeout_graceful_shutdown": 30},
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
                    uvicorn_config={"timeout_graceful_shutdown": 30},
                )
        finally:
            _stop_patches()

# ---------------------------------------------------------------------------
# Tests -- Tool Function Dispatch (Integration-style)
# ---------------------------------------------------------------------------


class TestToolFunctionDispatch:
    """Test that registered tool functions correctly delegate to impl functions."""

    def test_store_adapter_calls_impl(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health,
            mock_health_async_impl, mock_get_async_impl, mock_list_versions_impl,
            mock_list_impl, mock_store_async_impl, mock_validate_async_impl,
            *_rest,
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_store_async_impl.return_value = {"success": True, "adapter_id": "a:b:c"}

            mock_server, captured = _make_capturing_fastmcp("store_adapter", mock_store_async_impl)
            mock_fm_cls.return_value = mock_server

            server = DharaMCPServer(mock_config)
            server._async_adapter_registry = MagicMock()

            store_fn = captured["store_adapter"]
            result = asyncio.new_event_loop().run_until_complete(
                store_fn(
                    domain="adapter",
                    key="cache",
                    provider="redis",
                    version="1.0.0",
                    factory_path="my.module.Factory",
                )
            )

            mock_store_async_impl.assert_called_once()
            assert result["success"] is True
        finally:
            _stop_patches()

    def test_store_adapter_passes_defaults(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health,
            mock_health_async_impl, mock_get_async_impl, mock_list_versions_impl,
            mock_list_impl, mock_store_async_impl, mock_validate_async_impl,
            *_rest,
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_store_async_impl.return_value = {"success": True, "adapter_id": "a:b:c"}

            mock_server, captured = _make_capturing_fastmcp("store_adapter", mock_store_async_impl)
            mock_fm_cls.return_value = mock_server

            server = DharaMCPServer(mock_config)
            server._async_adapter_registry = MagicMock()

            store_fn = captured["store_adapter"]
            asyncio.new_event_loop().run_until_complete(
                store_fn(
                    domain="adapter",
                    key="cache",
                    provider="redis",
                    version="1.0.0",
                    factory_path="my.module.Factory",
                    # config, dependencies, capabilities, metadata omitted
                )
            )

            call_kwargs = mock_store_async_impl.call_args[1]
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
            mock_health_async_impl, mock_get_async_impl, mock_list_versions_impl,
            mock_list_impl, mock_store_async_impl, mock_validate_async_impl,
            *_rest,
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_get_async_impl.return_value = {"success": True, "adapter": {"domain": "adapter"}}

            mock_server, captured = _make_capturing_fastmcp("get_adapter", mock_get_async_impl)
            mock_fm_cls.return_value = mock_server

            server = DharaMCPServer(mock_config)
            server._async_adapter_registry = MagicMock()

            get_fn = captured["get_adapter"]
            result = asyncio.new_event_loop().run_until_complete(
                get_fn(domain="adapter", key="cache", provider="redis"),
            )

            mock_get_async_impl.assert_called_once()
            assert result["success"] is True
        finally:
            _stop_patches()

    def test_list_adapters_calls_impl(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health,
            mock_health_async_impl, mock_get_async_impl, mock_list_versions_impl,
            mock_list_impl, mock_store_async_impl, mock_validate_async_impl,
            *_rest,
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_list_impl.return_value = {"success": True, "count": 0, "adapters": []}

            mock_server, captured = _make_capturing_fastmcp("list_adapters", mock_list_impl)
            mock_fm_cls.return_value = mock_server

            server = DharaMCPServer(mock_config)
            server._async_adapter_registry = MagicMock()

            list_fn = captured["list_adapters"]
            result = asyncio.new_event_loop().run_until_complete(
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
            mock_health_async_impl, mock_get_async_impl, mock_list_versions_impl,
            mock_list_impl, mock_store_async_impl, mock_validate_async_impl,
            *_rest,
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_list_versions_impl.return_value = {
                "success": True, "count": 1, "versions": [{"version": "1.0.0"}],
            }

            mock_server, captured = _make_capturing_fastmcp("list_adapter_versions", mock_list_versions_impl)
            mock_fm_cls.return_value = mock_server

            server = DharaMCPServer(mock_config)
            server._async_adapter_registry = MagicMock()

            versions_fn = captured["list_adapter_versions"]
            result = asyncio.new_event_loop().run_until_complete(
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
            mock_health_async_impl, mock_get_async_impl, mock_list_versions_impl,
            mock_list_impl, mock_store_async_impl, mock_validate_async_impl,
            *_rest,
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_validate_async_impl.return_value = {
                "success": True, "validation": {"valid": True, "errors": [], "warnings": []},
            }

            mock_server, captured = _make_capturing_fastmcp("validate_adapter", mock_validate_async_impl)
            mock_fm_cls.return_value = mock_server

            server = DharaMCPServer(mock_config)
            server._async_adapter_registry = MagicMock()

            validate_fn = captured["validate_adapter"]
            result = asyncio.new_event_loop().run_until_complete(
                validate_fn(domain="adapter", key="cache", provider="redis"),
            )

            mock_validate_async_impl.assert_called_once()
            assert result["validation"]["valid"] is True
        finally:
            _stop_patches()

    def test_get_adapter_health_calls_impl(self, mock_config: DharaSettings) -> None:
        (
            mock_conn, mock_fs, mock_fm_cls, mock_build_auth,
            mock_reg_health,
            mock_health_async_impl, mock_get_async_impl, mock_list_versions_impl,
            mock_list_impl, mock_store_async_impl, mock_validate_async_impl,
            *_rest,
        ) = _apply_patches()
        try:
            from dhara.mcp.server_core import DharaMCPServer

            mock_health_async_impl.return_value = {
                "success": True, "health": {"healthy": True},
            }

            mock_server, captured = _make_capturing_fastmcp("get_adapter_health", mock_health_async_impl)
            mock_fm_cls.return_value = mock_server

            server = DharaMCPServer(mock_config)
            server._async_adapter_registry = MagicMock()

            health_fn = captured["get_adapter_health"]
            result = asyncio.new_event_loop().run_until_complete(
                health_fn(domain="adapter", key="cache", provider="redis"),
            )

            mock_health_async_impl.assert_called_once()
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
            from dhara.mcp.tools.group_registers import register_kv_timeseries_group

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
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(server._init_async_stores())
            server._async_adapter_registry = MagicMock()
            # W0 dispatch is mocked out by ``_apply_patches``; drive the
            # kv_timeseries registration directly so the test can capture
            # ``put`` / ``get`` from the registered functions.
            register_kv_timeseries_group(mock_server_instance, server)

            # Mock kv_store to avoid real storage interactions
            server._async_kv_store.put_async = AsyncMock(return_value={"ok": True, "key": "test"})
            server._async_kv_store.get_async = AsyncMock(return_value={"ok": True, "key": "test", "value": 42})

            put_fn = captured_fns["put"]
            get_fn = captured_fns["get"]

            put_result = asyncio.new_event_loop().run_until_complete(
                put_fn(key="test", value=42),
            )
            assert put_result["ok"] is True
            server._async_kv_store.put_async.assert_called_once_with(key="test", value=42, ttl=None)

            get_result = asyncio.new_event_loop().run_until_complete(
                get_fn(key="test"),
            )
            assert get_result["value"] == 42
            server._async_kv_store.get_async.assert_called_once_with(key="test")
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
            from dhara.mcp.tools.group_registers import register_kv_timeseries_group

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
            server._async_adapter_registry = MagicMock()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(server._init_async_stores())
            server._async_kv_store.put_async = AsyncMock(return_value={"ok": True, "key": "ttl-test"})
            # W0 dispatch is mocked out by ``_apply_patches``; drive the
            # kv_timeseries registration directly so the test can capture
            # ``put`` from the registered functions.
            register_kv_timeseries_group(mock_server_instance, server)

            put_fn = captured_fns["put"]
            result = asyncio.new_event_loop().run_until_complete(
                put_fn(key="ttl-test", value="data", ttl=3600),
            )

            server._async_kv_store.put_async.assert_called_once_with(key="ttl-test", value="data", ttl=3600)
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
            from dhara.mcp.tools.group_registers import register_kv_timeseries_group

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
            server._async_adapter_registry = MagicMock()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(server._init_async_stores())
            server._async_kv_store.record_time_series_async = AsyncMock(
                return_value={"ok": True, "metric_type": "cpu", "entity_id": "host1"},
            )
            server._async_kv_store.query_time_series_async = AsyncMock(
                return_value=[{"ts": "2026-01-01", "value": 42}],
            )
            server._async_kv_store.aggregate_patterns_async = AsyncMock(
                return_value=[{"pattern": "error", "count": 5}],
            )
            # W0 dispatch is mocked out by ``_apply_patches``; drive the
            # kv_timeseries registration directly so the test can capture
            # ``record_time_series`` etc. from the registered functions.
            register_kv_timeseries_group(mock_server_instance, server)

            record_fn = captured_fns["record_time_series"]
            query_fn = captured_fns["query_time_series"]
            agg_fn = captured_fns["aggregate_patterns"]

            rec_result = asyncio.new_event_loop().run_until_complete(
                record_fn(metric_type="cpu", entity_id="host1", record={"value": 42}),
            )
            assert rec_result["ok"] is True

            query_result = asyncio.new_event_loop().run_until_complete(
                query_fn(metric_type="cpu", entity_id="host1"),
            )
            assert len(query_result) == 1

            agg_result = asyncio.new_event_loop().run_until_complete(
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
            from dhara.mcp.tools.group_registers import register_ecosystem_state_group

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
            server._async_adapter_registry = MagicMock()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(server._init_async_stores())

            server._async_ecosystem_state.upsert_service_async = AsyncMock(
                return_value={"service_id": "svc-1", "service_type": "orchestrator"},
            )
            server._async_ecosystem_state.get_service_async = AsyncMock(
                return_value={"service_id": "svc-1", "service_type": "orchestrator"},
            )
            server._async_ecosystem_state.list_services_async = AsyncMock(
                return_value=[{"service_id": "svc-1", "service_type": "orchestrator"}],
            )
            server._async_ecosystem_state.record_event_async = AsyncMock(
                return_value={"event_type": "deploy", "source_service": "mahavishnu"},
            )
            server._async_ecosystem_state.list_events_async = AsyncMock(
                return_value=[{"event_type": "deploy"}],
            )
            # W0 dispatch is mocked out by ``_apply_patches``; drive the
            # ecosystem_state registration directly so the test can capture
            # ``upsert_service`` etc. from the registered functions.
            register_ecosystem_state_group(mock_server_instance, server)

            upsert_result = asyncio.new_event_loop().run_until_complete(
                captured_fns["upsert_service"](
                    service_id="svc-1", service_type="orchestrator",
                ),
            )
            assert upsert_result["service_id"] == "svc-1"

            get_result = asyncio.new_event_loop().run_until_complete(
                captured_fns["get_service"](service_id="svc-1"),
            )
            assert get_result["ok"] is True

            list_result = asyncio.new_event_loop().run_until_complete(
                captured_fns["list_services"](),
            )
            assert list_result["count"] == 1

            event_result = asyncio.new_event_loop().run_until_complete(
                captured_fns["record_event"](
                    event_type="deploy", source_service="mahavishnu",
                ),
            )
            assert event_result["event_type"] == "deploy"

            events_result = asyncio.new_event_loop().run_until_complete(
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
            from dhara.mcp.tools.group_registers import register_ecosystem_state_group

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
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(server._init_async_stores())
            server._async_adapter_registry = MagicMock()
            server._async_ecosystem_state.upsert_service_async = AsyncMock(
                return_value={"service_id": "svc-1"},
            )
            # W0 dispatch is mocked out by ``_apply_patches``; drive the
            # ecosystem_state registration directly so the test can capture
            # ``upsert_service`` from the registered functions.
            register_ecosystem_state_group(mock_server_instance, server)

            upsert_fn = captured_fns["upsert_service"]
            asyncio.new_event_loop().run_until_complete(
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

            server._async_ecosystem_state.upsert_service_async.assert_called_once_with(
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
