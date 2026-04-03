"""
$URL$
$Id$

ClientStorage for network-based dhara storage.

This implementation supports TLS/SSL encryption for secure communication
over untrusted networks. Use tls_config parameter to enable encryption.
"""

from dhara.error import (
    ConflictError,
    DruvaKeyError,
    ProtocolError,
    ReadConflictError,
    WriteConflictError,
)
from dhara.security.tls import (
    TLSConfig,
    get_env_tls_config,
    wrap_client_socket,
)
from dhara.serialize.adapter import split_oids
from dhara.server.server import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    STATUS_INVALID,
    STATUS_KEYERROR,
    STATUS_OKAY,
    SocketAddress,
    StorageServer,
)
from dhara.storage.base import Storage
from dhara.utils import (
    as_bytes,
    int4_to_str,
    iteritems,
    join_bytes,
    read,
    read_int4,
    write,
    write_all,
    write_int4,
    write_int4_str,
)


class ClientStorage(Storage):
    def __init__(
        self,
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        address=None,
        tls_config: TLSConfig | None = None,
        tls_enabled: bool | None = None,
    ):
        """
        Initialize ClientStorage.

        Args:
            host: Server hostname or IP address
            port: Server port
            address: SocketAddress instance (overrides host/port)
            tls_config: TLS configuration (if None, loads from environment)
            tls_enabled: Explicitly enable/disable TLS (None=auto-detect from config)
        """
        self.address = SocketAddress.new(address or (host, port))

        # Determine TLS configuration
        if tls_config is None:
            tls_config = get_env_tls_config()

        # Auto-detect TLS if config is provided but tls_enabled is not set
        if tls_enabled is None and tls_config is not None:
            tls_enabled = True

        self.tls_config = tls_config
        self.tls_enabled = tls_enabled and tls_config is not None

        # Connect to server
        self.s = self.address.get_connected_socket()
        if not self.s:
            raise ConnectionError(f"Could not connect to {self.address}")

        # Wrap socket with TLS if enabled
        if self.tls_enabled and self.tls_config:
            try:
                server_hostname = (
                    host if isinstance(address, (type(None), tuple)) else None
                )
                self.s = wrap_client_socket(
                    self.s,
                    self.tls_config,
                    server_hostname=server_hostname,
                )
            except Exception as e:
                self.s.close()
                raise ConnectionError(f"TLS handshake failed: {e}") from e

        self.oid_pool = []
        self.oid_pool_size = 32
        self.begin()
        protocol = StorageServer.protocol
        assert len(protocol) == 4
        write_all(self.s, "V", protocol)
        server_protocol = read(self.s, 4)
        if server_protocol != protocol:
            raise ProtocolError("Protocol version mismatch.")

    def __str__(self):
        return f"ClientStorage({self.address})"

    def new_oid(self):
        if not self.oid_pool:
            batch = self.oid_pool_size
            write(self.s, f"M{chr(batch)}")
            self.oid_pool = split_oids(read(self.s, 8 * batch))
            self.oid_pool.reverse()
            assert len(self.oid_pool) == len(set(self.oid_pool))
        oid = self.oid_pool.pop()
        assert oid not in self.oid_pool
        self.transaction_new_oids.append(oid)
        return oid

    def load(self, oid):
        write_all(self.s, "L", oid)
        return self._get_load_response(oid)

    def _get_load_response(self, oid):
        status = read(self.s, 1)
        if status == STATUS_OKAY:
            pass
        elif status == STATUS_INVALID:
            raise ReadConflictError([oid])
        elif status == STATUS_KEYERROR:
            raise DruvaKeyError(oid)
        else:
            raise ProtocolError(f"status={status!r}, oid={oid!r}")
        n = read_int4(self.s)
        record = read(self.s, n)
        return record

    def begin(self):
        self.records = {}
        self.transaction_new_oids = []

    def store(self, oid, record):
        assert len(oid) == 8
        assert oid not in self.records
        self.records[oid] = record

    def end(self, handle_invalidations=None):
        write(self.s, "C")
        n = read_int4(self.s)
        oid_list = []
        if n != 0:
            packed_oids = read(self.s, n * 8)
            oid_list = split_oids(packed_oids)
            try:
                handle_invalidations(oid_list)
            except ConflictError:
                self.transaction_new_oids.reverse()
                self.oid_pool.extend(self.transaction_new_oids)
                assert len(self.oid_pool) == len(set(self.oid_pool))
                self.begin()  # clear out records and transaction_new_oids.
                write_int4(self.s, 0)  # Tell server we are done.
                raise
        tdata = []
        for oid, record in iteritems(self.records):
            tdata.append(int4_to_str(8 + len(record)))
            tdata.append(as_bytes(oid))
            tdata.append(record)
        tdata = join_bytes(tdata)
        write_int4_str(self.s, tdata)
        self.records.clear()
        if len(tdata) > 0:
            status = read(self.s, 1)
            if status == STATUS_OKAY:
                pass
            elif status == STATUS_INVALID:
                raise WriteConflictError()
            else:
                raise ProtocolError(f"server returned invalid status {status!r}")

    def sync(self):
        write(self.s, "S")
        n = read_int4(self.s)
        if n == 0:
            packed_oids = ""
        else:
            packed_oids = read(self.s, n * 8)
        return split_oids(packed_oids)

    def pack(self):
        write(self.s, "P")
        status = read(self.s, 1)
        if status != STATUS_OKAY:
            raise ProtocolError(f"server returned invalid status {status!r}")

    def bulk_load(self, oids):
        oid_str = join_bytes(oids)
        num_oids, remainder = divmod(len(oid_str), 8)
        assert remainder == 0, remainder
        write_all(self.s, "B", int4_to_str(num_oids), oid_str)
        records = [self._get_load_response(oid) for oid in oids]
        yield from records

    def close(self):
        write(self.s, ".")  # Closes the server side.
        self.s.close()
