"""Tests for dhara.server.socket."""

from __future__ import annotations

import os
import sys
import types
import socket

import pytest

from dhara.server import socket as server_socket


class TestSetCloseOnExec:
    def test_no_fcntl_module_returns(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "fcntl", None)
        server_socket._set_close_on_exec(1)

    def test_no_fd_cloexec_returns(self, monkeypatch):
        fake_fcntl = types.SimpleNamespace(F_SETFD=1)
        monkeypatch.setitem(sys.modules, "fcntl", fake_fcntl)
        server_socket._set_close_on_exec(1)

    def test_sets_close_on_exec(self, monkeypatch):
        calls: list[tuple[int, int, int]] = []

        def fake_fcntl(fd, op, flag):
            calls.append((fd, op, flag))

        fake_fcntl_mod = types.SimpleNamespace(
            F_SETFD=2,
            FD_CLOEXEC=4,
            fcntl=fake_fcntl,
        )
        monkeypatch.setitem(sys.modules, "fcntl", fake_fcntl_mod)

        server_socket._set_close_on_exec(2)

        assert calls == [(3, 2, 4), (4, 2, 4)]


class TestSdListenFds:
    def test_invalid_pid_returns_zero(self, monkeypatch):
        monkeypatch.setenv("LISTEN_PID", "123")
        monkeypatch.setenv("LISTEN_FDS", "1")
        monkeypatch.setattr(os, "getpid", lambda: 456)
        assert server_socket.sd_listen_fds() == 0

    def test_invalid_pid_value_returns_zero(self, monkeypatch):
        monkeypatch.setenv("LISTEN_PID", "not-an-int")
        monkeypatch.setenv("LISTEN_FDS", "1")
        assert server_socket.sd_listen_fds() == 0

    def test_missing_fds_raises(self, monkeypatch):
        monkeypatch.setenv("LISTEN_PID", str(os.getpid()))
        monkeypatch.delenv("LISTEN_FDS", raising=False)
        with pytest.raises(OSError, match="invalid LISTEN_FDS value"):
            server_socket.sd_listen_fds()

    def test_returns_fds_and_sets_close_on_exec(self, monkeypatch):
        calls: list[int] = []

        monkeypatch.setenv("LISTEN_PID", str(os.getpid()))
        monkeypatch.setenv("LISTEN_FDS", "2")
        monkeypatch.setattr(server_socket, "_set_close_on_exec", lambda fds: calls.append(fds))

        assert server_socket.sd_listen_fds() == 2
        assert calls == [2]


class TestSocketFromFd:
    def test_uses_unix_family_for_string_name(self, monkeypatch):
        calls: list[tuple[int, int, int]] = []

        class FakeSocket:
            def __init__(self, name):
                self._name = name
                self.closed = False

            def getsockname(self):
                return self._name

            def close(self):
                self.closed = True

        first = FakeSocket("/tmp/sock")
        second = FakeSocket(None)

        def fake_fromfd(fd, family, socktype):
            calls.append((fd, family, socktype))
            return first if len(calls) == 1 else second

        monkeypatch.setattr(server_socket.socket, "fromfd", fake_fromfd)
        closed: list[int] = []
        monkeypatch.setattr(server_socket.os, "close", lambda fd: closed.append(fd))

        result = server_socket._socket_from_fd(7)

        assert result is second
        assert calls[0] == (7, socket.AF_UNIX, socket.SOCK_STREAM)
        assert calls[1] == (7, socket.AF_UNIX, socket.SOCK_STREAM)
        assert closed == [7]

    def test_uses_inet6_family_for_ipv6_name(self, monkeypatch):
        calls: list[tuple[int, int, int]] = []

        class FakeSocket:
            def __init__(self, name):
                self._name = name

            def getsockname(self):
                return self._name

            def close(self):
                pass

        first = FakeSocket(("::1", 1234, 0, 0))
        second = FakeSocket(None)

        def fake_fromfd(fd, family, socktype):
            calls.append((fd, family, socktype))
            return first if len(calls) == 1 else second

        monkeypatch.setattr(server_socket.socket, "fromfd", fake_fromfd)
        monkeypatch.setattr(server_socket.os, "close", lambda fd: None)

        result = server_socket._socket_from_fd(8)

        assert result is second
        assert calls[0] == (8, socket.AF_UNIX, socket.SOCK_STREAM)
        assert calls[1] == (8, socket.AF_INET6, socket.SOCK_STREAM)

    def test_uses_inet_family_for_ipv4_name(self, monkeypatch):
        calls: list[tuple[int, int, int]] = []

        class FakeSocket:
            def __init__(self, name):
                self._name = name

            def getsockname(self):
                return self._name

            def close(self):
                pass

        first = FakeSocket(("127.0.0.1", 1234))
        second = FakeSocket(None)

        def fake_fromfd(fd, family, socktype):
            calls.append((fd, family, socktype))
            return first if len(calls) == 1 else second

        monkeypatch.setattr(server_socket.socket, "fromfd", fake_fromfd)
        monkeypatch.setattr(server_socket.os, "close", lambda fd: None)

        result = server_socket._socket_from_fd(9)

        assert result is second
        assert calls[0] == (9, socket.AF_UNIX, socket.SOCK_STREAM)
        assert calls[1] == (9, socket.AF_INET, socket.SOCK_STREAM)


class TestGetSystemdSocket:
    def test_returns_none_when_no_sockets(self, monkeypatch):
        monkeypatch.setattr(server_socket, "sd_listen_fds", lambda: 0)
        assert server_socket.get_systemd_socket() is None

    def test_raises_when_more_than_one_socket(self, monkeypatch):
        monkeypatch.setattr(server_socket, "sd_listen_fds", lambda: 2)
        with pytest.raises(OSError, match="only one inherited socket supported"):
            server_socket.get_systemd_socket()

    def test_returns_socket_from_fd(self, monkeypatch):
        expected = object()
        monkeypatch.setattr(server_socket, "sd_listen_fds", lambda: 1)
        monkeypatch.setattr(server_socket, "_socket_from_fd", lambda fd: expected)
        assert server_socket.get_systemd_socket() is expected
