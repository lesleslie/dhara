"""Extended unit tests for dhara.server.socket — push coverage to ≥95%.

Targets:
  - SD_LISTEN_FDS_START constant
  - _set_close_on_exec() all three branches (ImportError, FD_CLOEXEC missing,
    normal fcntl path with right fd range, fds=0)
  - sd_listen_fds() all branches: missing/ValueError LISTEN_PID, missing/ValueError
    LISTEN_FDS, pid mismatch, success path that calls _set_close_on_exec
  - _socket_from_fd() all three family branches (AF_UNIX str, AF_UNIX bytes,
    AF_INET, AF_INET6) plus the os.close(7) of the original fd
  - get_systemd_socket() three branches: no inherited fds, multiple fds (error),
    single fd (success)

Pure unit tests: no live network, no real systemd activation, mocking of all
platform-bound sockets.
"""

from __future__ import annotations

import importlib
import os
import socket
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from dhara.server import socket as server_socket


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestSDListenFdsStart:
    """SD_LISTEN_FDS_START is the first inherited sd fd (3)."""

    def test_constant_value(self) -> None:
        assert server_socket.SD_LISTEN_FDS_START == 3

    def test_constant_is_int(self) -> None:
        assert isinstance(server_socket.SD_LISTEN_FDS_START, int)


# ---------------------------------------------------------------------------
# _set_close_on_exec
# ---------------------------------------------------------------------------


class TestSetCloseOnExec:
    """_set_close_on_exec sets FD_CLOEXEC on the inherited fds 3..3+N-1."""

    def test_returns_silently_when_fcntl_unimportable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The `import fcntl` inside _set_close_on_exec is wrapped in try/except."""
        import builtins

        original_import = builtins.__import__

        def blocking_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "fcntl":
                raise ImportError("blocked by test")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocking_import)
        # Should return None without raising.
        assert server_socket._set_close_on_exec(5) is None

    def test_returns_silently_when_fcntl_lacks_FD_CLOEXEC(self) -> None:
        """If fcntl is importable but has no FD_CLOEXEC attr, short-circuit."""
        fake_fcntl = types.ModuleType("fcntl")
        fake_fcntl.F_SETFD = 2
        # No FD_CLOEXEC attribute.
        fake_fcntl.fcntl = MagicMock()
        with patch.dict(sys.modules, {"fcntl": fake_fcntl}):
            assert server_socket._set_close_on_exec(2) is None
        # fcntl.fcntl must not have been called since the early-return fired.
        fake_fcntl.fcntl.assert_not_called()

    def test_calls_fcntl_for_each_fd_when_supported(self) -> None:
        """Happy path: one fcntl.fcntl(fd, F_SETFD, FD_CLOEXEC) per fd."""
        fake_fcntl = types.ModuleType("fcntl")
        fake_fcntl.F_SETFD = 2
        fake_fcntl.FD_CLOEXEC = 1
        seen: list[tuple[int, int, int]] = []

        def record(fd: int, flag: int, val: int) -> None:
            seen.append((fd, flag, val))

        fake_fcntl.fcntl = record
        with patch.dict(sys.modules, {"fcntl": fake_fcntl}):
            server_socket._set_close_on_exec(3)

        assert seen == [
            (3, fake_fcntl.F_SETFD, fake_fcntl.FD_CLOEXEC),
            (4, fake_fcntl.F_SETFD, fake_fcntl.FD_CLOEXEC),
            (5, fake_fcntl.F_SETFD, fake_fcntl.FD_CLOEXEC),
        ]

    def test_zero_count_no_calls(self) -> None:
        """fds=0 should iterate an empty range and never call fcntl."""
        fake_fcntl = types.ModuleType("fcntl")
        fake_fcntl.F_SETFD = 2
        fake_fcntl.FD_CLOEXEC = 1
        fake_fcntl.fcntl = MagicMock()
        with patch.dict(sys.modules, {"fcntl": fake_fcntl}):
            server_socket._set_close_on_exec(0)
        fake_fcntl.fcntl.assert_not_called()


# ---------------------------------------------------------------------------
# sd_listen_fds
# ---------------------------------------------------------------------------


class TestSDListenFds:
    """sd_listen_fds() reads LISTEN_PID and LISTEN_FDS from environ."""

    def setup_method(self) -> None:
        self._env_backup = os.environ.copy()

    def teardown_method(self) -> None:
        os.environ.clear()
        os.environ.update(self._env_backup)

    def test_returns_zero_when_listen_pid_unset(self) -> None:
        os.environ.pop("LISTEN_PID", None)
        os.environ.pop("LISTEN_FDS", None)
        assert server_socket.sd_listen_fds() == 0

    def test_returns_zero_when_listen_pid_value_invalid(self) -> None:
        os.environ["LISTEN_PID"] = "not-a-number"
        os.environ["LISTEN_FDS"] = "1"
        # ``int("not-a-number")`` raises ValueError, caught by the bare
        # ``except ValueError, KeyError:`` clause (Py2-compatible syntax).
        assert server_socket.sd_listen_fds() == 0

    def test_returns_zero_when_pid_does_not_match(self) -> None:
        os.environ["LISTEN_PID"] = str(os.getpid() + 1)
        os.environ["LISTEN_FDS"] = "1"
        assert server_socket.sd_listen_fds() == 0

    def test_raises_oserror_when_listen_fds_unset(self) -> None:
        os.environ["LISTEN_PID"] = str(os.getpid())
        os.environ.pop("LISTEN_FDS", None)
        with pytest.raises(OSError, match="invalid LISTEN_FDS value"):
            server_socket.sd_listen_fds()

    def test_raises_oserror_when_listen_fds_value_invalid(self) -> None:
        os.environ["LISTEN_PID"] = str(os.getpid())
        os.environ["LISTEN_FDS"] = "garbage"
        with pytest.raises(OSError, match="invalid LISTEN_FDS value"):
            server_socket.sd_listen_fds()

    def test_returns_fd_count_on_match(self) -> None:
        os.environ["LISTEN_PID"] = str(os.getpid())
        os.environ["LISTEN_FDS"] = "4"
        # Stub _set_close_on_exec since the test environment may lack fcntl.
        with patch.object(server_socket, "_set_close_on_exec", MagicMock()):
            assert server_socket.sd_listen_fds() == 4

    def test_invokes_set_close_on_exec_with_listen_fds_value(self) -> None:
        os.environ["LISTEN_PID"] = str(os.getpid())
        os.environ["LISTEN_FDS"] = "2"
        with patch.object(server_socket, "_set_close_on_exec", MagicMock()) as ce:
            server_socket.sd_listen_fds()
        ce.assert_called_once_with(2)


# ---------------------------------------------------------------------------
# _socket_from_fd — branching on getsockname()'s return shape
# ---------------------------------------------------------------------------


class TestSocketFromFd:
    """_socket_from_fd picks the family based on getsockname()'s return shape."""

    def _run(self, fake_name: object) -> tuple[socket.socket, list[int]]:
        """Run ``_socket_from_fd(7)`` with patched fromfd/getsockname/os.close.

        Returns (result_socket, list_of_families_passed_to_fromfd). The first
        family is always AF_UNIX (the probe); the second is the inferred family.
        ``os.close`` is patched since we never pass a real fd.
        """
        seen_families: list[int] = []
        real_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        def fake_fromfd(fd: int, family: int, kind: int, proto: int = 0) -> socket.socket:
            seen_families.append(family)
            return probe_socket if len(seen_families) == 1 else real_socket

        try:
            with (
                patch.object(socket, "fromfd", side_effect=fake_fromfd),
                patch.object(
                    socket.socket,
                    "getsockname",
                    lambda _self: fake_name,
                ),
                patch.object(os, "close"),
            ):
                result = server_socket._socket_from_fd(7)
        finally:
            probe_socket.close()
        return result, seen_families

    def test_unix_str_path_yields_af_unix(self) -> None:
        """``isinstance(name, str)`` — AF_UNIX."""
        result, seen = self._run("/tmp/sock")
        try:
            # The real socket was created with AF_INET but that's irrelevant —
            # we're testing the family that _socket_from_fd passes to fromfd
            # the second time around.
            assert seen[0] == socket.AF_UNIX  # probe
            assert seen[1] == socket.AF_UNIX  # inferred
        finally:
            result.close()

    def test_unix_bytes_path_yields_af_unix(self) -> None:
        """``isinstance(name, bytes)`` — AF_UNIX."""
        result, seen = self._run(b"/tmp/sock")
        try:
            assert seen[1] == socket.AF_UNIX
        finally:
            result.close()

    def test_inet_tuple_without_colon_yields_af_inet(self) -> None:
        """2-tuple with no ':' — AF_INET."""
        result, seen = self._run(("127.0.0.1", 8080))
        try:
            assert seen[1] == socket.AF_INET
        finally:
            result.close()

    def test_inet6_tuple_with_colon_yields_af_inet6(self) -> None:
        """4-tuple with ':' — AF_INET6."""
        result, seen = self._run(("::1", 8080, 0, 0))
        try:
            assert seen[1] == socket.AF_INET6
        finally:
            result.close()

    def test_closes_original_fd(self) -> None:
        """``os.close(fd)`` is called once after the second fromfd."""
        fake_name = b"/tmp/sock"
        probe_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            with (
                patch.object(
                    socket,
                    "fromfd",
                    side_effect=lambda *a, **kw: probe_socket,
                ),
                patch.object(
                    socket.socket,
                    "getsockname",
                    lambda _self: fake_name,
                ),
                patch.object(os, "close") as close_mock,
            ):
                server_socket._socket_from_fd(99)
            close_mock.assert_called_once_with(99)
        finally:
            probe_socket.close()


# ---------------------------------------------------------------------------
# get_systemd_socket
# ---------------------------------------------------------------------------


class TestGetSystemdSocket:
    """get_systemd_socket() returns the inherited socket or None."""

    def setup_method(self) -> None:
        self._env_backup = os.environ.copy()

    def teardown_method(self) -> None:
        os.environ.clear()
        os.environ.update(self._env_backup)

    def test_returns_none_when_no_listen_pid(self) -> None:
        os.environ.pop("LISTEN_PID", None)
        os.environ.pop("LISTEN_FDS", None)
        assert server_socket.get_systemd_socket() is None

    def test_returns_none_when_pid_mismatch(self) -> None:
        os.environ["LISTEN_PID"] = str(os.getpid() + 1)
        os.environ["LISTEN_FDS"] = "1"
        assert server_socket.get_systemd_socket() is None

    def test_raises_oserror_on_multiple_inherited_fds(self) -> None:
        os.environ["LISTEN_PID"] = str(os.getpid())
        os.environ["LISTEN_FDS"] = "2"
        with pytest.raises(OSError, match="only one inherited socket supported"):
            server_socket.get_systemd_socket()

    def test_returns_socket_on_single_inherited_fd(self) -> None:
        """Single inherited fd → wraps it via _socket_from_fd."""
        os.environ["LISTEN_PID"] = str(os.getpid())
        os.environ["LISTEN_FDS"] = "1"

        real = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            with (
                patch.object(server_socket, "_set_close_on_exec", MagicMock()),
                patch.object(
                    server_socket,
                    "_socket_from_fd",
                    MagicMock(return_value=real),
                ) as from_fd_mock,
            ):
                result = server_socket.get_systemd_socket()
            assert result is real
            from_fd_mock.assert_called_once_with(server_socket.SD_LISTEN_FDS_START)
        finally:
            real.close()


# ---------------------------------------------------------------------------
# Module reload smoke test
# ---------------------------------------------------------------------------


class TestModuleReload:
    """Re-importing the module should be safe and preserve public API."""

    def test_module_reload_preserves_callables(self) -> None:
        importlib.reload(server_socket)
        assert callable(server_socket.sd_listen_fds)
        assert callable(server_socket.get_systemd_socket)
        assert callable(server_socket._set_close_on_exec)
        assert callable(server_socket._socket_from_fd)
        assert server_socket.SD_LISTEN_FDS_START == 3
