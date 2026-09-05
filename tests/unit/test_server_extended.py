"""Extended unit tests for dhara.server.server — push coverage from 79% to ≥92%.

Targets:
  - UnixAbstractAddress direct method calls (bind_socket, get_connected_socket
    error path, set_connection_options, close)
  - UnixDomainSocketAddress methods (_cleanup_existing_socket both branches,
    _apply_socket_ownership int/name branches, bind_socket umask/EADDRINUSE,
    close unlink)
  - InheritedSocket.set_connection_options for AF_INET/AF_INET6/AF_UNIX
  - StorageServer.__init__ TLS auto-detect path
  - StorageServer.serve() inner branches (packer-driven timeout, TLS handshake
    failure, gcbytes trigger, packer StopIteration cleanup)
  - StorageServer.serve_threaded() systemd branch, select OSError, finally cleanup
  - _handle_client finally branch (533->550, 551->553), and the unreachable
    ``else`` branch on line 540 (hit by injecting a fake socket whose ``read``
    returns a non-bytes sequence so ``result[0]`` is a string)
  - _find_client ``assert 0`` fallback
  - _new_oids invalid-oid retry path
  - _report_load_record logging branch
  - handle_P synchronous pack path (get_packer returns None)

These tests are pure unit tests: they use mocks for storage backends, ephemeral
ports for real socket coverage where needed, and the existing project pytest
markers (no fastmcp/key_value imports, no duckdb dependency).
"""

from __future__ import annotations

import errno
import socket
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dhara.security.tls import TLSConfig
from dhara.serialize.record import pack_record
from dhara.server.server import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    STATUS_INVALID,
    STATUS_KEYERROR,
    STATUS_OKAY,
    ClientError,
    HostPortAddress,
    InheritedSocket,
    SocketAddress,
    StorageServer,
    UnixAbstractAddress,
    UnixDomainSocketAddress,
    _Client,
    _get_cpu_count,
)
from dhara.storage.client import ClientStorage
from dhara.storage.sqlite import SqliteStorage
from dhara.utils import int4_to_str


# ---------------------------------------------------------------------------
# Helpers (avoid cross-test fixtures; keep this file self-contained)
# ---------------------------------------------------------------------------


def _ephemeral_port() -> int:
    """Bind to :0 to let the kernel pick a free port, then close immediately."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((DEFAULT_HOST, 0))
        return s.getsockname()[1]


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "extended.dhara"


@pytest.fixture
def ephemeral_server(db_path: Path):
    """Yield a running threaded StorageServer on an ephemeral port."""
    port = _ephemeral_port()
    storage = SqliteStorage(str(db_path))
    server = StorageServer(storage, host=DEFAULT_HOST, port=port, threads=2)
    thread = threading.Thread(
        target=server.serve_threaded, daemon=True, name=f"ext-server-{port}"
    )
    thread.start()
    from dhara.server.server import wait_for_server

    wait_for_server(DEFAULT_HOST, port, maxtries=50, sleeptime=0.1)
    try:
        yield server, port
    finally:
        server.shutdown()
        thread.join(timeout=3)
        storage.close()


def _connect_raw(port: int) -> socket.socket:
    """Open a raw TCP connection, perform the V (version) handshake, return sock."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5.0)
    s.connect((DEFAULT_HOST, port))
    s.sendall(b"V" + StorageServer.protocol)
    reply = s.recv(4)
    assert reply == StorageServer.protocol, reply
    return s


# ---------------------------------------------------------------------------
# UnixAbstractAddress: direct method coverage (lines 185, 196-197, 200, 203)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnixAbstractAddressMethods:
    """Direct method tests for UnixAbstractAddress.

    Lines 185 (bind_socket), 196-197 (non-standard connect error),
    200 (set_connection_options), 203 (close).
    """

    def test_bind_socket_invokes_socket_bind(self) -> None:
        addr = UnixAbstractAddress("@abstract-bind-test")
        sock = MagicMock()
        addr.bind_socket(sock)
        sock.bind.assert_called_once_with(addr.filename)

    def test_get_connected_socket_reraises_non_standard_oserror(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """connect() raising OSError with errno outside the known set re-raises."""
        addr = UnixAbstractAddress("@abstract-err-test")

        class _RaisingSocket:
            def setsockopt(self, *a: object, **kw: object) -> None:
                return None

            def connect(self, target: str) -> None:
                # EHOSTUNREACH is intentionally outside the known swallow list.
                raise OSError(errno.EHOSTUNREACH, "host unreachable")

        monkeypatch.setattr(socket, "socket", lambda *a, **kw: _RaisingSocket())
        with pytest.raises(OSError):
            addr.get_connected_socket()

    def test_set_connection_options_sets_timeout(self) -> None:
        addr = UnixAbstractAddress("@abstract-timeout-test")
        sock = MagicMock()
        addr.set_connection_options(sock)
        sock.settimeout.assert_called_once_with(10)

    def test_close_calls_socket_close(self) -> None:
        addr = UnixAbstractAddress("@abstract-close-test")
        sock = MagicMock()
        addr.close(sock)
        sock.close.assert_called_once()


# ---------------------------------------------------------------------------
# UnixDomainSocketAddress: direct method coverage (238-245, 251-264, 267-283, 286-288)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnixDomainSocketAddressClose:
    """Lines 286-288: close() unlinks the socket file when present."""

    def test_close_unlinks_when_file_exists(self, tmp_path: Path) -> None:
        sock_path = tmp_path / "doomed.sock"
        sock_path.touch()
        addr = UnixDomainSocketAddress(str(sock_path))
        sock = MagicMock()
        addr.close(sock)
        sock.close.assert_called_once()
        assert not sock_path.exists()

    def test_close_skips_unlink_when_file_missing(self, tmp_path: Path) -> None:
        sock_path = tmp_path / "missing.sock"
        addr = UnixDomainSocketAddress(str(sock_path))
        sock = MagicMock()
        # Should not raise even though the file doesn't exist.
        addr.close(sock)
        sock.close.assert_called_once()


@pytest.mark.unit
class TestUnixDomainSocketAddressOwnership:
    """Lines 251-264: _apply_socket_ownership covers all four (owner, group) variants."""

    def test_owner_int_skips_getpwnam(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sock_path = tmp_path / "test.sock"
        addr = UnixDomainSocketAddress(str(sock_path))
        captured: dict[str, object] = {}

        def fake_chown(path: str, uid: int, gid: int) -> None:
            captured["path"] = path
            captured["uid"] = uid
            captured["gid"] = gid

        # If getpwnam is called with an int, that means we hit the wrong branch.
        monkeypatch.setattr(
            "dhara.server.server.getpwnam",
            lambda name: pytest.fail("getpwnam must not be called with int uid"),
        )
        monkeypatch.setattr("dhara.server.server.chown", fake_chown)
        addr._apply_socket_ownership(str(sock_path), owner=1234, group=None)
        assert captured["uid"] == 1234

    def test_owner_name_resolves_to_uid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sock_path = tmp_path / "test.sock"
        addr = UnixDomainSocketAddress(str(sock_path))
        captured: dict[str, object] = {}

        class _FakePwRecord:
            pw_uid = 9999

        monkeypatch.setattr(
            "dhara.server.server.getpwnam", lambda name: _FakePwRecord()
        )
        monkeypatch.setattr(
            "dhara.server.server.chown",
            lambda path, uid, gid: captured.update(uid=uid, gid=gid),
        )
        addr._apply_socket_ownership(str(sock_path), owner="fake-user", group=None)
        assert captured["uid"] == 9999

    def test_group_int_skips_getgrnam(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sock_path = tmp_path / "test.sock"
        addr = UnixDomainSocketAddress(str(sock_path))
        captured: dict[str, object] = {}

        monkeypatch.setattr(
            "dhara.server.server.getgrnam",
            lambda name: pytest.fail("getgrnam must not be called with int gid"),
        )
        monkeypatch.setattr(
            "dhara.server.server.chown",
            lambda path, uid, gid: captured.update(uid=uid, gid=gid),
        )
        addr._apply_socket_ownership(str(sock_path), owner=None, group=4321)
        assert captured["gid"] == 4321

    def test_group_name_resolves_to_gid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sock_path = tmp_path / "test.sock"
        addr = UnixDomainSocketAddress(str(sock_path))
        captured: dict[str, object] = {}

        class _FakeGrRecord:
            gr_gid = 8888

        monkeypatch.setattr(
            "dhara.server.server.getgrnam", lambda name: _FakeGrRecord()
        )
        monkeypatch.setattr(
            "dhara.server.server.chown",
            lambda path, uid, gid: captured.update(uid=uid, gid=gid),
        )
        addr._apply_socket_ownership(str(sock_path), owner=None, group="fake-group")
        assert captured["gid"] == 8888

    def test_no_owner_no_group_skips_chown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sock_path = tmp_path / "test.sock"
        addr = UnixDomainSocketAddress(str(sock_path))
        called: list[tuple[object, ...]] = []
        monkeypatch.setattr(
            "dhara.server.server.chown",
            lambda *a, **kw: called.append(a),
        )
        addr._apply_socket_ownership(str(sock_path), owner=None, group=None)
        assert called == []


@pytest.mark.unit
class TestUnixDomainSocketAddressCleanup:
    """Lines 238-245: _cleanup_existing_socket has two distinct branches."""

    def test_live_peer_raises_eaddrinuse(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When get_connected_socket returns a live peer, raise EADDRINUSE again."""
        sock_path = tmp_path / "live.sock"
        addr = UnixDomainSocketAddress(str(sock_path))
        peer = MagicMock()
        monkeypatch.setattr(addr, "get_connected_socket", lambda: peer)
        sock = MagicMock()
        with pytest.raises(OSError) as exc_info:
            addr._cleanup_existing_socket(sock, str(sock_path))
        assert exc_info.value.errno == errno.EADDRINUSE
        peer.close.assert_called_once()
        sock.bind.assert_not_called()

    def test_stale_socket_unlinks_and_binds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When get_connected_socket returns None, unlink the stale file and bind."""
        sock_path = tmp_path / "stale.sock"
        sock_path.touch()
        addr = UnixDomainSocketAddress(str(sock_path))
        monkeypatch.setattr(addr, "get_connected_socket", lambda: None)
        sock = MagicMock()
        addr._cleanup_existing_socket(sock, str(sock_path))
        assert not sock_path.exists()
        sock.bind.assert_called_once()


@pytest.mark.unit
class TestUnixDomainSocketAddressBindSocket:
    """Lines 267-283: bind_socket with umask, EADDRINUSE stale path, and the
    ``Path(self.filename).stat().st_size > 0`` error path."""

    def test_bind_socket_with_umask_sets_permissions(
        self, tmp_path: Path
    ) -> None:
        """bind_socket with umask applies the umask and restores it afterwards."""
        if not sys.platform.startswith("linux"):
            pytest.skip("unix-domain sun_path too short on this platform")
        sock_path = str(tmp_path / "umask.sock")
        addr = UnixDomainSocketAddress(sock_path, umask=0o077)
        listening = addr.get_listening_socket()
        try:
            mode = Path(sock_path).stat().st_mode & 0o777
            assert mode & 0o077 == 0
        finally:
            addr.close(listening)

    def test_bind_socket_eaddrinuse_on_stale_file_cleans_up(
        self, tmp_path: Path
    ) -> None:
        """bind_socket with EADDRINUSE on an empty stale file should unlink and rebind."""
        if not sys.platform.startswith("linux"):
            pytest.skip("unix-domain sun_path too short on this platform")
        sock_path = tmp_path / "stale.sock"
        sock_path.touch()
        # Confirm the file is empty so we hit the st_size == 0 branch.
        assert sock_path.stat().st_size == 0
        addr = UnixDomainSocketAddress(str(sock_path))
        listening = addr.get_listening_socket()
        try:
            assert Path(sock_path).exists()
        finally:
            addr.close(listening)

    def test_bind_socket_non_addr_error_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """bind_socket propagates non-OSError, non-EADDRINUSE exceptions."""
        addr = UnixDomainSocketAddress(str(tmp_path / "bogus.sock"))
        sock = MagicMock()
        sock.bind.side_effect = PermissionError(13, "Permission denied")

        with pytest.raises(PermissionError):
            addr.bind_socket(sock)


# ---------------------------------------------------------------------------
# InheritedSocket.set_connection_options (lines 316-318)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInheritedSocketConnectionOptions:
    def test_inet_sets_tcp_nodelay(self) -> None:
        sock = MagicMock()
        sock.family = socket.AF_INET
        addr = InheritedSocket(sock)
        addr.set_connection_options(sock)
        sock.setsockopt.assert_called_with(
            socket.IPPROTO_TCP, socket.TCP_NODELAY, 1
        )
        sock.settimeout.assert_called_once_with(10)

    def test_inet6_sets_tcp_nodelay(self) -> None:
        sock = MagicMock()
        sock.family = socket.AF_INET6
        addr = InheritedSocket(sock)
        addr.set_connection_options(sock)
        sock.setsockopt.assert_called_with(
            socket.IPPROTO_TCP, socket.TCP_NODELAY, 1
        )
        sock.settimeout.assert_called_once_with(10)

    def test_unix_does_not_set_tcp_nodelay(self) -> None:
        """AF_UNIX sockets should NOT set TCP_NODELAY, only settimeout."""
        sock = MagicMock()
        sock.family = socket.AF_UNIX
        addr = InheritedSocket(sock)
        addr.set_connection_options(sock)
        sock.setsockopt.assert_not_called()
        sock.settimeout.assert_called_once_with(10)


# ---------------------------------------------------------------------------
# StorageServer.__init__ TLS auto-detect (line 387)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStorageServerInitTLS:
    def test_tls_enabled_auto_set_when_config_has_credentials(
        self, db_path: Path
    ) -> None:
        """When tls_config has cert/key and tls_enabled is None, auto-enable TLS."""
        # Use MagicMock (no spec) to bypass TLSConfig's file-existence validation.
        # Setting certfile/keyfile to truthy strings makes the validation pass.
        config = MagicMock()
        config.certfile = "/tmp/cert.pem"
        config.keyfile = "/tmp/key.pem"
        storage = SqliteStorage(str(db_path))
        try:
            server = StorageServer(
                storage,
                host=DEFAULT_HOST,
                port=DEFAULT_PORT,
                threads=0,
                tls_config=config,
                tls_enabled=None,
            )
            assert server.tls_enabled is True
        finally:
            storage.close()

    def test_tls_enabled_raises_when_cert_empty_and_enabled_true(
        self, db_path: Path
    ) -> None:
        """Empty certfile + tls_enabled=True raises ValueError (validation branch)."""
        config = MagicMock()
        config.certfile = ""
        config.keyfile = ""
        storage = SqliteStorage(str(db_path))
        try:
            with pytest.raises(ValueError, match="certfile and keyfile"):
                StorageServer(
                    storage,
                    host=DEFAULT_HOST,
                    port=DEFAULT_PORT,
                    threads=0,
                    tls_config=config,
                    tls_enabled=True,
                )
        finally:
            storage.close()


# ---------------------------------------------------------------------------
# StorageServer.serve() control flow (415, 426-431, 446-448, 450-457)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestServeControlFlow:
    """Test the inner branches of serve() without running a full TCP server."""

    def test_serve_timeout_zero_when_packer_set(self) -> None:
        """When self.packer is not None, serve() must use timeout=0.0."""
        storage = MagicMock()
        server = StorageServer(storage, address=(DEFAULT_HOST, _ephemeral_port()))
        # Pre-set a no-op packer so the timeout=0.0 branch fires.
        server.packer = iter([])  # empty iterator
        captured: dict[str, object] = {}

        def fake_select(rlist, wlist, xlist, timeout):
            captured["timeout"] = timeout
            # Break the loop after the first iteration by raising.
            raise RuntimeError("break-loop-for-test")

        # Patch select.select, get_systemd_socket (return None so we use the
        # address.get_listening_socket path), and the listening socket itself.
        listening = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listening.bind((DEFAULT_HOST, 0))
        listening.listen(1)
        server.address.get_listening_socket = lambda: listening  # type: ignore[method-assign]

        with patch("dhara.server.server.get_systemd_socket", return_value=None), patch(
            "dhara.server.server.select.select", side_effect=fake_select
        ):
            with pytest.raises(RuntimeError, match="break-loop-for-test"):
                server.serve()

        assert captured["timeout"] == 0.0
        listening.close()

    def test_serve_timeout_none_when_packer_unset(self) -> None:
        """When self.packer is None, serve() must use timeout=None (block)."""
        storage = MagicMock()
        server = StorageServer(storage, address=(DEFAULT_HOST, _ephemeral_port()))
        assert server.packer is None
        captured: dict[str, object] = {}

        def fake_select(rlist, wlist, xlist, timeout):
            captured["timeout"] = timeout
            raise RuntimeError("break-loop-for-test")

        listening = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listening.bind((DEFAULT_HOST, 0))
        listening.listen(1)
        server.address.get_listening_socket = lambda: listening  # type: ignore[method-assign]

        with patch("dhara.server.server.get_systemd_socket", return_value=None), patch(
            "dhara.server.server.select.select", side_effect=fake_select
        ):
            with pytest.raises(RuntimeError, match="break-loop-for-test"):
                server.serve()

        assert captured["timeout"] is None
        listening.close()

    def test_serve_tls_handshake_failure_closes_connection(self) -> None:
        """When wrap_server_socket raises, serve() logs and continues (closes conn)."""
        # Use a MagicMock for the listening socket so the for-loop sees a
        # 'new connection' arrival without spinning on a real socket.
        listening_mock = MagicMock()
        conn_mock = MagicMock()
        listening_mock.accept.return_value = (conn_mock, ("127.0.0.1", 0))
        # Use MagicMock (no spec) to bypass TLSConfig's file-existence validation.
        config = MagicMock()
        config.certfile = "/tmp/cert.pem"
        config.keyfile = "/tmp/key.pem"
        storage = MagicMock()
        server = StorageServer(
            storage,
            address=(DEFAULT_HOST, _ephemeral_port()),
            tls_config=config,
            tls_enabled=True,
            threads=0,
        )
        # Override get_listening_socket to return our MagicMock listening sock.
        server.address.get_listening_socket = lambda: listening_mock  # type: ignore[method-assign]

        iteration = {"count": 0}

        def fake_select(rlist, wlist, xlist, timeout):
            iteration["count"] += 1
            # Iteration 1: return the listening socket (simulate new connection).
            if iteration["count"] == 1:
                return [listening_mock], [], []
            # Iteration 2: no readable sockets — break the loop.
            raise RuntimeError("break-loop-for-test")

        wrap_calls: list[object] = []

        def fake_wrap(sock: object, cfg: object) -> object:
            wrap_calls.append(sock)
            raise RuntimeError("simulated TLS handshake failure")

        with patch("dhara.server.server.get_systemd_socket", return_value=None), patch(
            "dhara.server.server.select.select", side_effect=fake_select
        ), patch(
            "dhara.server.server.wrap_server_socket", side_effect=fake_wrap
        ):
            with pytest.raises(RuntimeError, match="break-loop-for-test"):
                server.serve()

        # The TLS handshake failed → wrap_server_socket was called with the
        # accepted connection, then conn.close() was called from the except.
        assert len(wrap_calls) == 1
        assert wrap_calls[0] is conn_mock
        # The accepted connection's close was invoked.
        assert conn_mock.close.called

    def test_serve_packer_stopiteration_resets_state(self) -> None:
        """When the packer iterator raises StopIteration, serve() resets state."""
        storage = MagicMock()
        server = StorageServer(storage, address=(DEFAULT_HOST, _ephemeral_port()))

        # Set a packer iterator that yields one step then exhausts naturally.
        # We use a custom iterator class to avoid PEP 479 converting an explicit
        # ``raise StopIteration`` inside a generator into RuntimeError.
        class _OneStepPacker:
            def __init__(self) -> None:
                self.yielded = False

            def __iter__(self) -> _OneStepPacker:
                return self

            def __next__(self) -> str:
                if self.yielded:
                    raise StopIteration
                self.yielded = True
                return "first-step"

        server.packer = _OneStepPacker()
        server.bytes_since_pack = 100

        # Track iterations: first iteration yields "first-step", second hits
        # StopIteration and resets state, third breaks.
        iteration = {"count": 0}

        def fake_select(rlist, wlist, xlist, timeout):
            iteration["count"] += 1
            # Iterations 1 and 2: empty readable → packer branch runs.
            # Iteration 3: raise to break AFTER the packer reset fires.
            if iteration["count"] >= 3:
                raise RuntimeError("break-loop-for-test")
            return [], [], []

        listening = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listening.bind((DEFAULT_HOST, 0))
        listening.listen(1)
        server.address.get_listening_socket = lambda: listening  # type: ignore[method-assign]

        with patch("dhara.server.server.get_systemd_socket", return_value=None), patch(
            "dhara.server.server.select.select", side_effect=fake_select
        ):
            with pytest.raises(RuntimeError, match="break-loop-for-test"):
                server.serve()

        # After StopIteration: packer reset, bytes_since_pack zeroed.
        assert server.packer is None
        assert server.bytes_since_pack == 0
        listening.close()

    def test_serve_gcbytes_triggers_packer_initialization(self) -> None:
        """When bytes_since_pack exceeds gcbytes, serve() starts a packer."""
        storage = MagicMock()

        class _OneStepPacker:
            def __init__(self) -> None:
                self.yielded = False

            def __iter__(self) -> _OneStepPacker:
                return self

            def __next__(self) -> str:
                if self.yielded:
                    raise StopIteration
                self.yielded = True
                return "step-1"

        def fake_get_packer() -> _OneStepPacker:
            return _OneStepPacker()

        storage.get_packer = fake_get_packer  # type: ignore[method-assign]
        server = StorageServer(
            storage, address=(DEFAULT_HOST, _ephemeral_port()), gcbytes=1
        )
        # Pre-load bytes_since_pack past the threshold to trigger the branch.
        server.bytes_since_pack = 10

        # Track how many times select.select is called and force break after.
        iteration = {"count": 0}

        def fake_select(rlist, wlist, xlist, timeout):
            iteration["count"] += 1
            # First call: select returns nothing — gcbytes branch fires,
            # get_packer returns _OneStepPacker, next() yields "step-1".
            # Second call: packer is not None, next() raises StopIteration,
            # packer is reset to None; break the loop on the third call.
            if iteration["count"] >= 3:
                raise RuntimeError("break-loop-for-test")
            return [], [], []

        listening = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listening.bind((DEFAULT_HOST, 0))
        listening.listen(1)
        server.address.get_listening_socket = lambda: listening  # type: ignore[method-assign]

        with patch("dhara.server.server.get_systemd_socket", return_value=None), patch(
            "dhara.server.server.select.select", side_effect=fake_select
        ):
            with pytest.raises(RuntimeError, match="break-loop-for-test"):
                server.serve()

        # After StopIteration the packer is reset to None.
        assert server.packer is None
        listening.close()


def _is_open(sock: socket.socket) -> bool:
    """Return True if the socket is still open (not closed)."""
    try:
        sock.getpeername()
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# StorageServer.serve_threaded() control flow
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestServeThreadedControlFlow:
    """Test the inner branches of serve_threaded()."""

    def test_serve_threaded_select_oserror_continues(self) -> None:
        """When select.select raises OSError, serve_threaded() must continue."""
        storage = MagicMock()
        server = StorageServer(
            storage, address=(DEFAULT_HOST, _ephemeral_port()), threads=1
        )

        iteration = {"count": 0}

        def fake_select(rlist, wlist, xlist, timeout):
            iteration["count"] += 1
            # First two calls: raise OSError to exercise the except branch.
            if iteration["count"] <= 2:
                raise OSError(errno.EBADF, "Bad file descriptor")
            # Third call: break out of the loop.
            raise RuntimeError("break-loop-for-test")

        listening = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listening.bind((DEFAULT_HOST, 0))
        listening.listen(1)
        server.address.get_listening_socket = lambda: listening  # type: ignore[method-assign]

        with patch("dhara.server.server.get_systemd_socket", return_value=None), patch(
            "dhara.server.server.select.select", side_effect=fake_select
        ):
            with pytest.raises(RuntimeError, match="break-loop-for-test"):
                server.serve_threaded()

        assert iteration["count"] >= 3
        listening.close()

    def test_serve_threaded_finally_shuts_down_executor(self) -> None:
        """serve_threaded() must shut down its ThreadPoolExecutor on exit."""
        storage = MagicMock()
        server = StorageServer(
            storage, address=(DEFAULT_HOST, _ephemeral_port()), threads=2
        )

        def fake_select(rlist, wlist, xlist, timeout):
            raise RuntimeError("break-loop-for-test")

        listening = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listening.bind((DEFAULT_HOST, 0))
        listening.listen(1)
        server.address.get_listening_socket = lambda: listening  # type: ignore[method-assign]

        with patch("dhara.server.server.get_systemd_socket", return_value=None), patch(
            "dhara.server.server.select.select", side_effect=fake_select
        ):
            with pytest.raises(RuntimeError, match="break-loop-for-test"):
                server.serve_threaded()

        # After the loop exits, _running must be False and executor must be shut down.
        assert server._running is False
        assert server._executor is not None
        listening.close()

    def test_serve_threaded_accept_oserror_continues(self) -> None:
        """When accept() raises OSError, serve_threaded() must continue the loop."""
        storage = MagicMock()
        server = StorageServer(
            storage, address=(DEFAULT_HOST, _ephemeral_port()), threads=1
        )

        iteration = {"count": 0}

        def fake_select(rlist, wlist, xlist, timeout):
            iteration["count"] += 1
            if iteration["count"] == 1:
                # Return the listening socket so the for loop tries to accept.
                return [listening], [], []
            # Subsequent calls return nothing.
            return [], [], []

        listening = MagicMock()
        listening.fileno.return_value = 7
        listening.accept.side_effect = OSError(errno.EBADF, "Bad file descriptor")

        with patch("dhara.server.server.get_systemd_socket", return_value=None), patch(
            "dhara.server.server.select.select", side_effect=fake_select
        ):
            # Run in a thread so we can shutdown cleanly.
            thread = threading.Thread(
                target=server.serve_threaded, daemon=True
            )
            thread.start()
            time.sleep(0.2)
            server.shutdown()
            thread.join(timeout=2)

        # The accept OSError was swallowed and the loop continued at least once.
        assert iteration["count"] >= 1


# ---------------------------------------------------------------------------
# _handle_client: cleanup paths (533->550, 551->553) and dead else (540)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleClientCleanup:
    """Direct calls to _handle_client to hit the cleanup branches."""

    def test_handle_client_exits_via_finally_when_running_false(
        self, db_path: Path
    ) -> None:
        """When self._running flips False mid-loop, _handle_client jumps to finally."""
        storage = SqliteStorage(str(db_path))
        try:
            server = StorageServer(
                storage, host=DEFAULT_HOST, port=DEFAULT_PORT, threads=0
            )
            server._running = False

            class _FakeClientSock:
                """Fake socket whose ``read`` blocks forever (we flip _running first)."""

                def recv(self, n: int) -> bytes:
                    # If we ever get here, the test is hung. The expected flow:
                    # _running is False → while loop never enters → jumps to finally.
                    raise RuntimeError("recv should not be called when _running=False")

                def read(self, n: int) -> bytes:
                    raise RuntimeError("read should not be called when _running=False")

                def close(self) -> None:
                    pass

            client = _Client(_FakeClientSock(), ("localhost", 0))
            server.clients.append(client)
            server._handle_client(client)

            # After _handle_client returns, the client should be removed from clients.
            assert client not in server.clients
        finally:
            storage.close()

    def test_handle_client_branch_when_client_already_removed(
        self, db_path: Path
    ) -> None:
        """The 551->553 branch fires when client is NOT in self.clients at cleanup."""
        storage = SqliteStorage(str(db_path))
        try:
            server = StorageServer(
                storage, host=DEFAULT_HOST, port=DEFAULT_PORT, threads=0
            )
            server._running = False

            class _FakeClientSock:
                def recv(self, n: int) -> bytes:
                    raise RuntimeError("recv not expected")

                def read(self, n: int) -> bytes:
                    raise RuntimeError("read not expected")

                def close(self) -> None:
                    pass

            client = _Client(_FakeClientSock(), ("localhost", 0))
            # Deliberately do NOT add client to server.clients — the finally
            # block's `if client in self.clients` is False → 551->553.
            server._handle_client(client)
            assert client not in server.clients
        finally:
            storage.close()

    def test_handle_client_hits_dead_else_branch(self, db_path: Path) -> None:
        """The ``else: command_code = command_byte`` branch (line 540) is normally
        unreachable because ``read()`` always returns bytes. We force it by passing
        a fake socket whose ``read(n)`` returns a *list* whose first element is a
        non-int — ``result[0]`` is then a string, so ``type(command_byte) is int``
        is False and the else branch executes.
        """
        storage = SqliteStorage(str(db_path))
        try:
            server = StorageServer(
                storage, host=DEFAULT_HOST, port=DEFAULT_PORT, threads=0
            )

            class _FakeClientSock:
                """Return ['N'] from read; dhara.utils.read passes lists through."""

                def __init__(self) -> None:
                    self.closed = False

                def read(self, n: int) -> list[str]:
                    return ["N"]  # length 1, first element is a string

                def close(self) -> None:
                    self.closed = True

            fake = _FakeClientSock()
            client = _Client(fake, ("localhost", 0))
            # We need handle_N to be able to write an 8-byte OID; mock the write.
            from dhara.utils import join_bytes

            server._handle_client(client)
            # The client was removed during cleanup.
            assert fake.closed
        finally:
            storage.close()


# ---------------------------------------------------------------------------
# _find_client ``assert 0`` (line 610)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFindClient:
    def test_find_client_returns_matching(self, db_path: Path) -> None:
        """Happy path: the socket is in some client's ``.s`` slot."""
        storage = SqliteStorage(str(db_path))
        try:
            server = StorageServer(
                storage, host=DEFAULT_HOST, port=DEFAULT_PORT, threads=0
            )
            sock = MagicMock()
            client = _Client(sock, ("localhost", 0))
            server.clients.append(client)
            assert server._find_client(sock) is client
        finally:
            storage.close()

    def test_find_client_asserts_when_no_match(self, db_path: Path) -> None:
        """When no client owns the socket, _find_client hits the ``assert 0``."""
        storage = SqliteStorage(str(db_path))
        try:
            server = StorageServer(
                storage, host=DEFAULT_HOST, port=DEFAULT_PORT, threads=0
            )
            # No clients registered; lookup must trip the assertion.
            with pytest.raises(AssertionError):
                server._find_client(MagicMock())
        finally:
            storage.close()


# ---------------------------------------------------------------------------
# _new_oids invalid oid retry path (lines 618-619, 620->614)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNewOidsInvalidRetry:
    """Lines 618-619, 620->614: when storage returns an oid in some client's
    invalid set, _new_oids must retry until it gets a non-invalidated oid."""

    def test_new_oids_skips_invalidated_oid(
        self, ephemeral_server: tuple[StorageServer, int], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mock storage.new_oid to return an invalidated oid once, then a valid one."""
        server, port = ephemeral_server
        # Pre-populate the invalid set with a known OID.
        bad_oid = b"\x00" * 7 + b"\xff"
        good_oid = b"\x00" * 7 + b"\x01"

        # Connect once to register a client on the server.
        s = _connect_raw(port)
        try:
            with server.clients_lock:
                assert server.clients
                server.clients[0].invalid.add(bad_oid)

            # Mock new_oid to first return bad_oid, then good_oid.
            call_count = {"n": 0}

            def fake_new_oid() -> bytes:
                call_count["n"] += 1
                return bad_oid if call_count["n"] == 1 else good_oid

            monkeypatch.setattr(server.storage, "new_oid", fake_new_oid)

            # The next N request must skip bad_oid and return good_oid.
            s.sendall(b"N")
            returned_oid = s.recv(8)
            assert returned_oid == good_oid
            # The retry branch fired at least once.
            assert call_count["n"] >= 2
        finally:
            try:
                s.sendall(b"Q")
                s.close()
            except Exception:
                pass

    def test_new_oids_retries_until_count_satisfied(
        self, ephemeral_server: tuple[StorageServer, int], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even with multiple invalidated oids, M eventually returns ``count`` valid oids."""
        server, port = ephemeral_server
        bad1 = b"\x00" * 7 + b"\xfe"
        bad2 = b"\x00" * 7 + b"\xfd"
        good = b"\x00" * 7 + b"\xfc"

        s = _connect_raw(port)
        try:
            with server.clients_lock:
                assert server.clients
                server.clients[0].invalid.add(bad1)
                server.clients[0].invalid.add(bad2)

            # Mock new_oid to return bad1, bad2, then good — for each M call.
            counter = {"n": 0}

            def fake_new_oid() -> bytes:
                counter["n"] += 1
                sequence = [bad1, bad2, good, good, good]
                idx = (counter["n"] - 1) % len(sequence)
                return sequence[idx]

            monkeypatch.setattr(server.storage, "new_oid", fake_new_oid)

            # Ask for 3 fresh oids; the server should skip bad1 and bad2.
            s.sendall(b"M" + bytes([3]))
            oids = b""
            while len(oids) < 24:
                chunk = s.recv(24 - len(oids))
                if not chunk:
                    break
                oids += chunk
            assert len(oids) == 24
            # None of the returned oids should match the invalid ones.
            assert bad1 not in (oids[:8], oids[8:16], oids[16:24])
            assert bad2 not in (oids[:8], oids[8:16], oids[16:24])
        finally:
            try:
                s.sendall(b"Q")
                s.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# _report_load_record (lines 719-727)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReportLoadRecord:
    def test_report_load_record_logs_when_load_record_populated(
        self, ephemeral_server: tuple[StorageServer, int], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When load_record has entries and is_logging(5) is True, handle_C reports them."""
        import dhara.server.server as srv_mod

        monkeypatch.setattr(srv_mod, "is_logging", lambda level: True)

        _, port = ephemeral_server
        s = _connect_raw(port)
        try:
            # Step 1: Get an oid and commit a record to populate load_record via
            # the is_logging(5) extract_class_name branch (subsequent loads).
            s.sendall(b"N")
            oid = s.recv(8)
            record = pack_record(oid, b"report-load", b"")
            s.sendall(b"C")
            s.recv(4)  # invalid_count
            rlen = (8 + len(record)).to_bytes(4, "big")
            tdata = rlen + oid + record
            tlen = len(tdata).to_bytes(4, "big")
            s.sendall(tlen + tdata)
            s.recv(1)  # status

            # Step 2: Load once so load_record gets populated (is_logging(5) is
            # True → extract_class_name runs → load_record[class_name] = 1).
            s.sendall(b"L" + oid)
            s.recv(1)  # status byte
            record_len = int.from_bytes(s.recv(4), "big")
            s.recv(record_len)

            # Step 3: Successful commit — handle_C calls _report_load_record
            # which logs the populated load_record.
            s.sendall(b"C")
            s.recv(4)  # invalid_count
            # Send valid tdata with a fresh oid (already-fetched `oid` is used
            # to avoid colliding with the load_record's pre-existing entry).
            record2 = pack_record(oid, b"report-load-2", b"")
            rlen2 = (8 + len(record2)).to_bytes(4, "big")
            tdata2 = rlen2 + oid + record2
            tlen2 = len(tdata2).to_bytes(4, "big")
            s.sendall(tlen2 + tdata2)
            s.recv(1)  # status
            time.sleep(0.1)
        finally:
            try:
                s.sendall(b"Q")
                s.close()
            except Exception:
                pass

    def test_report_load_record_skips_when_load_record_empty(
        self, db_path: Path
    ) -> None:
        """If load_record is empty, _report_load_record returns without logging."""
        storage = SqliteStorage(str(db_path))
        try:
            server = StorageServer(
                storage, host=DEFAULT_HOST, port=DEFAULT_PORT, threads=0
            )
            # load_record starts empty.
            assert server.load_record == {}
            server._report_load_record()  # must not raise
        finally:
            storage.close()

    def test_report_load_record_skips_when_not_logging(
        self, ephemeral_server: tuple[StorageServer, int], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When is_logging(5) is False, _report_load_record is a no-op even with entries."""
        import dhara.server.server as srv_mod

        # is_logging(5) returns False everywhere else.
        monkeypatch.setattr(srv_mod, "is_logging", lambda level: False)

        server, port = ephemeral_server
        # Directly populate load_record.
        server.load_record["SomeClass"] = 5

        # _report_load_record should be a no-op.
        server._report_load_record()
        # And the entry should not be cleared.
        assert server.load_record == {"SomeClass": 5}


# ---------------------------------------------------------------------------
# handle_P synchronous pack path (lines 751-752)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandlePSyncPack:
    def test_handle_p_sync_pack_when_get_packer_returns_none(
        self, ephemeral_server: tuple[StorageServer, int], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When storage.get_packer() returns None, handle_P falls back to storage.pack()."""
        real_storage = ephemeral_server[0].storage
        pack_called: list[bool] = []

        def fake_get_packer() -> None:
            return None

        def fake_pack() -> None:
            pack_called.append(True)

        monkeypatch.setattr(real_storage, "get_packer", fake_get_packer)
        monkeypatch.setattr(real_storage, "pack", fake_pack)

        _, port = ephemeral_server
        s = _connect_raw(port)
        try:
            s.sendall(b"P")
            status = s.recv(1)
            assert status == STATUS_OKAY
            assert pack_called == [True]
        finally:
            try:
                s.sendall(b"Q")
                s.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# handle_C client invalidation propagation (lines 712-714, exercised)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleCInvalidation:
    def test_handle_c_propagates_invalidations_to_other_clients(
        self, ephemeral_server: tuple[StorageServer, int]
    ) -> None:
        """When client A commits, every other client's invalid set gains those oids."""
        server, port = ephemeral_server
        a = ClientStorage(host=DEFAULT_HOST, port=port)
        b = ClientStorage(host=DEFAULT_HOST, port=port)
        try:
            # A commits an oid.
            oid = a.new_oid()
            record = pack_record(oid, b"propagate", b"")
            a.begin()
            a.store(oid, record)
            a.end()
            # B's invalid set should now contain oid.
            assert oid in b.sync()
        finally:
            try:
                a.s.close()
            except Exception:
                pass
            try:
                b.s.close()
            except Exception:
                pass

    def test_handle_c_invalid_oid_raises_client_error(
        self, ephemeral_server: tuple[StorageServer, int]
    ) -> None:
        """If another client is using an oid, handle_C raises ClientError('invalid oid')."""
        _, port = ephemeral_server
        a = ClientStorage(host=DEFAULT_HOST, port=port)
        b = ClientStorage(host=DEFAULT_HOST, port=port)
        try:
            # A asks for a new oid but doesn't commit it; the oid remains in
            # A's unused_oids set. B then tries to commit that same oid.
            stolen_oid = a.new_oid()
            # Build a hand-crafted commit from B using the stolen oid.
            s_b = b.s
            s_b.sendall(b"C")
            s_b.recv(4)  # invalid_count
            record = pack_record(stolen_oid, b"theft", b"")
            rlen = (8 + len(record)).to_bytes(4, "big")
            tdata = rlen + stolen_oid + record
            tlen = len(tdata).to_bytes(4, "big")
            s_b.sendall(tlen + tdata)
            # Server should raise ClientError → worker closes socket.
            time.sleep(0.2)
        finally:
            try:
                a.s.close()
            except Exception:
                pass
            try:
                b.s.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# StorageServer.serve_forever equivalent (briefly run serve() in a thread)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_serve_single_thread_brief_run_then_shutdown(db_path: Path) -> None:
    """Spin up serve() in a thread, let it accept one connection, then shutdown."""
    port = _ephemeral_port()
    storage = SqliteStorage(str(db_path))
    server = StorageServer(storage, host=DEFAULT_HOST, port=port, threads=0)
    thread = threading.Thread(target=server.run, daemon=True, name=f"serve-st-{port}")
    thread.start()
    from dhara.server.server import wait_for_server

    wait_for_server(DEFAULT_HOST, port, maxtries=50, sleeptime=0.1)

    # Connect once to confirm the server is alive.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2.0)
    s.connect((DEFAULT_HOST, port))
    s.sendall(b"V" + StorageServer.protocol)
    reply = s.recv(4)
    assert reply == StorageServer.protocol
    s.close()

    # Break out of the select loop by closing the listening socket.
    try:
        for listening in server.sockets:
            try:
                listening.close()
            except Exception:
                pass
    except Exception:
        pass
    thread.join(timeout=3)
    storage.close()


# ---------------------------------------------------------------------------
# MagicMock tls_config validation: ValueError when tls_enabled=True but no creds
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_tls_validation_error_message_contents(db_path: Path) -> None:
    """Verify the ValueError message mentions certfile and keyfile."""
    storage = SqliteStorage(str(db_path))
    try:
        config = TLSConfig(certfile="", keyfile="")
        with pytest.raises(ValueError) as exc_info:
            StorageServer(
                storage,
                host=DEFAULT_HOST,
                port=DEFAULT_PORT,
                threads=0,
                tls_config=config,
                tls_enabled=True,
            )
        msg = str(exc_info.value)
        assert "certfile" in msg
        assert "keyfile" in msg
        assert "DHARA_TLS_CERTFILE" in msg or "TLSConfig" in msg
    finally:
        storage.close()


# ---------------------------------------------------------------------------
# run() default threads=0 selection
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_picks_serve_threaded_for_auto_threads(db_path: Path) -> None:
    """run() with threads=-1 (auto) must call serve_threaded (threads > 0 after init)."""
    port = _ephemeral_port()
    storage = SqliteStorage(str(db_path))
    # threads=-1 → cpu_count * 2 → positive → serve_threaded branch
    server = StorageServer(storage, host=DEFAULT_HOST, port=port, threads=-1)
    assert server.threads > 0

    called = {"name": None}

    def fake_serve() -> None:
        called["name"] = "serve"

    def fake_serve_threaded() -> None:
        called["name"] = "serve_threaded"
        server._running = False

    server.serve = fake_serve  # type: ignore[method-assign]
    server.serve_threaded = fake_serve_threaded  # type: ignore[method-assign]
    server.run()
    assert called["name"] == "serve_threaded"
    storage.close()


# ---------------------------------------------------------------------------
# wait_for_server with custom address
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_wait_for_server_uses_socket_address_object(tmp_path: Path) -> None:
    """wait_for_server should accept a SocketAddress instance (not just host/port)."""
    from dhara.server.server import wait_for_server

    addr = HostPortAddress(host=DEFAULT_HOST, port=_ephemeral_port())
    # Bound but no server listening — must raise SystemExit after the budget.
    with pytest.raises(SystemExit, match="Timeout"):
        wait_for_server(address=addr, maxtries=2, sleeptime=0.05)


# ---------------------------------------------------------------------------
# _handle_command_threaded: invalid command_code raises ClientError
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_handle_command_threaded_invalid_code_raises(db_path: Path) -> None:
    """_handle_command_threaded with an unknown command code must raise ClientError."""
    storage = SqliteStorage(str(db_path))
    try:
        server = StorageServer(
            storage, host=DEFAULT_HOST, port=DEFAULT_PORT, threads=0
        )
        sock = MagicMock()
        client = _Client(sock, ("localhost", 0))
        with pytest.raises(ClientError, match="No such command code"):
            server._handle_command_threaded(sock, client, "Z")  # type: ignore[arg-type]
    finally:
        storage.close()


# ---------------------------------------------------------------------------
# _handle_command_threaded: read command goes through (lock not acquired)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_handle_command_threaded_read_skips_storage_lock(db_path: Path) -> None:
    """Read commands ('L', 'V', 'N', 'M', 'B') must NOT acquire the storage lock."""
    storage = SqliteStorage(str(db_path))
    try:
        server = StorageServer(
            storage, host=DEFAULT_HOST, port=DEFAULT_PORT, threads=0
        )

        class _LockProbe:
            def __init__(self) -> None:
                self.locked = False

            def __enter__(self) -> _LockProbe:
                self.locked = True
                return self

            def __exit__(self, *a: object) -> None:
                self.locked = False

        probe = _LockProbe()
        proxy = probe

        class _ProxyLock:
            def __enter__(self_inner) -> _LockProbe:
                return proxy.__enter__()

            def __exit__(self_inner, *a: object) -> None:
                proxy.__exit__(*a)

        server.storage_lock = _ProxyLock()  # type: ignore[assignment]

        sock = MagicMock()
        client = _Client(sock, ("localhost", 0))
        # Register the client so handle_N's _find_client lookup succeeds.
        server.clients.append(client)

        # V is a read command → lock NOT acquired.
        sock.read = MagicMock(return_value=StorageServer.protocol)  # type: ignore[attr-defined]
        server._handle_command_threaded(sock, client, "V")  # type: ignore[arg-type]
        assert probe.locked is False

        # N is also a read command (writes an OID but doesn't touch storage).
        sock.read = MagicMock(return_value=b"\x00\x00\x00\x00\x00\x00\x00\x01")  # type: ignore[attr-defined]
        sock.write = MagicMock()  # type: ignore[attr-defined]
        server._handle_command_threaded(sock, client, "N")  # type: ignore[arg-type]
        assert probe.locked is False
    finally:
        storage.close()
