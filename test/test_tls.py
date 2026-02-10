"""
Tests for TLS/SSL support in dhruva.

These tests verify that TLS configuration and socket wrapping work correctly.
"""

import os
import ssl
import tempfile
from pathlib import Path

import pytest

from dhruva.security.tls import (
    TLSConfig,
    generate_self_signed_cert,
    get_env_tls_config,
    wrap_client_socket,
    wrap_server_socket,
)


class TestTLSConfig:
    """Test TLSConfig creation and validation."""

    def test_server_config_requires_cert_and_key(self):
        """Server TLS config requires both certfile and keyfile."""
        with pytest.raises(ValueError, match="keyfile is required"):
            TLSConfig(certfile="test.crt")

        with pytest.raises(ValueError, match="certfile is required"):
            TLSConfig(keyfile="test.key")

    def test_mutual_tls_requires_both_client_cert_and_key(self):
        """Mutual TLS requires both client cert and key."""
        with pytest.raises(ValueError, match="client_keyfile is required"):
            TLSConfig(
                certfile="server.crt",
                keyfile="server.key",
                client_certfile="client.crt",
            )

        with pytest.raises(ValueError, match="client_certfile is required"):
            TLSConfig(
                certfile="server.crt",
                keyfile="server.key",
                client_keyfile="client.key",
            )

    def test_nonexistent_cert_file_raises_error(self):
        """Nonexistent certificate file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Certificate file not found"):
            TLSConfig(certfile="nonexistent.crt", keyfile="test.key")

    def test_create_server_context(self):
        """Test creating server SSL context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            certfile = Path(tmpdir) / "server.crt"
            keyfile = Path(tmpdir) / "server.key"

            # Generate self-signed certificate
            generate_self_signed_cert(certfile, keyfile, hostname="localhost")

            # Create TLS config
            config = TLSConfig(certfile=certfile, keyfile=keyfile)

            # Create server context
            context = config.create_server_context()

            assert context.protocol == ssl.PROTOCOL_TLS_SERVER
            assert context.minimum_version == ssl.TLSVersion.TLSv1_3

    def test_create_client_context(self):
        """Test creating client SSL context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            certfile = Path(tmpdir) / "server.crt"
            keyfile = Path(tmpdir) / "server.key"
            cafile = Path(tmpdir) / "ca.crt"

            # Generate self-signed certificate
            generate_self_signed_cert(certfile, keyfile, hostname="localhost")

            # Use server cert as CA for testing
            import shutil
            shutil.copy(certfile, cafile)

            # Create TLS config
            config = TLSConfig(cafile=cafile)

            # Create client context
            context = config.create_client_context()

            assert context.protocol == ssl.PROTOCOL_TLS_CLIENT
            assert context.minimum_version == ssl.TLSVersion.TLSv1_3
            assert context.verify_mode == ssl.CERT_REQUIRED
            assert context.check_hostname is True


class TestGenerateSelfSignedCert:
    """Test self-signed certificate generation."""

    def test_generate_cert_creates_files(self):
        """Test that certificate generation creates the expected files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            certfile = Path(tmpdir) / "test.crt"
            keyfile = Path(tmpdir) / "test.key"

            generate_self_signed_cert(certfile, keyfile, hostname="testhost")

            assert certfile.exists()
            assert keyfile.exists()

            # Verify cert contains expected content
            cert_content = certfile.read_text()
            assert "CERTIFICATE" in cert_content

            # Verify key contains expected content
            key_content = keyfile.read_text()
            assert "PRIVATE KEY" in key_content

    def test_generate_cert_creates_parent_directories(self):
        """Test that certificate generation creates parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            certfile = Path(tmpdir) / "subdir" / "test.crt"
            keyfile = Path(tmpdir) / "subdir" / "test.key"

            generate_self_signed_cert(certfile, keyfile)

            assert certfile.exists()
            assert keyfile.exists()


class TestEnvTLSConfig:
    """Test environment variable TLS configuration."""

    def test_no_env_vars_returns_none(self):
        """Test that no TLS environment vars returns None."""
        # Clear any existing TLS env vars
        for key in list(os.environ.keys()):
            if key.startswith("DHRUVA_TLS_"):
                del os.environ[key]

        config = get_env_tls_config()
        assert config is None

    def test_env_vars_create_config(self):
        """Test that TLS environment vars create a config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            certfile = Path(tmpdir) / "server.crt"
            keyfile = Path(tmpdir) / "server.key"

            # Generate certificates
            generate_self_signed_cert(certfile, keyfile)

            # Set environment variables
            os.environ["DHRUVA_TLS_CERTFILE"] = str(certfile)
            os.environ["DHRUVA_TLS_KEYFILE"] = str(keyfile)

            try:
                config = get_env_tls_config()
                assert config is not None
                assert config.certfile == certfile
                assert config.keyfile == keyfile
            finally:
                # Clean up
                del os.environ["DHRUVA_TLS_CERTFILE"]
                del os.environ["DHRUVA_TLS_KEYFILE"]

    def test_verify_mode_from_env(self):
        """Test that verify mode can be set from environment."""
        with tempfile.TemporaryDirectory() as tmpdir:
            certfile = Path(tmpdir) / "server.crt"
            keyfile = Path(tmpdir) / "server.key"

            generate_self_signed_cert(certfile, keyfile)

            os.environ["DHRUVA_TLS_CERTFILE"] = str(certfile)
            os.environ["DHRUVA_TLS_KEYFILE"] = str(keyfile)

            for mode, expected in [
                ("none", ssl.CERT_NONE),
                ("optional", ssl.CERT_OPTIONAL),
                ("required", ssl.CERT_REQUIRED),
            ]:
                os.environ["DHRUVA_TLS_VERIFY_MODE"] = mode
                try:
                    config = get_env_tls_config()
                    assert config.verify_mode == expected
                finally:
                    if "DHRUVA_TLS_VERIFY_MODE" in os.environ:
                        del os.environ["DHRUVA_TLS_VERIFY_MODE"]

            # Clean up
            del os.environ["DHRUVA_TLS_CERTFILE"]
            del os.environ["DHRUVA_TLS_KEYFILE"]


@pytest.mark.integration
class TestTLSWrapping:
    """Integration tests for TLS socket wrapping."""

    def test_wrap_server_socket(self):
        """Test wrapping a server socket with TLS."""
        import socket

        with tempfile.TemporaryDirectory() as tmpdir:
            certfile = Path(tmpdir) / "server.crt"
            keyfile = Path(tmpdir) / "server.key"

            generate_self_signed_cert(certfile, keyfile)
            config = TLSConfig(certfile=certfile, keyfile=keyfile)

            # Create a simple socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))  # Bind to ephemeral port
            sock.listen(1)

            try:
                # Wrap with TLS
                secure_sock = wrap_server_socket(sock, config)

                assert secure_sock is not None
                # SSLSocket has additional attributes
                assert hasattr(secure_sock, "context")
            finally:
                sock.close()

    def test_client_server_tls_handshake(self):
        """Test TLS handshake between client and server."""
        import socket
        import threading

        with tempfile.TemporaryDirectory() as tmpdir:
            # Generate server certificate
            server_cert = Path(tmpdir) / "server.crt"
            server_key = Path(tmpdir) / "server.key"
            generate_self_signed_cert(server_cert, server_key, hostname="localhost")

            # Server config
            server_config = TLSConfig(certfile=server_cert, keyfile=server_key)

            # Client config (use server cert as CA for testing)
            client_config = TLSConfig(
                cafile=server_cert,
                check_hostname=False,  # Don't verify hostname for localhost test
            )

            # Create server socket
            server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_sock.bind(("127.0.0.1", 0))
            server_sock.listen(1)
            port = server_sock.getsockname()[1]

            # Server thread to accept connection
            def server_thread():
                try:
                    conn, addr = server_sock.accept()
                    secure_conn = wrap_server_socket(conn, server_config)
                    # Send test message
                    secure_conn.send(b"Hello from server")
                    secure_conn.close()
                except Exception as e:
                    print(f"Server error: {e}")

            thread = threading.Thread(target=server_thread, daemon=True)
            thread.start()

            # Client connection
            try:
                client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client_sock.connect(("127.0.0.1", port))

                # Wrap with TLS
                secure_client = wrap_client_socket(
                    client_sock,
                    client_config,
                    server_hostname="localhost",
                )

                # Receive message
                data = secure_client.recv(1024)
                assert data == b"Hello from server"

                secure_client.close()
            finally:
                server_sock.close()
                thread.join(timeout=2)
