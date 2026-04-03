"""Tests for cryptographic object signing."""

import os
import tempfile

import pytest
from cryptography.exceptions import InvalidSignature

from dhara.security.signing import ObjectSigner, SignedStorage, create_signer_from_env
from dhara.storage import MemoryStorage


class TestObjectSigner:
    def test_generate_key(self):
        """Test key generation produces 32-byte keys."""
        key1 = ObjectSigner.generate_key()
        key2 = ObjectSigner.generate_key()

        assert len(key1) == 32
        assert len(key2) == 32
        assert key1 != key2  # Keys should be random

    def test_init_with_invalid_key(self):
        """Test that signer rejects keys of wrong size."""
        with pytest.raises(ValueError):
            ObjectSigner(b"too_short")

        with pytest.raises(ValueError):
            ObjectSigner(b"way_too_long_" * 10)

    def test_sign_and_verify(self):
        """Test basic sign and verify workflow."""
        key = ObjectSigner.generate_key()
        signer = ObjectSigner(key)

        data = b"Hello, World!"
        signed = signer.sign(data)

        # Signed data should be original + 32-byte signature
        assert len(signed) == len(data) + 32
        assert signed[:-32] == data

        # Verification should work
        verified = signer.verify(signed)
        assert verified == data

    def test_verify_tampered_data(self):
        """Test that tampering is detected."""
        key = ObjectSigner.generate_key()
        signer = ObjectSigner(key)

        data = b"Original data"
        signed = signer.sign(data)

        # Tamper with the data
        tampered = signed[:-32] + b"X" + signed[-31:]

        with pytest.raises(InvalidSignature):
            signer.verify(tampered)

    def test_verify_wrong_signature(self):
        """Test that wrong signature is rejected."""
        key1 = ObjectSigner.generate_key()
        key2 = ObjectSigner.generate_key()

        signer1 = ObjectSigner(key1)
        signer2 = ObjectSigner(key2)

        data = b"Test data"
        signed_with_key1 = signer1.sign(data)

        # Try to verify with different key
        with pytest.raises(InvalidSignature):
            signer2.verify(signed_with_key1)

    def test_from_password(self):
        """Test creating signer from password."""
        password = b"my-secure-password"

        signer = ObjectSigner.from_password(password)

        # Should have created a valid signer
        data = b"Test"
        signed = signer.sign(data)
        verified = signer.verify(signed)
        assert verified == data

    def test_from_password_with_custom_salt(self):
        """Test PBKDF2 with custom salt for reproducible keys."""
        password = b"password"
        salt = b"0123456789ABCDEF"  # 16 bytes

        signer1 = ObjectSigner.from_password(password, salt)
        signer2 = ObjectSigner.from_password(password, salt)

        # Same password + salt should produce same key
        data = b"Test"
        signed1 = signer1.sign(data)
        signed2 = signer2.sign(data)

        # Can verify across instances
        assert signer1.verify(signed2) == data
        assert signer2.verify(signed1) == data

    def test_from_password_requires_correct_salt_length(self):
        """Test that salt must be 16 bytes."""
        with pytest.raises(ValueError):
            ObjectSigner.from_password(b"password", salt=b"too_short")

    def test_key_file_roundtrip(self):
        """Test saving and loading key from file."""
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            key_path = f.name

        try:
            # Generate and save key
            ObjectSigner.generate_key_file(key_path)

            # Load key from file
            signer = ObjectSigner.from_file(key_path)

            # Should work correctly
            data = b"Test data"
            signed = signer.sign(data)
            verified = signer.verify(signed)
            assert verified == data

            # Check file permissions
            st = os.stat(key_path)
            # File should be owner-readable/writable only (0600)
            assert st.st_mode & 0o777 == 0o600
        finally:
            os.unlink(key_path)

    def test_sign_record(self):
        """Test signing storage records."""
        key = ObjectSigner.generate_key()
        signer = ObjectSigner(key)

        oid = b"\x00" * 8
        data = b"serialized_object_state"
        refs = b"references"

        signed = signer.sign_record(oid, data, refs)

        # Should be record + 32-byte signature
        assert len(signed) == len(oid + data + refs) + 32

    def test_verify_short_data(self):
        """Test that verify rejects data that's too short."""
        key = ObjectSigner.generate_key()
        signer = ObjectSigner(key)

        with pytest.raises(ValueError):
            signer.verify(b"too_short")

    def test_create_signer_from_env_not_set(self):
        """Test that env var must be set."""
        if "DRUVA_SIGNING_KEY" in os.environ:
            del os.environ["DRUVA_SIGNING_KEY"]

        with pytest.raises(ValueError):
            create_signer_from_env()

    def test_create_signer_from_env_with_password(self):
        """Test creating signer from env var password."""
        os.environ["DRUVA_SIGNING_KEY"] = "test-password"

        try:
            signer = create_signer_from_env()
            data = b"Test"
            signed = signer.sign(data)
            assert signer.verify(signed) == data
        finally:
            del os.environ["DRUVA_SIGNING_KEY"]


class TestSignedStorage:
    def test_signed_storage_wraps_base_storage(self):
        """Test that SignedStorage wraps and delegates to base storage."""
        # MemoryStorage already imported at top of file

        key = ObjectSigner.generate_key()
        signer = ObjectSigner(key)
        base_storage = MemoryStorage()
        storage = SignedStorage(base_storage, signer)

        # Should delegate non-signing methods
        assert hasattr(storage, "new_oid")
        assert hasattr(storage, "begin")
        assert hasattr(storage, "end")

    def test_signed_storage_auto_signs_on_store(self):
        """Test that records are automatically signed on storage."""
        # MemoryStorage already imported at top of file

        key = ObjectSigner.generate_key()
        signer = ObjectSigner(key)
        base_storage = MemoryStorage()
        storage = SignedStorage(base_storage, signer)

        # Begin transaction
        base_storage.begin()

        oid = b"\x00" * 8
        record = b"test_record_data"

        storage.store(oid, record)

        # End transaction to commit
        base_storage.end()

        # Verify the stored data includes signature
        stored = base_storage.load(oid)
        assert len(stored) == len(record) + 32  # data + signature

    def test_signed_storage_verifies_on_load(self):
        """Test that records are automatically verified on load."""
        # MemoryStorage already imported at top of file

        key = ObjectSigner.generate_key()
        signer = ObjectSigner(key)
        base_storage = MemoryStorage()
        storage = SignedStorage(base_storage, signer)

        # Begin transaction
        base_storage.begin()

        oid = b"\x00" * 8
        record = b"test_record_data"

        # Store signed record
        storage.store(oid, record)

        # End transaction to commit
        base_storage.end()

        # Load and verify
        loaded = storage.load(oid)
        assert loaded == record

    def test_signed_storage_detects_tampering(self):
        """Test that tampered records are rejected on load."""
        # MemoryStorage already imported at top of file

        key = ObjectSigner.generate_key()
        signer = ObjectSigner(key)
        base_storage = MemoryStorage()

        # Begin transaction
        base_storage.begin()

        # Store signed record
        oid = b"\x00" * 8
        record = b"test_record_data"
        signed = signer.sign(record)
        base_storage.store(oid, signed)

        # End transaction to commit
        base_storage.end()

        # Begin new transaction for tampering
        base_storage.begin()

        # Tamper with stored record
        original = base_storage.load(oid)
        tampered = original[:-32] + b"X" + original[-31:]
        base_storage.store(oid, tampered)

        # End transaction to commit tampering
        base_storage.end()

        # SignedStorage should detect tampering
        storage = SignedStorage(base_storage, signer)
        with pytest.raises(InvalidSignature):
            storage.load(oid)
