"""Extended coverage tests for ``dhara.mcp.__main__``.

The ``dhara.mcp.__main__`` module is the canonical ``python -m dhara.mcp``
entry point. It is a tiny module — one ``main()`` function plus a
``__main__`` guard — but the canonical unit-test location (``tests/unit/``)
has no existing coverage. ``tests/test_mcp_main.py`` covers the
``main()`` happy path; ``tests/unit/test_mcp_main_transport_kwarg.py``
guards the ``DharaMCPServer.run`` signature. These tests target the
remaining paths: argument flow, error propagation, and the call-order
invariant between ``DharaSettings.load`` → ``DharaMCPServer(...)`` →
``server.run()``.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest

import dhara.mcp.__main__ as main_mod
from dhara.mcp.__main__ import main


class TestMainHappyPath:
    """``main()`` loads settings → constructs server → calls ``run()``."""

    def test_main_calls_dhara_settings_load(self) -> None:
        config = object()
        server = MagicMock()
        with patch(
            "dhara.mcp.__main__.DharaSettings.load",
            return_value=config,
        ) as mock_load:
            with patch(
                "dhara.mcp.__main__.DharaMCPServer",
                return_value=server,
            ):
                main()

        mock_load.assert_called_once_with()

    def test_main_constructs_dhara_mcp_server_with_loaded_config(self) -> None:
        config = object()
        server = MagicMock()
        with patch(
            "dhara.mcp.__main__.DharaSettings.load",
            return_value=config,
        ):
            with patch(
                "dhara.mcp.__main__.DharaMCPServer",
                return_value=server,
            ) as mock_server:
                main()

        mock_server.assert_called_once_with(config)

    def test_main_calls_server_run(self) -> None:
        config = object()
        server = MagicMock()
        with patch(
            "dhara.mcp.__main__.DharaSettings.load",
            return_value=config,
        ):
            with patch(
                "dhara.mcp.__main__.DharaMCPServer",
                return_value=server,
            ) as mock_server:
                main()

        mock_server.return_value.run.assert_called_once_with()

    def test_main_calls_load_before_constructing_server(self) -> None:
        """Order matters: settings must be loaded before the server is
        constructed so the server receives a fully-populated config."""

        call_order: list[str] = []

        def _record_load() -> object:
            call_order.append("load")
            return object()

        def _record_server(_config: object) -> MagicMock:
            call_order.append("server")
            return MagicMock()

        with patch(
            "dhara.mcp.__main__.DharaSettings.load",
            side_effect=_record_load,
        ):
            with patch(
                "dhara.mcp.__main__.DharaMCPServer",
                side_effect=_record_server,
            ):
                main()

        assert call_order == ["load", "server"]

    def test_main_calls_server_run_after_construction(self) -> None:
        call_order: list[str] = []
        server = MagicMock()

        def _record_server_ctor(_config: object) -> MagicMock:
            call_order.append("server_ctor")
            return server

        def _record_run() -> None:
            call_order.append("run")

        server.run.side_effect = _record_run

        with patch(
            "dhara.mcp.__main__.DharaSettings.load",
            return_value=object(),
        ):
            with patch(
                "dhara.mcp.__main__.DharaMCPServer",
                side_effect=_record_server_ctor,
            ):
                main()

        assert call_order == ["server_ctor", "run"]

    def test_main_propagates_load_error(self) -> None:
        """If ``DharaSettings.load()`` raises, ``main()`` must propagate the
        exception — it does not catch its own bootstrap failures."""

        class _BootError(RuntimeError):
            pass

        with patch(
            "dhara.mcp.__main__.DharaSettings.load",
            side_effect=_BootError("settings broken"),
        ):
            with pytest.raises(_BootError, match="settings broken"):
                main()

    def test_main_propagates_server_constructor_error(self) -> None:
        """If ``DharaMCPServer(config)`` raises, ``main()`` must propagate."""

        class _BuildError(RuntimeError):
            pass

        with patch(
            "dhara.mcp.__main__.DharaSettings.load",
            return_value=object(),
        ):
            with patch(
                "dhara.mcp.__main__.DharaMCPServer",
                side_effect=_BuildError("ctor broken"),
            ):
                with pytest.raises(_BuildError, match="ctor broken"):
                    main()

    def test_main_propagates_server_run_error(self) -> None:
        """If ``server.run()`` raises, ``main()`` must propagate."""

        class _RunError(RuntimeError):
            pass

        server = MagicMock()
        server.run.side_effect = _RunError("run broken")

        with patch(
            "dhara.mcp.__main__.DharaSettings.load",
            return_value=object(),
        ):
            with patch(
                "dhara.mcp.__main__.DharaMCPServer",
                return_value=server,
            ):
                with pytest.raises(_RunError, match="run broken"):
                    main()


class TestMainSignature:
    """``main()`` is a no-arg callable."""

    def test_main_takes_no_arguments(self) -> None:
        sig = inspect.signature(main)
        assert list(sig.parameters) == [], (
            f"main() should take no arguments; got {sig.parameters!r}"
        )

    def test_main_returns_none(self) -> None:
        sig = inspect.signature(main)
        assert sig.return_annotation is None

    def test_main_is_callable(self) -> None:
        assert callable(main)


class TestModuleImports:
    """Module-level symbol surface."""

    def test_module_exposes_main(self) -> None:
        assert hasattr(main_mod, "main")
        assert callable(main_mod.main)

    def test_module_imports_dhara_settings(self) -> None:
        assert hasattr(main_mod, "DharaSettings")

    def test_module_imports_dhara_mcp_server(self) -> None:
        assert hasattr(main_mod, "DharaMCPServer")
