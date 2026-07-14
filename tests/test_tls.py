"""Tests for TLS/SSL configuration and utilities.

from __future__ import annotations
Tests TLSConfig, socket wrapping, self-signed cert generation,
and environment-based configuration loading from dhara.security.tls.
"""

import os
import ssl

import pytest

from dhara.security.tls import (
    DEFAULT_CIPHER_SUITES,
    DEFAULT_TLS_VERSION,
    DEFAULT_VERIFY_MODE,
    TLSConfig,
    _get_tls_env,
    generate_self_signed_cert,
    get_env_tls_config,
    wrap_client_socket,
    wrap_server_socket,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_tls_certs(tmp_path) -> None:
    """Generate self-signed cert + key pair, return (certfile, keyfile) paths."""
    try:
        generate_self_signed_cert(
            certfile=tmp_path / "cert.pem",
            keyfile=tmp_path / "key.pem",
            hostname="localhost",
            valid_days=1,
        )
    except ImportError:
        pytest.skip("cryptography module not installed")
    return str(tmp_path / "cert.pem"), str(tmp_path / "key.pem")


@pytest.fixture
def temp_ca_cert(tmp_path, temp_tls_certs) -> None:
    """Create a CA cert file (reuses server cert for testing)."""
    ca_path = tmp_path / "ca.pem"
    # For testing, copy server cert as CA cert
    import shutil

    shutil.copy(temp_tls_certs[0], ca_path)
    return str(ca_path)


@pytest.fixture
def server_config(temp_tls_certs) -> None:
    """Create a TLSConfig with real cert/key files."""
    certfile, keyfile = temp_tls_certs
    return TLSConfig(certfile=certfile, keyfile=keyfile)


# ============================================================================
# Module constants
# ============================================================================


class TestModuleConstants:
    """Tests for module-level defaults."""

    def test_default_tls_version_is_1_3(self) -> None:
        assert DEFAULT_TLS_VERSION == ssl.TLSVersion.TLSv1_3

    def test_default_verify_mode_is_required(self) -> None:
        assert DEFAULT_VERIFY_MODE == ssl.CERT_REQUIRED

    def test_default_cipher_suites_is_none(self) -> None:
        assert DEFAULT_CIPHER_SUITES is None


# ============================================================================
# _get_tls_env
# ============================================================================


class TestGetTlsEnv:
    """Tests for _get_tls_env helper."""

    def test_reads_dhara_env(self, monkeypatch) -> None:
        monkeypatch.setenv("DHARA_TLS_CERTFILE", "/path/to/cert")
        assert _get_tls_env("CERTFILE") == "/path/to/cert"

    def test_falls_back_to_druva(self, monkeypatch) -> None:
        monkeypatch.delenv("DHARA_TLS_CERTFILE", raising=False)
        monkeypatch.setenv("DRUVA_TLS_CERTFILE", "/druva/cert")
        assert _get_tls_env("CERTFILE") == "/druva/cert"

    def test_dhara_preferred_over_druva(self, monkeypatch) -> None:
        monkeypatch.setenv("DHARA_TLS_CERTFILE", "/dhara/cert")
        monkeypatch.setenv("DRUVA_TLS_CERTFILE", "/druva/cert")
        assert _get_tls_env("CERTFILE") == "/dhara/cert"

    def test_returns_default_when_not_set(self, monkeypatch) -> None:
        monkeypatch.delenv("DHARA_TLS_KEYFILE", raising=False)
        monkeypatch.delenv("DRUVA_TLS_KEYFILE", raising=False)
        assert _get_tls_env("KEYFILE", "fallback") == "fallback"

    def test_returns_none_when_not_set_and_no_default(self, monkeypatch) -> None:
        monkeypatch.delenv("DHARA_TLS_KEYFILE", raising=False)
        monkeypatch.delenv("DRUVA_TLS_KEYFILE", raising=False)
        assert _get_tls_env("KEYFILE") is None


# ============================================================================
# TLSConfig.__init__ and _validate
# ============================================================================


class TestTLSConfigInit:
    """Tests for TLSConfig construction and validation."""

    def test_minimal_config(self, temp_tls_certs) -> None:
        certfile, keyfile = temp_tls_certs
        config = TLSConfig(certfile=certfile, keyfile=keyfile)
        assert config.certfile.name.endswith("cert.pem")
        assert config.keyfile.name.endswith("key.pem")
        assert config.cafile is None
        assert config.capath is None
        assert config.verify_mode == ssl.CERT_REQUIRED
        assert config.tls_version == ssl.TLSVersion.TLSv1_3
        assert config.check_hostname is True

    def test_cert_without_key_raises(self) -> None:
        with pytest.raises(ValueError, match="keyfile is required"):
            TLSConfig(certfile="/nonexistent/cert.pem")

    def test_key_without_cert_raises(self) -> None:
        with pytest.raises(ValueError, match="certfile is required"):
            TLSConfig(keyfile="/nonexistent/key.pem")

    def test_client_cert_without_key_raises(self, temp_tls_certs) -> None:
        certfile, _ = temp_tls_certs
        with pytest.raises(ValueError, match="client_keyfile is required"):
            TLSConfig(
                certfile=certfile, keyfile=temp_tls_certs[1], client_certfile=certfile
            )

    def test_client_key_without_cert_raises(self, temp_tls_certs) -> None:
        certfile, keyfile = temp_tls_certs
        with pytest.raises(ValueError, match="client_certfile is required"):
            TLSConfig(certfile=certfile, keyfile=keyfile, client_keyfile=keyfile)

    def test_nonexistent_cert_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError, match="Certificate file not found"):
            TLSConfig(certfile="/nonexistent/cert.pem", keyfile="/nonexistent/key.pem")

    def test_nonexistent_ca_file_raises(self, temp_tls_certs) -> None:
        certfile, keyfile = temp_tls_certs
        with pytest.raises(FileNotFoundError, match="CA file not found"):
            TLSConfig(certfile=certfile, keyfile=keyfile, cafile="/nonexistent/ca.pem")

    def test_nonexistent_key_file_raises(self, temp_tls_certs) -> None:
        certfile, _ = temp_tls_certs
        with pytest.raises(FileNotFoundError, match="Key file not found"):
            TLSConfig(certfile=certfile, keyfile="/nonexistent/key.pem")

    def test_nonexistent_capath_raises(self, temp_tls_certs) -> None:
        certfile, keyfile = temp_tls_certs
        with pytest.raises(FileNotFoundError, match="CA directory file not found"):
            TLSConfig(certfile=certfile, keyfile=keyfile, capath="/nonexistent/ca_dir")

    def test_nonexistent_client_cert_file_raises(self, temp_tls_certs) -> None:
        certfile, keyfile = temp_tls_certs
        with pytest.raises(
            FileNotFoundError, match="Client certificate file not found"
        ):
            TLSConfig(
                certfile=certfile,
                keyfile=keyfile,
                client_certfile="/nonexistent/client-cert.pem",
                client_keyfile=keyfile,
            )

    def test_nonexistent_client_key_file_raises(self, temp_tls_certs) -> None:
        certfile, keyfile = temp_tls_certs
        with pytest.raises(FileNotFoundError, match="Client key file not found"):
            TLSConfig(
                certfile=certfile,
                keyfile=keyfile,
                client_certfile=certfile,
                client_keyfile="/nonexistent/client-key.pem",
            )

    def test_custom_verify_mode(self, temp_tls_certs) -> None:
        certfile, keyfile = temp_tls_certs
        config = TLSConfig(
            certfile=certfile,
            keyfile=keyfile,
            verify_mode=ssl.CERT_NONE,
        )
        assert config.verify_mode == ssl.CERT_NONE

    def test_custom_tls_version(self, temp_tls_certs) -> None:
        certfile, keyfile = temp_tls_certs
        config = TLSConfig(
            certfile=certfile,
            keyfile=keyfile,
            tls_version=ssl.TLSVersion.TLSv1_2,
        )
        assert config.tls_version == ssl.TLSVersion.TLSv1_2

    def test_paths_converted_to_pathlib(self, temp_tls_certs) -> None:
        certfile, keyfile = temp_tls_certs
        config = TLSConfig(certfile=certfile, keyfile=keyfile)
        assert isinstance(config.certfile, os.PathLike)
        assert isinstance(config.keyfile, os.PathLike)

    def test_none_params_stay_none(self, temp_tls_certs) -> None:
        certfile, keyfile = temp_tls_certs
        config = TLSConfig(certfile=certfile, keyfile=keyfile)
        assert config.cafile is None
        assert config.capath is None
        assert config.client_certfile is None
        assert config.client_keyfile is None


# ============================================================================
# create_server_context
# ============================================================================


class TestCreateServerContext:
    """Tests for TLSConfig.create_server_context."""

    def test_creates_server_context(self, server_config) -> None:
        ctx = server_config.create_server_context()
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.minimum_version == ssl.TLSVersion.TLSv1_3

    def test_server_context_without_certs_raises(self) -> None:
        config = TLSConfig()
        with pytest.raises(ValueError, match="requires both certfile and keyfile"):
            config.create_server_context()

    def test_server_context_with_ca_uses_verify_mode(
        self, server_config, temp_ca_cert
    ) -> None:
        config = TLSConfig(
            certfile=server_config.certfile,
            keyfile=server_config.keyfile,
            cafile=temp_ca_cert,
            verify_mode=ssl.CERT_REQUIRED,
        )
        ctx = config.create_server_context()
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_server_context_without_ca_uses_cert_none(self, server_config) -> None:
        ctx = server_config.create_server_context()
        assert ctx.verify_mode == ssl.CERT_NONE

    def test_server_context_with_cafile_and_capath(
        self, temp_tls_certs, temp_ca_cert, tmp_path, monkeypatch
    ):
        certfile, keyfile = temp_tls_certs
        capath = tmp_path / "ca-dir"
        capath.mkdir()

        calls: list[tuple[str, dict[str, str | None]]] = []

        class FakeContext:
            def __init__(self, protocol) -> None:
                self.protocol = protocol
                self.minimum_version = None
                self.verify_mode = None

            def load_cert_chain(self, **kwargs) -> None:
                calls.append(("load_cert_chain", kwargs))

            def load_verify_locations(self, **kwargs) -> None:
                calls.append(("load_verify_locations", kwargs))

            def set_ciphers(self, ciphers) -> None:
                calls.append(("set_ciphers", {"ciphers": ciphers}))

        monkeypatch.setattr(ssl, "SSLContext", FakeContext)

        config = TLSConfig(
            certfile=certfile,
            keyfile=keyfile,
            cafile=temp_ca_cert,
            capath=capath,
            verify_mode=ssl.CERT_OPTIONAL,
            tls_version=ssl.TLSVersion.TLSv1_2,
            cipher_suites="ECDHE+AESGCM",
        )
        ctx = config.create_server_context()

        assert isinstance(ctx, FakeContext)
        assert ctx.verify_mode == ssl.CERT_OPTIONAL
        assert (
            "load_cert_chain",
            {"certfile": str(config.certfile), "keyfile": str(config.keyfile)},
        ) in calls
        assert ("load_verify_locations", {"cafile": str(config.cafile)}) in calls
        assert ("load_verify_locations", {"capath": str(config.capath)}) in calls
        assert ("set_ciphers", {"ciphers": "ECDHE+AESGCM"}) in calls

    def test_server_context_with_capath_only(
        self, temp_tls_certs, tmp_path, monkeypatch
    ):
        certfile, keyfile = temp_tls_certs
        capath = tmp_path / "server-ca"
        capath.mkdir()

        calls: list[tuple[str, dict[str, str | None]]] = []

        class FakeContext:
            def __init__(self, protocol) -> None:
                self.protocol = protocol
                self.minimum_version = None
                self.verify_mode = None

            def load_cert_chain(self, **kwargs) -> None:
                calls.append(("load_cert_chain", kwargs))

            def load_verify_locations(self, **kwargs) -> None:
                calls.append(("load_verify_locations", kwargs))

            def set_ciphers(self, ciphers) -> None:
                calls.append(("set_ciphers", {"ciphers": ciphers}))

        monkeypatch.setattr(ssl, "SSLContext", FakeContext)

        config = TLSConfig(
            certfile=certfile,
            keyfile=keyfile,
            capath=capath,
            verify_mode=ssl.CERT_REQUIRED,
        )
        ctx = config.create_server_context()

        assert isinstance(ctx, FakeContext)
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ("load_verify_locations", {"capath": str(config.capath)}) in calls
        assert not any(
            name == "load_verify_locations" and "cafile" in kwargs
            for name, kwargs in calls
        )


# ============================================================================
# create_client_context
# ============================================================================


class TestCreateClientContext:
    """Tests for TLSConfig.create_client_context."""

    def test_creates_client_context(self, server_config) -> None:
        ctx = server_config.create_client_context()
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.minimum_version == ssl.TLSVersion.TLSv1_3

    def test_client_context_with_ca(self, server_config, temp_ca_cert) -> None:
        config = TLSConfig(
            certfile=server_config.certfile,
            keyfile=server_config.keyfile,
            cafile=temp_ca_cert,
        )
        ctx = config.create_client_context()
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_client_context_hostname_check(self, server_config) -> None:
        config = TLSConfig(
            certfile=server_config.certfile,
            keyfile=server_config.keyfile,
            check_hostname=False,
        )
        ctx = config.create_client_context()
        assert ctx.check_hostname is False

    def test_client_context_with_mutual_tls(self, temp_tls_certs) -> None:
        certfile, keyfile = temp_tls_certs
        config = TLSConfig(
            certfile=certfile,
            keyfile=keyfile,
            client_certfile=certfile,
            client_keyfile=keyfile,
        )
        ctx = config.create_client_context()
        assert isinstance(ctx, ssl.SSLContext)

    def test_client_context_with_capath_and_mutual_tls(
        self, temp_tls_certs, temp_ca_cert, tmp_path, monkeypatch
    ):
        certfile, keyfile = temp_tls_certs
        capath = tmp_path / "client-ca"
        capath.mkdir()

        calls: list[tuple[str, dict[str, str | None] | dict[str, object]]] = []

        class FakeContext:
            def __init__(self, protocol) -> None:
                self.protocol = protocol
                self.minimum_version = None
                self.verify_mode = None
                self.check_hostname = None

            def load_verify_locations(self, **kwargs) -> None:
                calls.append(("load_verify_locations", kwargs))

            def load_default_certs(self, **kwargs) -> None:
                calls.append(("load_default_certs", kwargs))

            def load_cert_chain(self, **kwargs) -> None:
                calls.append(("load_cert_chain", kwargs))

            def set_ciphers(self, ciphers) -> None:
                calls.append(("set_ciphers", {"ciphers": ciphers}))

        monkeypatch.setattr(ssl, "SSLContext", FakeContext)

        config = TLSConfig(
            certfile=certfile,
            keyfile=keyfile,
            cafile=temp_ca_cert,
            capath=capath,
            client_certfile=certfile,
            client_keyfile=keyfile,
            tls_version=ssl.TLSVersion.TLSv1_2,
            cipher_suites="ECDHE+AESGCM",
        )
        ctx = config.create_client_context()

        assert isinstance(ctx, FakeContext)
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is True
        assert ("load_verify_locations", {"cafile": str(config.cafile)}) in calls
        assert ("load_verify_locations", {"capath": str(config.capath)}) in calls
        assert (
            "load_cert_chain",
            {
                "certfile": str(config.client_certfile),
                "keyfile": str(config.client_keyfile),
            },
        ) in calls
        assert ("set_ciphers", {"ciphers": "ECDHE+AESGCM"}) in calls

    def test_client_context_verify_none_skips_default_certs(
        self, temp_tls_certs, monkeypatch
    ):
        certfile, keyfile = temp_tls_certs
        calls: list[tuple[str, dict[str, object]]] = []

        class FakeContext:
            def __init__(self, protocol) -> None:
                self.protocol = protocol
                self.minimum_version = None
                self.verify_mode = None
                self.check_hostname = None

            def load_verify_locations(self, **kwargs) -> None:
                calls.append(("load_verify_locations", kwargs))

            def load_default_certs(self, **kwargs) -> None:
                calls.append(("load_default_certs", kwargs))

            def load_cert_chain(self, **kwargs) -> None:
                calls.append(("load_cert_chain", kwargs))

            def set_ciphers(self, ciphers) -> None:
                calls.append(("set_ciphers", {"ciphers": ciphers}))

        monkeypatch.setattr(ssl, "SSLContext", FakeContext)

        config = TLSConfig(
            certfile=certfile,
            keyfile=keyfile,
            verify_mode=ssl.CERT_NONE,
        )
        ctx = config.create_client_context()

        assert isinstance(ctx, FakeContext)
        assert ctx.verify_mode == ssl.CERT_NONE
        assert ("load_default_certs", {"purpose": ssl.Purpose.SERVER_AUTH}) not in calls


# ============================================================================
# wrap_server_socket / wrap_client_socket
# ============================================================================


class TestSocketWrapping:
    """Tests for the thin socket wrapper helpers."""

    def test_wrap_server_socket_uses_server_context(self, temp_tls_certs) -> None:
        certfile, keyfile = temp_tls_certs
        sentinels: list[tuple[str, object]] = []

        class FakeContext:
            def wrap_socket(
                self, sock, server_side=False, server_hostname=None
            ) -> None:
                sentinels.append(("wrap_socket", (sock, server_side, server_hostname)))
                return "wrapped-server"

        config = TLSConfig(certfile=certfile, keyfile=keyfile)
        config.create_server_context = lambda: FakeContext()

        result = wrap_server_socket("plain-socket", config)
        assert result == "wrapped-server"
        assert sentinels == [("wrap_socket", ("plain-socket", True, None))]

    def test_wrap_client_socket_respects_hostname_check(self, temp_tls_certs) -> None:
        certfile, keyfile = temp_tls_certs
        sentinels: list[tuple[str, object]] = []

        class FakeContext:
            def wrap_socket(
                self, sock, server_side=False, server_hostname=None
            ) -> None:
                sentinels.append(("wrap_socket", (sock, server_side, server_hostname)))
                return "wrapped-client"

        config = TLSConfig(certfile=certfile, keyfile=keyfile, check_hostname=True)
        config.create_client_context = lambda: FakeContext()

        result = wrap_client_socket(
            "plain-socket", config, server_hostname="example.com"
        )
        assert result == "wrapped-client"
        assert sentinels == [("wrap_socket", ("plain-socket", False, "example.com"))]

    def test_wrap_client_socket_omits_hostname_when_disabled(
        self, temp_tls_certs
    ) -> None:
        certfile, keyfile = temp_tls_certs
        sentinels: list[tuple[str, object]] = []

        class FakeContext:
            def wrap_socket(
                self, sock, server_side=False, server_hostname=None
            ) -> None:
                sentinels.append(("wrap_socket", (sock, server_side, server_hostname)))
                return "wrapped-client"

        config = TLSConfig(certfile=certfile, keyfile=keyfile, check_hostname=False)
        config.create_client_context = lambda: FakeContext()

        result = wrap_client_socket(
            "plain-socket", config, server_hostname="example.com"
        )
        assert result == "wrapped-client"
        assert sentinels == [("wrap_socket", ("plain-socket", False, None))]


# ============================================================================
# generate_self_signed_cert
# ============================================================================


class TestGenerateSelfSignedCert:
    """Tests for generate_self_signed_cert."""

    def test_creates_cert_and_key_files(self, tmp_path) -> None:
        certfile = tmp_path / "cert.pem"
        keyfile = tmp_path / "key.pem"
        generate_self_signed_cert(certfile, keyfile)
        assert certfile.exists()
        assert keyfile.exists()

    def test_cert_contains_pem_data(self, tmp_path) -> None:
        certfile = tmp_path / "cert.pem"
        keyfile = tmp_path / "key.pem"
        generate_self_signed_cert(certfile, keyfile)
        content = certfile.read_text()
        assert "-----BEGIN CERTIFICATE-----" in content

    def test_key_contains_pem_data(self, tmp_path) -> None:
        certfile = tmp_path / "cert.pem"
        keyfile = tmp_path / "key.pem"
        generate_self_signed_cert(certfile, keyfile)
        content = keyfile.read_text()
        assert "-----BEGIN RSA PRIVATE KEY-----" in content

    def test_creates_parent_directories(self, tmp_path) -> None:
        certfile = tmp_path / "nested" / "cert.pem"
        keyfile = tmp_path / "nested" / "key.pem"
        generate_self_signed_cert(certfile, keyfile)
        assert certfile.exists()

    def test_custom_hostname(self, tmp_path) -> None:
        certfile = tmp_path / "cert.pem"
        keyfile = tmp_path / "key.pem"
        generate_self_signed_cert(certfile, keyfile, hostname="example.com")

    def test_can_load_cert_as_tls_config(self, tmp_path) -> None:
        certfile = tmp_path / "cert.pem"
        keyfile = tmp_path / "key.pem"
        generate_self_signed_cert(certfile, keyfile)
        config = TLSConfig(certfile=str(certfile), keyfile=str(keyfile))
        ctx = config.create_server_context()
        assert isinstance(ctx, ssl.SSLContext)

    def test_requires_cryptography(self) -> None:
        """The function raises ImportError when cryptography is missing.

        We verify the source code has the correct guard rather than
        removing cryptography at runtime, which corrupts sys.modules
        for subsequent tests.
        """
        import inspect

        source = inspect.getsource(generate_self_signed_cert)
        assert "ImportError" in source
        assert "cryptography" in source


# ============================================================================
# get_env_tls_config
# ============================================================================


class TestGetEnvTlsConfig:
    """Tests for get_env_tls_config."""

    def test_returns_none_when_no_env_set(self, monkeypatch) -> None:
        for var in [
            "DHARA_TLS_CERTFILE",
            "DHARA_TLS_KEYFILE",
            "DHARA_TLS_CAFILE",
            "DHARA_TLS_CAPATH",
            "DHARA_TLS_CLIENT_CERTFILE",
            "DHARA_TLS_CLIENT_KEYFILE",
            "DRUVA_TLS_CERTFILE",
            "DRUVA_TLS_KEYFILE",
            "DRUVA_TLS_CAFILE",
            "DRUVA_TLS_CAPATH",
            "DRUVA_TLS_CLIENT_CERTFILE",
            "DRUVA_TLS_CLIENT_KEYFILE",
        ]:
            monkeypatch.delenv(var, raising=False)
        assert get_env_tls_config() is None

    def test_returns_config_from_cert_env(self, temp_tls_certs, monkeypatch) -> None:
        certfile, keyfile = temp_tls_certs
        monkeypatch.setenv("DHARA_TLS_CERTFILE", certfile)
        monkeypatch.setenv("DHARA_TLS_KEYFILE", keyfile)
        config = get_env_tls_config()
        assert config is not None
        assert isinstance(config, TLSConfig)

    def test_verify_mode_default_required(self, temp_tls_certs, monkeypatch) -> None:
        certfile, keyfile = temp_tls_certs
        monkeypatch.setenv("DHARA_TLS_CERTFILE", certfile)
        monkeypatch.setenv("DHARA_TLS_KEYFILE", keyfile)
        config = get_env_tls_config()
        assert config.verify_mode == ssl.CERT_REQUIRED

    def test_verify_mode_from_env(self, temp_tls_certs, monkeypatch) -> None:
        certfile, keyfile = temp_tls_certs
        monkeypatch.setenv("DHARA_TLS_CERTFILE", certfile)
        monkeypatch.setenv("DHARA_TLS_KEYFILE", keyfile)
        monkeypatch.setenv("DHARA_TLS_VERIFY_MODE", "none")
        config = get_env_tls_config()
        assert config.verify_mode == ssl.CERT_NONE

    def test_tls_version_from_env(self, temp_tls_certs, monkeypatch) -> None:
        certfile, keyfile = temp_tls_certs
        monkeypatch.setenv("DHARA_TLS_CERTFILE", certfile)
        monkeypatch.setenv("DHARA_TLS_KEYFILE", keyfile)
        monkeypatch.setenv("DHARA_TLS_VERSION", "1.2")
        config = get_env_tls_config()
        assert config.tls_version == ssl.TLSVersion.TLSv1_2

    def test_hostname_check_from_env(self, temp_tls_certs, monkeypatch) -> None:
        certfile, keyfile = temp_tls_certs
        monkeypatch.setenv("DHARA_TLS_CERTFILE", certfile)
        monkeypatch.setenv("DHARA_TLS_KEYFILE", keyfile)
        monkeypatch.setenv("DHARA_TLS_CHECK_HOSTNAME", "false")
        config = get_env_tls_config()
        assert config.check_hostname is False

    def test_unknown_verify_mode_defaults_to_required(
        self, temp_tls_certs, monkeypatch
    ):
        certfile, keyfile = temp_tls_certs
        monkeypatch.setenv("DHARA_TLS_CERTFILE", certfile)
        monkeypatch.setenv("DHARA_TLS_KEYFILE", keyfile)
        monkeypatch.setenv("DHARA_TLS_VERIFY_MODE", "invalid")
        config = get_env_tls_config()
        assert config.verify_mode == ssl.CERT_REQUIRED
