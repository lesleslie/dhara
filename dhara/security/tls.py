"""
TLS/SSL support for dhara network storage.

This module provides secure socket layer functionality for both
client and server connections, implementing best practices for:
- Certificate validation
- Secure cipher suites
- TLS version configuration
- Mutual authentication (optional)
"""

import os
import socket
import ssl
from pathlib import Path

# Default TLS configuration
DEFAULT_TLS_VERSION = ssl.TLSVersion.TLSv1_3
DEFAULT_VERIFY_MODE = ssl.CERT_REQUIRED

# Recommended cipher suites for TLS 1.2/1.3
# For TLS 1.3, cipher suites are configured differently
DEFAULT_CIPHER_SUITES = None  # Use system defaults for TLS 1.3


class TLSConfig:
    """Configuration for TLS/SSL connections."""

    def __init__(
        self,
        certfile: str | Path | None = None,
        keyfile: str | Path | None = None,
        cafile: str | Path | None = None,
        capath: str | Path | None = None,
        verify_mode: ssl.VerifyMode = DEFAULT_VERIFY_MODE,
        tls_version: ssl.TLSVersion = DEFAULT_TLS_VERSION,
        check_hostname: bool = True,
        cipher_suites: str | None = DEFAULT_CIPHER_SUITES,
        client_certfile: str | Path | None = None,
        client_keyfile: str | Path | None = None,
    ):
        """
        Initialize TLS configuration.

        Args:
            certfile: Path to server certificate file (PEM format)
            keyfile: Path to server private key file (PEM format)
            cafile: Path to CA certificate file for verification
            capath: Path to CA certificate directory
            verify_mode: SSL certificate verification mode
            tls_version: Minimum TLS version to use
            check_hostname: Whether to verify hostname in certificates
            cipher_suites: Colon-separated list of cipher suites (None for defaults)
            client_certfile: Path to client certificate for mutual auth
            client_keyfile: Path to client private key for mutual auth
        """
        self.certfile = Path(certfile) if certfile else None
        self.keyfile = Path(keyfile) if keyfile else None
        self.cafile = Path(cafile) if cafile else None
        self.capath = Path(capath) if capath else None
        self.verify_mode = verify_mode
        self.tls_version = tls_version
        self.check_hostname = check_hostname
        self.cipher_suites = cipher_suites
        self.client_certfile = Path(client_certfile) if client_certfile else None
        self.client_keyfile = Path(client_keyfile) if client_keyfile else None

        # Validate configuration
        self._validate()

    def _validate(self) -> None:
        """Validate TLS configuration."""
        # For server mode, both certfile and keyfile are required
        if self.certfile and not self.keyfile:
            raise ValueError("keyfile is required when certfile is provided")
        if self.keyfile and not self.certfile:
            raise ValueError("certfile is required when keyfile is provided")

        # For client authentication, both client cert and key are required
        if self.client_certfile and not self.client_keyfile:
            raise ValueError(
                "client_keyfile is required when client_certfile is provided"
            )
        if self.client_keyfile and not self.client_certfile:
            raise ValueError(
                "client_certfile is required when client_keyfile is provided"
            )

        # Check that certificate files exist
        if self.certfile and not self.certfile.exists():
            raise FileNotFoundError(f"Certificate file not found: {self.certfile}")
        if self.keyfile and not self.keyfile.exists():
            raise FileNotFoundError(f"Key file not found: {self.keyfile}")
        if self.cafile and not self.cafile.exists():
            raise FileNotFoundError(f"CA file not found: {self.cafile}")
        if self.capath and not self.capath.exists():
            raise FileNotFoundError(f"CA directory not found: {self.capath}")
        if self.client_certfile and not self.client_certfile.exists():
            raise FileNotFoundError(
                f"Client certificate not found: {self.client_certfile}"
            )
        if self.client_keyfile and not self.client_keyfile.exists():
            raise FileNotFoundError(f"Client key not found: {self.client_keyfile}")

    def create_server_context(self) -> ssl.SSLContext:
        """
        Create SSLContext for server connections.

        Returns:
            Configured SSLContext for server use

        Raises:
            ValueError: If certfile or keyfile is not configured
            FileNotFoundError: If certificate files don't exist
        """
        if not self.certfile or not self.keyfile:
            raise ValueError("Server TLS requires both certfile and keyfile")

        # Create SSL context with TLS version
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = self.tls_version

        # Load certificate and key
        context.load_cert_chain(
            certfile=str(self.certfile),
            keyfile=str(self.keyfile),
        )

        # Configure client certificate verification (for mutual TLS)
        if self.cafile or self.capath:
            context.verify_mode = self.verify_mode
            if self.cafile:
                context.load_verify_locations(cafile=str(self.cafile))
            if self.capath:
                context.load_verify_locations(capath=str(self.capath))
        else:
            # No CA configured - no client certificate verification
            context.verify_mode = ssl.CERT_NONE

        # Configure cipher suites (only for TLS 1.2)
        if self.cipher_suites and self.tls_version < ssl.TLSVersion.TLSv1_3:
            context.set_ciphers(self.cipher_suites)

        return context

    def create_client_context(self) -> ssl.SSLContext:
        """
        Create SSLContext for client connections.

        Returns:
            Configured SSLContext for client use
        """
        # Create SSL context
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = self.tls_version

        # Load CA certificates for server verification
        if self.cafile:
            context.load_verify_locations(cafile=str(self.cafile))
        if self.capath:
            context.load_verify_locations(capath=str(self.capath))
        elif self.verify_mode != ssl.CERT_NONE:
            # Use system default CA certificates
            context.load_default_certs(purpose=ssl.Purpose.SERVER_AUTH)

        # Configure verification mode
        context.verify_mode = self.verify_mode
        context.check_hostname = self.check_hostname

        # Load client certificate for mutual authentication
        if self.client_certfile and self.client_keyfile:
            context.load_cert_chain(
                certfile=str(self.client_certfile),
                keyfile=str(self.client_keyfile),
            )

        # Configure cipher suites (only for TLS 1.2)
        if self.cipher_suites and self.tls_version < ssl.TLSVersion.TLSv1_3:
            context.set_ciphers(self.cipher_suites)

        return context


def wrap_server_socket(
    sock: socket.socket,
    config: TLSConfig,
    server_side: bool = True,
) -> ssl.SSLSocket:
    """
    Wrap a server socket with TLS/SSL.

    Args:
        sock: The socket to wrap
        config: TLS configuration
        server_side: True for server socket, False for client

    Returns:
        SSL-wrapped socket

    Raises:
        ssl.SSLError: If TLS handshake fails
    """
    context = config.create_server_context()
    secure_sock = context.wrap_socket(sock, server_side=server_side)
    return secure_sock


def wrap_client_socket(
    sock: socket.socket,
    config: TLSConfig,
    server_hostname: str | None = None,
) -> ssl.SSLSocket:
    """
    Wrap a client socket with TLS/SSL.

    Args:
        sock: The socket to wrap
        config: TLS configuration
        server_hostname: Server hostname for SNI (if check_hostname is True)

    Returns:
        SSL-wrapped socket

    Raises:
        ssl.SSLError: If TLS handshake fails
    """
    context = config.create_client_context()
    secure_sock = context.wrap_socket(
        sock,
        server_side=False,
        server_hostname=server_hostname if config.check_hostname else None,
    )
    return secure_sock


def generate_self_signed_cert(
    certfile: str | Path,
    keyfile: str | Path,
    hostname: str = "localhost",
    valid_days: int = 365,
) -> None:
    """
    Generate a self-signed certificate for testing/development.

    WARNING: Self-signed certificates should ONLY be used for development
    and testing. Production deployments should use certificates from a
    trusted CA (Let's Encrypt, commercial CA, or internal PKI).

    Args:
        certfile: Path where certificate will be saved
        keyfile: Path where private key will be saved
        hostname: Common name for the certificate
        valid_days: Number of days the certificate is valid

    Raises:
        ImportError: If cryptography module is not available
        OSError: If files cannot be written
    """
    try:
        import datetime

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        raise ImportError(
            "cryptography module is required to generate self-signed certificates. "
            "Install it with: pip install cryptography"
        )

    certfile = Path(certfile)
    keyfile = Path(keyfile)

    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Create certificate
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Development"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Development"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Druva Development"),
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        ]
    )

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.UTC))
        .not_valid_after(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=valid_days)
        )
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(hostname)]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    # Write certificate
    certfile.parent.mkdir(parents=True, exist_ok=True)
    with certfile.open("wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    # Write private key
    keyfile.parent.mkdir(parents=True, exist_ok=True)
    with keyfile.open("wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )


def get_env_tls_config() -> TLSConfig | None:
    """
    Load TLS configuration from environment variables.

    Environment variables:
        DHARA_TLS_CERTFILE: Path to server certificate
        DHARA_TLS_KEYFILE: Path to server private key
        DHARA_TLS_CAFILE: Path to CA certificate
        DHARA_TLS_CAPATH: Path to CA directory
        DHARA_TLS_CLIENT_CERTFILE: Path to client certificate (mutual TLS)
        DHARA_TLS_CLIENT_KEYFILE: Path to client private key (mutual TLS)
        DHARA_TLS_VERIFY_MODE: Verification mode (none, optional, required)
        DHARA_TLS_VERSION: Minimum TLS version (1.2, 1.3)
        DHARA_TLS_CHECK_HOSTNAME: Enable hostname verification (true/false)

    Returns:
        TLSConfig if any TLS environment variables are set, None otherwise
    """
    certfile = os.getenv("DHARA_TLS_CERTFILE")
    keyfile = os.getenv("DHARA_TLS_KEYFILE")
    cafile = os.getenv("DHARA_TLS_CAFILE")
    capath = os.getenv("DHARA_TLS_CAPATH")
    client_certfile = os.getenv("DHARA_TLS_CLIENT_CERTFILE")
    client_keyfile = os.getenv("DHARA_TLS_CLIENT_KEYFILE")

    # If no TLS config is set, return None
    if not any([certfile, keyfile, cafile, capath, client_certfile, client_keyfile]):
        return None

    # Parse verify mode
    verify_mode_str = os.getenv("DHARA_TLS_VERIFY_MODE", "required").lower()
    verify_mode_map = {
        "none": ssl.CERT_NONE,
        "optional": ssl.CERT_OPTIONAL,
        "required": ssl.CERT_REQUIRED,
    }
    verify_mode = verify_mode_map.get(verify_mode_str, ssl.CERT_REQUIRED)

    # Parse TLS version
    tls_version_str = os.getenv("DHARA_TLS_VERSION", "1.3")
    tls_version_map = {
        "1.2": ssl.TLSVersion.TLSv1_2,
        "1.3": ssl.TLSVersion.TLSv1_3,
    }
    tls_version = tls_version_map.get(tls_version_str, ssl.TLSVersion.TLSv1_3)

    # Parse hostname check
    check_hostname = os.getenv("DHARA_TLS_CHECK_HOSTNAME", "true").lower() == "true"

    return TLSConfig(
        certfile=certfile,
        keyfile=keyfile,
        cafile=cafile,
        capath=capath,
        verify_mode=verify_mode,
        tls_version=tls_version,
        check_hostname=check_hostname,
        client_certfile=client_certfile,
        client_keyfile=client_keyfile,
    )
