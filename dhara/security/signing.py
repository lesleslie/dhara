"""
Cryptographic object signing for dhara.

Provides HMAC-based signing to detect tampering and authenticate data.
Lighter alternative to full TLS/SSL encryption.

Uses cryptography.hazmat for HMAC-SHA256 signing.
"""

import os

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, hmac
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class ObjectSigner:
    """Signs and verifies serialized objects using HMAC-SHA256.

    This provides:
    - Tamper detection: Any modification of data invalidates signature
    - Authentication: Only those with the signing key can produce valid signatures
    - No encryption: Data remains readable (use TLS/SSL separately if needed)

    Example:
        signer = ObjectSigner.from_password(b"my-secret-password")
        data = b"serialized object data"
        signed = signer.sign(data)
        # Later...
        try:
            verified = signer.verify(signed)
        except InvalidSignature:
            print("Data was tampered with!")
    """

    def __init__(self, key: bytes):
        """Initialize signer with HMAC key.

        Args:
            key: 32-byte (256-bit) HMAC key. Generate with generate_key().

        Raises:
            ValueError: If key is not 32 bytes
        """
        if len(key) != 32:
            raise ValueError(f"HMAC key must be 32 bytes, got {len(key)}")

        self.key = key
        self._backend = default_backend()

    @classmethod
    def from_password(
        cls, password: bytes, salt: bytes | None = None
    ) -> "ObjectSigner":
        """Create signer from password using PBKDF2 key derivation.

        This is the recommended way to create a signer from a user-provided
        password or configuration string.

        Args:
            password: Password bytes (use password.encode() if str)
            salt: Optional 16-byte salt. Generates random salt if None.

        Returns:
            ObjectSigner instance with derived key
        """
        if salt is None:
            salt = os.urandom(16)

        if len(salt) != 16:
            raise ValueError(f"Salt must be 16 bytes, got {len(salt)}")

        # Derive 32-byte key from password using PBKDF2-HMAC-SHA256
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,  # OWASP recommended minimum
            backend=default_backend(),
        )

        key = kdf.derive(password)
        return cls(key)

    @classmethod
    def from_file(cls, path: str) -> "ObjectSigner":
        """Load signer key from file.

        Args:
            path: Path to file containing 32-byte key

        Returns:
            ObjectSigner instance

        Raises:
            FileNotFoundError: If key file doesn't exist
            ValueError: If key file is invalid
        """
        with open(path, "rb") as f:
            key = f.read()

        if len(key) != 32:
            raise ValueError(f"Key file must contain 32 bytes, got {len(key)}")

        return cls(key)

    @classmethod
    def generate_key(cls) -> bytes:
        """Generate cryptographically random 32-byte HMAC key.

        Returns:
            32-byte key suitable for ObjectSigner
        """
        return os.urandom(32)

    @classmethod
    def generate_key_file(cls, path: str) -> None:
        """Generate and save a new random key to file.

        Args:
            path: Path where key file should be created
        """
        key = cls.generate_key()

        # Create parent directories if needed
        os.makedirs(
            os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True
        )

        with open(path, "wb") as f:
            f.write(key)

        # Restrict file permissions to owner-only
        os.chmod(path, 0o600)

    def sign(self, data: bytes) -> bytes:
        """Sign data and return data + signature.

        Args:
            data: Bytes to sign

        Returns:
            Signed data (original data + 32-byte HMAC-SHA256 signature appended)
        """
        h = hmac.HMAC(self.key, hashes.SHA256(), backend=self._backend)
        h.update(data)
        signature = h.finalize()

        # Return data + signature
        return data + signature

    def verify(self, signed_data: bytes) -> bytes:
        """Verify signed data and return original data.

        Args:
            signed_data: Data with signature appended (from sign())

        Returns:
            Original data without signature

        Raises:
            InvalidSignature: If signature verification fails
            ValueError: If data is too short to contain signature
        """
        if len(signed_data) < 32:
            raise ValueError("Signed data must be at least 32 bytes (data + signature)")

        # Split data and signature
        data = signed_data[:-32]
        signature = signed_data[-32:]

        # Verify signature
        h = hmac.HMAC(self.key, hashes.SHA256(), backend=self._backend)
        h.update(data)

        try:
            h.verify(signature)
        except InvalidSignature:
            raise InvalidSignature(
                "HMAC verification failed. Data may have been tampered with."
            )

        return data

    def sign_record(self, oid: bytes, data: bytes, refs: bytes) -> bytes:
        """Sign a storage record (OID + data + refs).

        This is the main method for signing dhara storage records.

        Args:
            oid: Object ID (8 bytes)
            data: Serialized object state
            refs: Serialized reference list

        Returns:
            Signed record (oid + data + refs + signature)
        """
        # Sign the concatenated record
        record = oid + data + refs
        return self.sign(record)

    def verify_record(self, signed_record: bytes) -> tuple[bytes, bytes, bytes]:
        """Verify and extract signed storage record.

        Args:
            signed_record: Signed record from sign_record()

        Returns:
            Tuple of (oid, data, refs)

        Raises:
            InvalidSignature: If record verification fails
        """
        # Verify and get record without signature
        record = self.verify(signed_record)

        # Split into components (OID is 8 bytes)
        if len(record) < 8:
            raise ValueError("Record too short to contain OID")

        oid = record[:8]
        data_and_refs = record[8:]

        # Note: We don't split data/refs here because the serialization
        # format uses length prefixes. The caller (Storage) handles that.
        # We just return (oid, data_and_refs) or use the pack_record format.

        # For now, return the full record and let caller unpack it
        return oid, data_and_refs, b""  # Third element ignored, use full record


class SignedStorage:
    """Wrapper for Storage that adds cryptographic signing.

    This wraps any Storage implementation to automatically sign all
    records on storage and verify on load.

    Example:
        from dhara.storage import FileStorage
        from dhara.security.signing import SignedStorage, ObjectSigner

        signer = ObjectSigner.from_password(b"my-secret-key")
        base_storage = FileStorage("data.dhara")
        storage = SignedStorage(base_storage, signer)

        # Now all operations are automatically signed/verified
        data = storage.load(oid)  # Verifies signature
        storage.store(oid, record)  # Signs before storing
    """

    def __init__(self, storage, signer: ObjectSigner):
        """Initialize signed storage wrapper.

        Args:
            storage: Base Storage instance to wrap
            signer: ObjectSigner instance for signing/verification
        """
        self._storage = storage
        self._signer = signer

    def load(self, oid: bytes) -> bytes:
        """Load and verify signed record.

        Args:
            oid: Object ID to load

        Returns:
            Verified record data

        Raises:
            InvalidSignature: If record signature is invalid
            KeyError: If OID not found
        """
        signed_record = self._storage.load(oid)
        return self._signer.verify(signed_record)

    def store(self, oid: bytes, record: bytes) -> None:
        """Sign and store record.

        Args:
            oid: Object ID
            record: Record data to sign and store
        """
        signed_record = self._signer.sign(record)
        self._storage.store(oid, signed_record)

    def __getattr__(self, name):
        """Delegate all other attributes to wrapped storage."""
        return getattr(self._storage, name)


# Convenience function for common use case
def create_signer_from_env(env_var: str = "DHARA_SIGNING_KEY") -> ObjectSigner:
    """Create ObjectSigner from environment variable.

    Environment variable should contain:
    - Path to key file (if starts with / or .)
    - Direct password (otherwise)

    Args:
        env_var: Name of environment variable

    Returns:
        ObjectSigner instance

    Raises:
        ValueError: If env var is not set
    """
    import os

    value = os.environ.get(env_var)

    if not value:
        raise ValueError(f"Environment variable {env_var} not set")

    # Check if it's a file path
    if value.startswith("/") or value.startswith("."):
        return ObjectSigner.from_file(value)
    else:
        # Treat as password
        return ObjectSigner.from_password(value.encode())


__all__ = [
    "ObjectSigner",
    "SignedStorage",
    "create_signer_from_env",
]
