"""
Example usage of Durus secret management with Oneiric
"""

import logging
import sys

from dhara.config.security import SecurityConfig

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    print("=== Durus Secret Management Example ===\n")

    # Initialize security configuration
    print("1. Initializing security configuration...")
    config = SecurityConfig(
        secret_prefix="example/hmac",
        rotation_interval_days=90,
        fallback_enabled=True,  # Enable for this example
        log_security_events=True,
    )

    try:
        # Initialize the configuration
        with config as security_config:
            print("✓ Security configuration initialized")

            # Get security status
            print("\n2. Security status:")
            status = security_config.get_security_status()
            for key, value in status.items():
                print(f"   {key}: {value}")

            # Create and verify signatures
            print("\n3. Testing signature creation and verification...")
            test_messages = [
                b"Hello, world!",
                b"This is a test message",
                b"Durus secret management is secure",
            ]

            for i, message in enumerate(test_messages, 1):
                try:
                    # Create signature
                    signature = security_config.create_signature(message, "sha256")
                    print(f"   ✓ Created signature for message {i}")

                    # Verify signature
                    is_valid = security_config.verify_signature(
                        message, signature, "sha256"
                    )
                    print(
                        f"   ✓ Verified signature {i}: {'Valid' if is_valid else 'Invalid'}"
                    )

                    # Test with wrong message
                    wrong_message = b"This is the wrong message"
                    is_valid_wrong = security_config.verify_signature(
                        wrong_message, signature, "sha256"
                    )
                    print(
                        f"   ✓ Wrong message verification {i}: {'Valid' if is_valid_wrong else 'Invalid'}"
                    )

                except Exception as e:
                    print(f"   ✗ Error with message {i}: {str(e)}")

            # Test different algorithms
            print("\n4. Testing different algorithms...")
            algorithms = ["sha256", "sha384", "sha512"]

            for algorithm in algorithms:
                try:
                    message = f"Testing {algorithm}".encode()
                    signature = security_config.create_signature(message, algorithm)
                    is_valid = security_config.verify_signature(
                        message, signature, algorithm
                    )
                    print(f"   ✓ {algorithm}: {'Valid' if is_valid else 'Invalid'}")
                except Exception as e:
                    print(f"   ✗ {algorithm}: Error - {str(e)}")

            # Test key management
            print("\n5. Testing key management...")
            try:
                # Create backup key
                backup_key_id = security_config.create_backup_key()
                print(f"   ✓ Created backup key: {backup_key_id}")
            except Exception as e:
                print(f"   ✗ Failed to create backup key: {str(e)}")

            try:
                # Clean up expired keys
                cleaned_count = security_config.cleanup_expired_keys()
                print(f"   ✓ Cleaned up {cleaned_count} expired keys")
            except Exception as e:
                print(f"   ✗ Failed to cleanup keys: {str(e)}")

            # Show final status
            print("\n6. Final security status:")
            final_status = security_config.get_security_status()
            if "key_status" in final_status:
                key_status = final_status["key_status"]
                if "signing_key" in key_status:
                    signing_key = key_status["signing_key"]
                    print(f"   Signing key ID: {signing_key['key_id']}")
                    print(f"   Key length: {signing_key['key_length']} bytes")
                    print(f"   Age: {signing_key['age_days']} days")
                    print(f"   Expires: {signing_key['expires_at']}")
                    print(f"   Active: {signing_key['is_active']}")

    except Exception as e:
        print(f"✗ Error: {str(e)}")
        sys.exit(1)

    print("\n=== Example completed successfully! ===")


if __name__ == "__main__":
    main()
