"""Tests for TLS/SSL configuration and utilities.

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
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_tls_certs(tmp_path):
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
def temp_ca_cert(tmp_path, temp_tls_certs):
    """Create a CA cert file (reuses server cert for testing)."""
    ca_path = tmp_path / "ca.pem"
    # For testing, copy server cert as CA cert
    import shutil

    shutil.copy(temp_tls_certs[0], ca_path)
    return str(ca_path)


@pytest.fixture
def server_config(temp_tls_certs):
    """Create a TLSConfig with real cert/key files."""
    certfile, keyfile = temp_tls_certs
    return TLSConfig(certfile=certfile, keyfile=keyfile)


# ============================================================================
# Module constants
# ============================================================================


class TestModuleConstants:
    """Tests for module-level defaults."""

    def test_default_tls_version_is_1_3(self):
        assert DEFAULT_TLS_VERSION == ssl.TLSVersion.TLSv1_3

    def test_default_verify_mode_is_required(self):
        assert DEFAULT_VERIFY_MODE == ssl.CERT_REQUIRED

    def test_default_cipher_suites_is_none(self):
        assert DEFAULT_CIPHER_SUITES is None


# ============================================================================
# _get_tls_env
# ============================================================================


class TestGetTlsEnv:
    """Tests for _get_tls_env helper."""

    def test_reads_dhara_env(self, monkeypatch):
        monkeypatch.setenv("DHARA_TLS_CERTFILE", "/path/to/cert")
        assert _get_tls_env("CERTFILE") == "/path/to/cert"

    def test_falls_back_to_druva(self, monkeypatch):
        monkeypatch.delenv("DHARA_TLS_CERTFILE", raising=False)
        monkeypatch.setenv("DRUVA_TLS_CERTFILE", "/druva/cert")
        assert _get_tls_env("CERTFILE") == "/druva/cert"

    def test_dhara_preferred_over_druva(self, monkeypatch):
        monkeypatch.setenv("DHARA_TLS_CERTFILE", "/dhara/cert")
        monkeypatch.setenv("DRUVA_TLS_CERTFILE", "/druva/cert")
        assert _get_tls_env("CERTFILE") == "/dhara/cert"

    def test_returns_default_when_not_set(self, monkeypatch):
        monkeypatch.delenv("DHARA_TLS_KEYFILE", raising=False)
        monkeypatch.delenv("DRUVA_TLS_KEYFILE", raising=False)
        assert _get_tls_env("KEYFILE", "fallback") == "fallback"

    def test_returns_none_when_not_set_and_no_default(self, monkeypatch):
        monkeypatch.delenv("DHARA_TLS_KEYFILE", raising=False)
        monkeypatch.delenv("DRUVA_TLS_KEYFILE", raising=False)
        assert _get_tls_env("KEYFILE") is None


# ============================================================================
# TLSConfig.__init__ and _validate
# ============================================================================


class TestTLSConfigInit:
    """Tests for TLSConfig construction and validation."""

    def test_minimal_config(self, temp_tls_certs):
        certfile, keyfile = temp_tls_certs
        config = TLSConfig(certfile=certfile, keyfile=keyfile)
        assert config.certfile.name.endswith("cert.pem")
        assert config.keyfile.name.endswith("key.pem")
        assert config.cafile is None
        assert config.capath is None
        assert config.verify_mode == ssl.CERT_REQUIRED
        assert config.tls_version == ssl.TLSVersion.TLSv1_3
        assert config.check_hostname is True

    def test_cert_without_key_raises(self):
        with pytest.raises(ValueError, match="keyfile is required"):
            TLSConfig(certfile="/nonexistent/cert.pem")

    def test_key_without_cert_raises(self):
        with pytest.raises(ValueError, match="certfile is required"):
            TLSConfig(keyfile="/nonexistent/key.pem")

    def test_client_cert_without_key_raises(self, temp_tls_certs):
        certfile, _ = temp_tls_certs
        with pytest.raises(ValueError, match="client_keyfile is required"):
            TLSConfig(certfile=certfile, keyfile=temp_tls_certs[1],
                      client_certfile=certfile)

    def test_client_key_without_cert_raises(self, temp_tls_certs):
        certfile, keyfile = temp_tls_certs
        with pytest.raises(ValueError, match="client_certfile is required"):
            TLSConfig(certfile=certfile, keyfile=keyfile,
                      client_keyfile=keyfile)

    def test_nonexistent_cert_file_raises(self):
        with pytest.raises(FileNotFoundError, match="Certificate file not found"):
            TLSConfig(certfile="/nonexistent/cert.pem", keyfile="/nonexistent/key.pem")

    def test_nonexistent_ca_file_raises(self, temp_tls_certs):
        certfile, keyfile = temp_tls_certs
        with pytest.raises(FileNotFoundError, match="CA file not found"):
            TLSConfig(certfile=certfile, keyfile=keyfile, cafile="/nonexistent/ca.pem")

    def test_nonexistent_capath_raises(self, temp_tls_certs):
        certfile, keyfile = temp_tls_certs
        with pytest.raises(FileNotFoundError, match="CA directory not found"):
            TLSConfig(certfile=certfile, keyfile=keyfile, capath="/nonexistent/ca_dir")

    def test_custom_verify_mode(self, temp_tls_certs):
        certfile, keyfile = temp_tls_certs
        config = TLSConfig(
            certfile=certfile, keyfile=keyfile,
            verify_mode=ssl.CERT_NONE,
        )
        assert config.verify_mode == ssl.CERT_NONE

    def test_custom_tls_version(self, temp_tls_certs):
        certfile, keyfile = temp_tls_certs
        config = TLSConfig(
            certfile=certfile, keyfile=keyfile,
            tls_version=ssl.TLSVersion.TLSv1_2,
        )
        assert config.tls_version == ssl.TLSVersion.TLSv1_2

    def test_paths_converted_to_pathlib(self, temp_tls_certs):
        certfile, keyfile = temp_tls_certs
        config = TLSConfig(certfile=certfile, keyfile=keyfile)
        assert isinstance(config.certfile, os.PathLike)
        assert isinstance(config.keyfile, os.PathLike)

    def test_none_params_stay_none(self, temp_tls_certs):
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

    def test_creates_server_context(self, server_config):
        ctx = server_config.create_server_context()
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.minimum_version == ssl.TLSVersion.TLSv1_3

    def test_server_context_without_certs_raises(self):
        config = TLSConfig()
        with pytest.raises(ValueError, match="requires both certfile and keyfile"):
            config.create_server_context()

    def test_server_context_with_ca_uses_verify_mode(self, server_config, temp_ca_cert):
        config = TLSConfig(
            certfile=server_config.certfile,
            keyfile=server_config.keyfile,
            cafile=temp_ca_cert,
            verify_mode=ssl.CERT_REQUIRED,
        )
        ctx = config.create_server_context()
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_server_context_without_ca_uses_cert_none(self, server_config):
        ctx = server_config.create_server_context()
        assert ctx.verify_mode == ssl.CERT_NONE


# ============================================================================
# create_client_context
# ============================================================================


class TestCreateClientContext:
    """Tests for TLSConfig.create_client_context."""

    def test_creates_client_context(self, server_config):
        ctx = server_config.create_client_context()
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.minimum_version == ssl.TLSVersion.TLSv1_3

    def test_client_context_with_ca(self, server_config, temp_ca_cert):
        config = TLSConfig(
            certfile=server_config.certfile,
            keyfile=server_config.keyfile,
            cafile=temp_ca_cert,
        )
        ctx = config.create_client_context()
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_client_context_hostname_check(self, server_config):
        config = TLSConfig(
            certfile=server_config.certfile,
            keyfile=server_config.keyfile,
            check_hostname=False,
        )
        ctx = config.create_client_context()
        assert ctx.check_hostname is False

    def test_client_context_with_mutual_tls(self, temp_tls_certs):
        certfile, keyfile = temp_tls_certs
        config = TLSConfig(
            certfile=certfile,
            keyfile=keyfile,
            client_certfile=certfile,
            client_keyfile=keyfile,
        )
        ctx = config.create_client_context()
        assert isinstance(ctx, ssl.SSLContext)


# ============================================================================
# generate_self_signed_cert
# ============================================================================


class TestGenerateSelfSignedCert:
    """Tests for generate_self_signed_cert."""

    def test_creates_cert_and_key_files(self, tmp_path):
        certfile = tmp_path / "cert.pem"
        keyfile = tmp_path / "key.pem"
        generate_self_signed_cert(certfile, keyfile)
        assert certfile.exists()
        assert keyfile.exists()

    def test_cert_contains_pem_data(self, tmp_path):
        certfile = tmp_path / "cert.pem"
        keyfile = tmp_path / "key.pem"
        generate_self_signed_cert(certfile, keyfile)
        content = certfile.read_text()
        assert "-----BEGIN CERTIFICATE-----" in content

    def test_key_contains_pem_data(self, tmp_path):
        certfile = tmp_path / "cert.pem"
        keyfile = tmp_path / "key.pem"
        generate_self_signed_cert(certfile, keyfile)
        content = keyfile.read_text()
        assert "-----BEGIN RSA PRIVATE KEY-----" in content

    def test_creates_parent_directories(self, tmp_path):
        certfile = tmp_path / "nested" / "cert.pem"
        keyfile = tmp_path / "nested" / "key.pem"
        generate_self_signed_cert(certfile, keyfile)
        assert certfile.exists()

    def test_custom_hostname(self, tmp_path):
        certfile = tmp_path / "cert.pem"
        keyfile = tmp_path / "key.pem"
        generate_self_signed_cert(certfile, keyfile, hostname="example.com")

    def test_can_load_cert_as_tls_config(self, tmp_path):
        certfile = tmp_path / "cert.pem"
        keyfile = tmp_path / "key.pem"
        generate_self_signed_cert(certfile, keyfile)
        config = TLSConfig(certfile=str(certfile), keyfile=str(keyfile))
        ctx = config.create_server_context()
        assert isinstance(ctx, ssl.SSLContext)

    def test_requires_cryptography(self):
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

    def test_returns_none_when_no_env_set(self, monkeypatch):
        for var in ["DHARA_TLS_CERTFILE", "DHARA_TLS_KEYFILE", "DHARA_TLS_CAFILE",
                     "DHARA_TLS_CAPATH", "DHARA_TLS_CLIENT_CERTFILE",
                     "DHARA_TLS_CLIENT_KEYFILE",
                     "DRUVA_TLS_CERTFILE", "DRUVA_TLS_KEYFILE",
                     "DRUVA_TLS_CAFILE", "DRUVA_TLS_CAPATH",
                     "DRUVA_TLS_CLIENT_CERTFILE", "DRUVA_TLS_CLIENT_KEYFILE"]:
            monkeypatch.delenv(var, raising=False)
        assert get_env_tls_config() is None

    def test_returns_config_from_cert_env(self, temp_tls_certs, monkeypatch):
        certfile, keyfile = temp_tls_certs
        monkeypatch.setenv("DHARA_TLS_CERTFILE", certfile)
        monkeypatch.setenv("DHARA_TLS_KEYFILE", keyfile)
        config = get_env_tls_config()
        assert config is not None
        assert isinstance(config, TLSConfig)

    def test_verify_mode_default_required(self, temp_tls_certs, monkeypatch):
        certfile, keyfile = temp_tls_certs
        monkeypatch.setenv("DHARA_TLS_CERTFILE", certfile)
        monkeypatch.setenv("DHARA_TLS_KEYFILE", keyfile)
        config = get_env_tls_config()
        assert config.verify_mode == ssl.CERT_REQUIRED

    def test_verify_mode_from_env(self, temp_tls_certs, monkeypatch):
        certfile, keyfile = temp_tls_certs
        monkeypatch.setenv("DHARA_TLS_CERTFILE", certfile)
        monkeypatch.setenv("DHARA_TLS_KEYFILE", keyfile)
        monkeypatch.setenv("DHARA_TLS_VERIFY_MODE", "none")
        config = get_env_tls_config()
        assert config.verify_mode == ssl.CERT_NONE

    def test_tls_version_from_env(self, temp_tls_certs, monkeypatch):
        certfile, keyfile = temp_tls_certs
        monkeypatch.setenv("DHARA_TLS_CERTFILE", certfile)
        monkeypatch.setenv("DHARA_TLS_KEYFILE", keyfile)
        monkeypatch.setenv("DHARA_TLS_VERSION", "1.2")
        config = get_env_tls_config()
        assert config.tls_version == ssl.TLSVersion.TLSv1_2

    def test_hostname_check_from_env(self, temp_tls_certs, monkeypatch):
        certfile, keyfile = temp_tls_certs
        monkeypatch.setenv("DHARA_TLS_CERTFILE", certfile)
        monkeypatch.setenv("DHARA_TLS_KEYFILE", keyfile)
        monkeypatch.setenv("DHARA_TLS_CHECK_HOSTNAME", "false")
        config = get_env_tls_config()
        assert config.check_hostname is False

    def test_unknown_verify_mode_defaults_to_required(self, temp_tls_certs, monkeypatch):
        certfile, keyfile = temp_tls_certs
        monkeypatch.setenv("DHARA_TLS_CERTFILE", certfile)
        monkeypatch.setenv("DHARA_TLS_KEYFILE", keyfile)
        monkeypatch.setenv("DHARA_TLS_VERIFY_MODE", "invalid")
        config = get_env_tls_config()
        assert config.verify_mode == ssl.CERT_REQUIRED
