"""Tests for dhara.storage.client."""

from __future__ import annotations

import pytest

from dhara.error import ConflictError, DruvaKeyError, ProtocolError, ReadConflictError
from dhara.storage.client import ClientStorage


class FakeSocket:
    def __init__(self, reads: list[bytes] | None = None):
        self.reads = list(reads or [])
        self.writes: list[bytes] = []
        self.closed = False

    def read(self, n: int) -> bytes:
        assert self.reads, f"unexpected read({n})"
        data = self.reads.pop(0)
        assert len(data) == n, (n, len(data))
        return data

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def close(self) -> None:
        self.closed = True


class FakeAddress:
    def __init__(self, sock: FakeSocket, label: str = "fake:1"):
        self._sock = sock
        self.label = label

    def get_connected_socket(self):
        return self._sock

    def __str__(self) -> str:
        return self.label


def _make_storage(monkeypatch, *, reads: list[bytes] | None = None, tls_config=None, tls_enabled=None, address=None):
    sock = FakeSocket(reads=reads or [])
    fake_address = FakeAddress(sock, label="example:1234")
    monkeypatch.setattr("dhara.storage.client.SocketAddress.new", lambda value: fake_address)
    monkeypatch.setattr("dhara.storage.client.StorageServer.protocol", b"ABCD")
    if tls_config is None:
        monkeypatch.setattr("dhara.storage.client.get_env_tls_config", lambda: None)
    if address is None:
        address = ("example.com", 1234)
    storage = ClientStorage(
        host=address[0],
        port=address[1],
        address=None,
        tls_config=tls_config,
        tls_enabled=tls_enabled,
    )
    return storage, sock


class TestClientStorageInit:
    def test_init_connection_error(self, monkeypatch):
        fake_address = FakeAddress(FakeSocket(), label="down:1")
        fake_address.get_connected_socket = lambda: None
        monkeypatch.setattr("dhara.storage.client.SocketAddress.new", lambda value: fake_address)
        monkeypatch.setattr("dhara.storage.client.get_env_tls_config", lambda: None)

        with pytest.raises(ConnectionError, match="Could not connect"):
            ClientStorage(host="example.com", port=1234)

    def test_init_performs_handshake(self, monkeypatch):
        storage, sock = _make_storage(monkeypatch, reads=[b"ABCD"])
        assert storage.address.label == "example:1234"
        assert sock.writes[0] == b"VABCD"
        assert storage.tls_config is None
        assert storage.tls_enabled is None or storage.tls_enabled is False

    def test_init_protocol_mismatch_raises(self, monkeypatch):
        with pytest.raises(ProtocolError, match="Protocol version mismatch"):
            _make_storage(monkeypatch, reads=[b"WXYZ"])

    def test_init_wraps_tls(self, monkeypatch):
        calls = {}

        def fake_wrap_client_socket(sock, tls_config, server_hostname=None):
            calls["server_hostname"] = server_hostname
            calls["tls_config"] = tls_config
            return sock

        monkeypatch.setattr("dhara.storage.client.wrap_client_socket", fake_wrap_client_socket)
        storage, sock = _make_storage(
            monkeypatch,
            reads=[b"ABCD"],
            tls_config=object(),
            tls_enabled=True,
        )
        assert storage.s is sock
        assert calls["server_hostname"] == "example.com"
        assert calls["tls_config"] is storage.tls_config
        assert sock.closed is False

    def test_init_auto_enables_tls_when_config_provided(self, monkeypatch):
        calls = {}

        def fake_wrap_client_socket(sock, tls_config, server_hostname=None):
            calls["server_hostname"] = server_hostname
            return sock

        monkeypatch.setattr("dhara.storage.client.wrap_client_socket", fake_wrap_client_socket)
        storage, _ = _make_storage(
            monkeypatch,
            reads=[b"ABCD"],
            tls_config=object(),
            tls_enabled=None,
        )
        assert storage.tls_enabled is True
        assert calls["server_hostname"] == "example.com"

    def test_init_wrap_failure_closes_socket(self, monkeypatch):
        def fake_wrap_client_socket(*args, **kwargs):
            raise ValueError("boom")

        monkeypatch.setattr("dhara.storage.client.wrap_client_socket", fake_wrap_client_socket)
        with pytest.raises(ConnectionError, match="TLS handshake failed: boom"):
            _make_storage(
                monkeypatch,
                reads=[b"ABCD"],
                tls_config=object(),
                tls_enabled=True,
            )


class TestClientStorageLoadResponses:
    @pytest.mark.parametrize(
        "status, expected",
        [
            (b"O", None),
            (b"I", ReadConflictError),
            (b"K", DruvaKeyError),
        ],
    )
    def test_get_load_response_statuses(self, monkeypatch, status, expected):
        storage, _ = _make_storage(monkeypatch, reads=[b"ABCD"])
        storage.s.reads = [status, b"\x00\x00\x00\x03", b"abc"]
        if expected is None:
            assert storage._get_load_response(b"oid12345") == b"abc"
        else:
            with pytest.raises(expected):
                storage._get_load_response(b"oid12345")

    def test_get_load_response_protocol_error(self, monkeypatch):
        storage, _ = _make_storage(monkeypatch, reads=[b"ABCD"])
        storage.s.reads = [b"?", b"\x00\x00\x00\x00"]
        with pytest.raises(ProtocolError):
            storage._get_load_response(b"oid12345")

    def test_load_uses_request_and_response(self, monkeypatch):
        storage, sock = _make_storage(monkeypatch, reads=[b"ABCD"])
        storage.s.reads = [b"O", b"\x00\x00\x00\x03", b"abc"]
        result = storage.load(b"oid12345")
        assert result == b"abc"
        assert sock.writes[1] == b"Loid12345"


class TestConflictError:
    def test_none_oids_message(self):
        err = ConflictError()
        assert err.oids is None
        assert str(err) == "conflicting oids not available"


class TestClientStorageOidFlow:
    def test_new_oid_batches_from_server(self, monkeypatch):
        storage, sock = _make_storage(
            monkeypatch,
            reads=[b"ABCD", b"00000001" + b"11111111"],
        )
        storage.oid_pool_size = 2

        first = storage.new_oid()
        second = storage.new_oid()

        assert first == b"00000001"
        assert second == b"11111111"
        assert sock.writes[-1] == b"M\x02"

    def test_store_records_pending_update(self, monkeypatch):
        storage, _ = _make_storage(monkeypatch, reads=[b"ABCD"])
        storage.store(b"oid12345", b"payload")
        assert storage.records[b"oid12345"] == b"payload"

    def test_end_success_writes_transaction(self, monkeypatch):
        storage, sock = _make_storage(monkeypatch, reads=[b"ABCD"])
        storage.begin()
        storage.store(b"oid12345", b"payload")
        sock.reads = [b"\x00\x00\x00\x00", b"O"]

        storage.end()

        assert storage.records == {}
        assert sock.writes[1] == b"C"
        assert sock.writes[-1].startswith(b"\x00\x00\x00")

    def test_end_with_no_records(self, monkeypatch):
        storage, sock = _make_storage(monkeypatch, reads=[b"ABCD"])
        storage.begin()
        sock.reads = [b"\x00\x00\x00\x00"]

        storage.end()

        assert storage.records == {}
        assert sock.writes[1] == b"C"

    def test_end_write_conflict_raises(self, monkeypatch):
        storage, sock = _make_storage(monkeypatch, reads=[b"ABCD"])
        storage.begin()
        storage.store(b"oid12345", b"payload")
        sock.reads = [b"\x00\x00\x00\x00", b"I"]

        with pytest.raises(Exception):
            storage.end()

    def test_end_protocol_error_raises(self, monkeypatch):
        storage, sock = _make_storage(monkeypatch, reads=[b"ABCD"])
        storage.begin()
        storage.store(b"oid12345", b"payload")
        sock.reads = [b"\x00\x00\x00\x00", b"X"]

        with pytest.raises(ProtocolError):
            storage.end()

    def test_sync_with_oids(self, monkeypatch):
        storage, sock = _make_storage(monkeypatch, reads=[b"ABCD"])
        sock.reads = [b"\x00\x00\x00\x01", b"abcdefgh"]
        assert storage.sync() == [b"abcdefgh"]

    def test_end_handles_conflict_and_restores_pool(self, monkeypatch):
        storage, sock = _make_storage(monkeypatch, reads=[b"ABCD"])
        storage.begin()
        storage.oid_pool = [b"pool-a", b"pool-b"]
        storage.transaction_new_oids = [b"new-a", b"new-b"]
        storage.records = {b"recordid": b"payload"}
        sock.reads = [b"\x00\x00\x00\x01", b"invalid1"]

        def handle_invalidations(_oids):
            raise ConflictError("conflict")

        with pytest.raises(ConflictError):
            storage.end(handle_invalidations=handle_invalidations)

        assert storage.records == {}
        assert storage.transaction_new_oids == []
        assert storage.oid_pool[-2:] == [b"new-b", b"new-a"]
        assert sock.writes[-1] == b"\x00\x00\x00\x00"

    def test_sync_and_pack_and_close(self, monkeypatch):
        storage, sock = _make_storage(monkeypatch, reads=[b"ABCD"])
        storage.s.reads = [b"\x00\x00\x00\x00", b"O"]
        assert storage.sync() == []
        storage.pack()
        storage.close()
        assert sock.closed is True

    def test_pack_protocol_error(self, monkeypatch):
        storage, _ = _make_storage(monkeypatch, reads=[b"ABCD"])
        storage.s.reads = [b"I"]
        with pytest.raises(ProtocolError):
            storage.pack()

    def test_bulk_load_yields_records(self, monkeypatch):
        storage, sock = _make_storage(monkeypatch, reads=[b"ABCD"])
        storage.s.reads = [b"O", b"\x00\x00\x00\x03", b"abc"]
        records = list(storage.bulk_load([b"oid12345"]))
        assert records == [b"abc"]
        assert sock.writes[1].startswith(b"B")
