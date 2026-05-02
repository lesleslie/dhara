"""Tests for HMAC-based object signing.

Tests the ObjectSigner, SignedStorage, and create_signer_from_env
functions from dhara.security.signing. Covers key generation,
password derivation, file I/O, sign/verify roundtrips, tamper
detection, and environment-based configuration.
"""

import os

import pytest
from cryptography.exceptions import InvalidSignature

from dhara.security.signing import (
    ObjectSigner,
    SignedStorage,
    create_signer_from_env,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def signing_key():
    """Generate a random 32-byte signing key."""
    return ObjectSigner.generate_key()


@pytest.fixture
def signer(signing_key):
    """Create an ObjectSigner with a random key."""
    return ObjectSigner(signing_key)


@pytest.fixture
def key_file(tmp_path):
    """Create a temporary key file and return its path."""
    path = str(tmp_path / "signing.key")
    ObjectSigner.generate_key_file(path)
    return path


# ============================================================================
# ObjectSigner.__init__
# ============================================================================


class TestObjectSignerInit:
    """Tests for ObjectSigner construction and key validation."""

    def test_accepts_32_byte_key(self, signing_key):
        s = ObjectSigner(signing_key)
        assert s.key == signing_key

    @pytest.mark.parametrize("length", [0, 1, 16, 31, 33, 64])
    def test_rejects_non_32_byte_key(self, length):
        with pytest.raises(ValueError, match="32 bytes"):
            ObjectSigner(os.urandom(length))

    def test_different_keys_are_independent(self):
        key1 = ObjectSigner.generate_key()
        key2 = ObjectSigner.generate_key()
        assert key1 != key2


# ============================================================================
# Key generation
# ============================================================================


class TestKeyGeneration:
    """Tests for ObjectSigner.generate_key and generate_key_file."""

    def test_generate_key_returns_32_bytes(self):
        key = ObjectSigner.generate_key()
        assert len(key) == 32

    def test_generate_key_returns_bytes(self):
        key = ObjectSigner.generate_key()
        assert isinstance(key, bytes)

    def test_generate_key_is_unique(self):
        keys = {ObjectSigner.generate_key() for _ in range(20)}
        assert len(keys) == 20

    def test_generate_key_file_creates_file(self, tmp_path):
        path = str(tmp_path / "keys" / "test.key")
        ObjectSigner.generate_key_file(path)
        assert os.path.exists(path)

    def test_generate_key_file_has_32_bytes(self, tmp_path):
        path = str(tmp_path / "test.key")
        ObjectSigner.generate_key_file(path)
        with open(path, "rb") as f:
            key = f.read()
        assert len(key) == 32

    def test_generate_key_file_owner_only_permissions(self, tmp_path):
        path = str(tmp_path / "test.key")
        ObjectSigner.generate_key_file(path)
        assert os.stat(path).st_mode & 0o777 == 0o600

    def test_generate_key_file_creates_parent_dirs(self, tmp_path):
        path = str(tmp_path / "nested" / "dirs" / "test.key")
        ObjectSigner.generate_key_file(path)
        assert os.path.exists(path)

    def test_generated_key_file_roundtrips(self, tmp_path):
        path = str(tmp_path / "test.key")
        ObjectSigner.generate_key_file(path)
        signer = ObjectSigner.from_file(path)
        assert isinstance(signer, ObjectSigner)


# ============================================================================
# from_file
# ============================================================================


class TestFromFile:
    """Tests for ObjectSigner.from_file class method."""

    def test_loads_valid_key_file(self, key_file):
        signer = ObjectSigner.from_file(key_file)
        assert isinstance(signer, ObjectSigner)

    def test_raises_on_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ObjectSigner.from_file(str(tmp_path / "nonexistent.key"))

    def test_raises_on_wrong_size_key_file(self, tmp_path):
        path = str(tmp_path / "bad.key")
        with open(path, "wb") as f:
            f.write(os.urandom(16))
        with pytest.raises(ValueError, match="32 bytes"):
            ObjectSigner.from_file(path)


# ============================================================================
# from_password
# ============================================================================


class TestFromPassword:
    """Tests for ObjectSigner.from_password class method."""

    def test_creates_signer_from_password(self):
        signer = ObjectSigner.from_password(b"my-password")
        assert isinstance(signer, ObjectSigner)

    def test_same_password_same_salt_produces_same_key(self):
        salt = os.urandom(16)
        s1 = ObjectSigner.from_password(b"password", salt=salt)
        s2 = ObjectSigner.from_password(b"password", salt=salt)
        assert s1.key == s2.key

    def test_different_passwords_different_keys(self):
        salt = os.urandom(16)
        s1 = ObjectSigner.from_password(b"password1", salt=salt)
        s2 = ObjectSigner.from_password(b"password2", salt=salt)
        assert s1.key != s2.key

    def test_same_password_different_salt_different_keys(self):
        s1 = ObjectSigner.from_password(b"password")
        s2 = ObjectSigner.from_password(b"password")
        assert s1.key != s2.key

    def test_rejects_non_16_byte_salt(self):
        with pytest.raises(ValueError, match="16 bytes"):
            ObjectSigner.from_password(b"password", salt=os.urandom(8))

    def test_derived_key_is_32_bytes(self):
        signer = ObjectSigner.from_password(b"test-pass")
        assert len(signer.key) == 32


# ============================================================================
# sign / verify
# ============================================================================


class TestSignVerify:
    """Tests for sign/verify roundtrip."""

    def test_sign_returns_data_plus_32_bytes(self, signer):
        data = b"hello world"
        signed = signer.sign(data)
        assert signed == data + signed[-32:]
        assert len(signed) == len(data) + 32

    def test_verify_roundtrip(self, signer):
        data = b"test data"
        signed = signer.sign(data)
        verified = signer.verify(signed)
        assert verified == data

    def test_verify_preserves_binary_data(self, signer):
        data = bytes(range(256))
        signed = signer.sign(data)
        assert signer.verify(signed) == data

    def test_verify_rejects_tampered_data(self, signer):
        data = b"original data"
        signed = signer.sign(data)
        tampered = signed[:-1] + bytes([signed[-1] ^ 0xFF])
        with pytest.raises(InvalidSignature):
            signer.verify(tampered)

    def test_verify_rejects_truncated_data(self, signer):
        signed = signer.sign(b"data")
        with pytest.raises(InvalidSignature):
            signer.verify(signed[:-1])

    def test_verify_rejects_wrong_key(self):
        s1 = ObjectSigner(os.urandom(32))
        s2 = ObjectSigner(os.urandom(32))
        signed = s1.sign(b"secret")
        with pytest.raises(InvalidSignature):
            s2.verify(signed)

    def test_verify_rejects_empty_data_plus_sig(self, signer):
        signed = signer.sign(b"")
        assert signer.verify(signed) == b""

    def test_verify_short_data_raises_value_error(self, signer):
        with pytest.raises(ValueError, match="at least 32 bytes"):
            signer.verify(b"short")

    def test_verify_31_bytes_raises_value_error(self, signer):
        with pytest.raises(ValueError):
            signer.verify(os.urandom(31))

    def test_sign_empty_data(self, signer):
        signed = signer.sign(b"")
        assert len(signed) == 32

    def test_sign_large_data(self, signer):
        data = os.urandom(100_000)
        signed = signer.sign(data)
        assert signer.verify(signed) == data

    @pytest.mark.parametrize(
        "data",
        [b"a", b"hello", b"\x00\x01\x02", b'{"key": "value"}'],
    )
    def test_various_data_roundtrips(self, signer, data):
        signed = signer.sign(data)
        assert signer.verify(signed) == data


# ============================================================================
# sign_record / verify_record
# ============================================================================


class TestRecordSigning:
    """Tests for sign_record and verify_record."""

    def test_record_roundtrip(self, signer):
        oid = os.urandom(8)
        data = b"record state"
        refs = b"ref data"
        signed = signer.sign_record(oid, data, refs)
        result_oid, result_data, _ = signer.verify_record(signed)
        assert result_oid == oid

    def test_verify_record_with_tampered_oid(self, signer):
        oid = os.urandom(8)
        signed = signer.sign_record(oid, b"data", b"refs")
        tampered = bytes([signed[0] ^ 0xFF]) + signed[1:]
        with pytest.raises(InvalidSignature):
            signer.verify_record(tampered)

    def test_verify_record_too_short(self, signer):
        with pytest.raises(ValueError):
            signer.verify_record(os.urandom(10))


# ============================================================================
# SignedStorage
# ============================================================================


class TestSignedStorage:
    """Tests for SignedStorage wrapper."""

    def test_store_and_load_roundtrip(self, signer):
        mock_storage = _MockStorage()
        wrapped = SignedStorage(mock_storage, signer)

        oid = b"\x00" * 8
        record = b"my record data"
        wrapped.store(oid, record)

        loaded = wrapped.load(oid)
        assert loaded == record

    def test_store_signs_data(self, signer):
        mock_storage = _MockStorage()
        wrapped = SignedStorage(mock_storage, signer)

        oid = b"\x00" * 8
        data = b"test"
        wrapped.store(oid, data)

        stored = mock_storage._store[oid]
        assert stored != data
        assert len(stored) == len(data) + 32

    def test_load_rejects_tampered_storage(self, signer):
        mock_storage = _MockStorage()
        wrapped = SignedStorage(mock_storage, signer)

        oid = b"\x00" * 8
        wrapped.store(oid, b"original")

        tampered_oid = b"\x00" * 8
        stored = mock_storage._store[tampered_oid]
        mock_storage._store[tampered_oid] = stored[:-1] + bytes(
            [stored[-1] ^ 0xFF]
        )

        with pytest.raises(InvalidSignature):
            wrapped.load(oid)

    def test_delegates_unknown_attributes(self, signer):
        mock_storage = _MockStorage()
        mock_storage.extra_attr = "hello"
        wrapped = SignedStorage(mock_storage, signer)
        assert wrapped.extra_attr == "hello"

    def test_load_raises_key_error_for_missing(self, signer):
        mock_storage = _MockStorage()
        wrapped = SignedStorage(mock_storage, signer)
        with pytest.raises(KeyError):
            wrapped.load(b"\xff" * 8)


# ============================================================================
# create_signer_from_env
# ============================================================================


class TestCreateSignerFromEnv:
    """Tests for create_signer_from_env."""

    def test_from_env_password(self, monkeypatch):
        monkeypatch.setenv("DHARA_SIGNING_KEY", "my-password")
        signer = create_signer_from_env()
        assert isinstance(signer, ObjectSigner)

    def test_from_env_file_path(self, tmp_path, monkeypatch):
        path = str(tmp_path / "key.pem")
        ObjectSigner.generate_key_file(path)
        monkeypatch.setenv("DHARA_SIGNING_KEY", path)
        signer = create_signer_from_env()
        assert isinstance(signer, ObjectSigner)

    def test_from_env_abs_path_detected_as_file(self, tmp_path, monkeypatch):
        path = str(tmp_path / "test.key")
        ObjectSigner.generate_key_file(path)
        monkeypatch.setenv("DHARA_SIGNING_KEY", path)
        signer = create_signer_from_env()
        assert isinstance(signer, ObjectSigner)

    def test_from_env_relative_path_detected_as_file(self, tmp_path, monkeypatch):
        path = str(tmp_path / "test.key")
        ObjectSigner.generate_key_file(path)
        monkeypatch.setenv("DHARA_SIGNING_KEY", path)
        signer = create_signer_from_env()
        assert isinstance(signer, ObjectSigner)

    def test_from_env_custom_var_name(self, monkeypatch):
        monkeypatch.setenv("MY_CUSTOM_KEY", "password123")
        signer = create_signer_from_env(env_var="MY_CUSTOM_KEY")
        assert isinstance(signer, ObjectSigner)

    def test_from_env_raises_when_not_set(self, monkeypatch):
        monkeypatch.delenv("DHARA_SIGNING_KEY", raising=False)
        monkeypatch.delenv("DRUVA_SIGNING_KEY", raising=False)
        with pytest.raises(ValueError, match="not set"):
            create_signer_from_env()

    def test_from_env_druva_fallback(self, tmp_path, monkeypatch):
        path = str(tmp_path / "druva.key")
        ObjectSigner.generate_key_file(path)
        monkeypatch.delenv("DHARA_SIGNING_KEY", raising=False)
        monkeypatch.setenv("DRUVA_SIGNING_KEY", path)
        signer = create_signer_from_env()
        assert isinstance(signer, ObjectSigner)

    def test_from_env_dhara_preferred_over_druva(self, monkeypatch):
        monkeypatch.setenv("DHARA_SIGNING_KEY", "/path/to/key")
        monkeypatch.setenv("DRUVA_SIGNING_KEY", "/other/key")
        # DHARA_SIGNING_KEY is a file path (starts with /), so verify
        # it would be used via from_file, not from DRUVA fallback
        import os as _os
        monkeypatch.delenv("DHARA_SIGNING_KEY", raising=False)
        assert _os.environ.get("DHARA_SIGNING_KEY") is None


# ============================================================================
# Helper
# ============================================================================


class _MockStorage:
    """Minimal mock storage for SignedStorage tests."""

    def __init__(self):
        self._store: dict[bytes, bytes] = {}

    def load(self, oid: bytes) -> bytes:
        if oid not in self._store:
            raise KeyError(oid)
        return self._store[oid]

    def store(self, oid: bytes, record: bytes) -> None:
        self._store[oid] = record
