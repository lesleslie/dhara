# Secret Management with Oneiric

This document describes the secret management system in Durus using Oneiric secrets adapters for HMAC signing keys.

## Overview

The secret management system provides secure, automated key management with the following features:

- **256-bit minimum key length enforcement**
- **Automatic key rotation** (default: 90 days)
- **Thread-safe key access** for concurrent operations
- **Fallback key support** during rotation
- **Comprehensive validation** at startup
- **Oneiric integration** for secure secret storage

## Quick Start

### 1. Basic Initialization

```python
from durus.config.security import initialize_security, get_security_config

# Initialize security configuration
config = initialize_security(
    secret_prefix="myapp/hmac",
    rotation_interval_days=90,
    fallback_enabled=False  # Set to True for development/testing
)

# Create a signature
message = b"Hello, world!"
signature = config.create_signature(message, "sha256")

# Verify a signature
is_valid = config.verify_signature(message, signature, "sha256")
```

### 2. Context Manager

```python
from durus.config.security import SecurityConfig

with SecurityConfig(
    secret_prefix="myapp/hmac",
    rotation_interval_days=90
) as security_config:
    # Use security context
    signature = security_config.create_signature(b"Hello!")
    is_valid = security_config.verify_signature(b"Hello!", signature)
```

## Configuration Options

### SecurityConfig Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `secret_prefix` | str | `"durus/hmac"` | Prefix for secret names in Oneiric |
| `rotation_interval_days` | int | `90` | Key rotation interval in days |
| `key_length_minimum_bytes` | int | `32` | Minimum key length in bytes (256 bits) |
| `allowed_algorithms` | List[str] | `["sha256", "sha384", "sha512"]` | Allowed HMAC algorithms |
| `allow_fallback_keys` | bool | `True` | Allow fallback keys during rotation |
| `require_key_validation` | bool | `True` | Require key validation at startup |
| `enable_auto_rotation` | bool | `True` | Enable automatic key rotation |
| `enable_strict_mode` | bool | `False` | Enable strict validation mode |
| `log_security_events` | bool | `True` | Enable security event logging |
| `fallback_signing_key` | bytes | `None` | Custom fallback signing key |
| `fallback_enabled` | bool | `False` | Enable fallback mode |

## Advanced Usage

### Manual Key Rotation

```python
# Rotate all keys
key_rotations = config.rotate_keys()
print(f"Rotated keys: {key_rotations}")

# Check security status after rotation
status = config.get_security_status()
print(f"Key status: {status}")
```

### Backup Keys

```python
# Create a backup key
backup_key_id = config.create_backup_key()
print(f"Created backup key: {backup_key_id}")
```

### Key Cleanup

```python
# Clean up expired keys
cleaned_count = config.cleanup_expired_keys()
print(f"Cleaned up {cleaned_count} expired keys")
```

### Security Status Monitoring

```python
# Get comprehensive security status
status = config.get_security_status()

print(f"Initialized: {status['initialized']}")
print(f"Oneiric available: {status['oneiric_available']}")
print(f"Key status: {status.get('key_status', {})}")
print(f"Rotation interval: {status['rotation_interval_days']} days")
```

## Oneiric Integration

### Prerequisites

Ensure the Oneiric SDK is installed:

```bash
pip install oneiric
```

### Secret Structure

The system stores secrets in Oneiric with the following naming convention:

```
{secret_prefix}/signing_key              # Primary signing key
{secret_prefix}/signing_key_created      # Creation timestamp
{secret_prefix}/signing_key_expires      # Expiration timestamp
{secret_prefix}/backup_signing_key       # Backup/rotated key
{secret_prefix}/backup_signing_key_created
{secret_prefix}/backup_signing_key_expires
```

### Environment Variables

The system respects the following environment variables:

- `ONEIRIC_SECRET_PREFIX`: Override default secret prefix
- `ONEIRIC_ROTATION_INTERVAL`: Override rotation interval in days
- `ONEIRIC_ENABLE_FALLBACK`: Enable fallback mode (true/false)

## Security Best Practices

### 1. Key Rotation

- **Always use the default 90-day rotation interval**
- Monitor key status regularly using `get_security_status()`
- Plan rotations during maintenance windows

### 2. Algorithm Selection

- **Prefer SHA256 for most use cases**
- Use SHA384 or SHA512 for higher security requirements
- Avoid MD5 and SHA1 (deprecated)

### 3. Validation

- **Always enable key validation** (`require_key_validation=True`)
- Enable strict mode in production (`enable_strict_mode=True`)
- Monitor security logs for unusual events

### 4. Fallback Mode

- **Never use fallback mode in production**
- Use only for development and testing
- Generate a custom fallback key for testing

### 5. Error Handling

Always handle security exceptions appropriately:

```python
try:
    signature = config.create_signature(message)
except ValueError as e:
    print(f"Invalid request: {e}")
except RuntimeError as e:
    print(f"Security error: {e}")
```

## Thread Safety

The secret management system is fully thread-safe:

- All operations use threading.RLock for synchronization
- Multiple threads can create signatures simultaneously
- Key rotation is atomic and won't interrupt active operations
- Fallback keys provide continuity during rotation

## Migration from HashiCorp Vault

If migrating from HashiCorp Vault to Oneiric:

1. **Update dependencies**: Remove Vault client, install Oneiric SDK
1. **Change configuration**: Update secret prefix and initialization
1. **No code changes**: The API remains the same
1. **Enable fallback**: Use during migration for zero downtime

### Example Migration

```python
# Before (HashiCorp Vault)
from durus.config.vault import VaultSecurityConfig

config = VaultSecurityConfig(...)

# After (Oneiric)
from durus.config.security import SecurityConfig

config = SecurityConfig(
    secret_prefix="myapp/hmac",
    fallback_enabled=True  # Enable during migration
)
```

## Troubleshooting

### Common Issues

**"Oneiric secrets library is not available"**

- Install Oneiric SDK: `pip install oneiric`
- Enable fallback mode for development/testing

**"Key has expired"**

- Keys are automatically rotated, but manual rotation can be triggered with `rotate_keys()`
- Check key status with `get_security_status()`

**"Failed to load secrets from Oneiric"**

- Verify Oneiric connection and permissions
- Check secret prefix is correct
- Enable fallback mode temporarily

### Debug Logging

Enable debug logging to troubleshoot issues:

```python
import logging
logging.getLogger('durus.config.security').setLevel(logging.DEBUG)
```

## API Reference

### SecurityConfig Class

#### Methods

- `initialize()`: Initialize the security configuration
- `create_signature(message, algorithm)`: Create HMAC signature
- `verify_signature(message, signature, algorithm)`: Verify HMAC signature
- `rotate_keys()`: Manually rotate all keys
- `get_security_status()`: Get security status information
- `cleanup_expired_keys()`: Clean up expired keys
- `create_backup_key()`: Create a backup key

#### Properties

- `initialized`: Check if configuration is initialized
- `secret_prefix`: Current secret prefix
- `rotation_interval_days`: Rotation interval
- `fallback_enabled`: Fallback mode status

### Global Functions

- `get_security_config()`: Get the global security configuration
- `initialize_secret(...)`: Initialize global configuration

## Testing

### Unit Tests

```python
def test_signing_and_verification():
    with SecurityConfig(fallback_enabled=True) as config:
        message = b"test message"
        signature = config.create_signature(message)
        assert config.verify_signature(message, signature)
        assert not config.verify_signature(b"wrong message", signature)
```

### Integration Tests

```python
def test_key_rotation():
    config = SecurityConfig(
        rotation_interval_days=1,  # Quick rotation for testing
        fallback_enabled=True
    )

    with config:
        original_keys = config.get_security_status()
        rotated_keys = config.rotate_keys()

        # Verify rotation occurred
        assert len(rotated_keys) > 0
```

## Version History

- **v1.0.0**: Initial implementation with Oneiric integration
- **v1.0.1**: Enhanced fallback mode and error handling
- **v1.0.2**: Added backup key support and cleanup functionality
- **v1.1.0**: Thread-safe implementation and auto-rotation
