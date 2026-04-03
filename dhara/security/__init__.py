"""
Druva Security Module

This module provides security-related functionality including:
- TLS/SSL support for network connections
- Secure secrets management using Oneiric secrets adapters
- HMAC signing operations
"""

from .oneiric_secrets import (
    OneiricSecretsAdapter,
    SecretKey,
    create_hmac_signature,
    get_secrets_adapter,
    initialize_secrets,
    verify_hmac_signature,
)
from .tls import (
    DEFAULT_CIPHER_SUITES,
    DEFAULT_TLS_VERSION,
    DEFAULT_VERIFY_MODE,
    TLSConfig,
    generate_self_signed_cert,
    get_env_tls_config,
    wrap_client_socket,
    wrap_server_socket,
)

__all__ = [
    # Oneiric secrets
    "OneiricSecretsAdapter",
    "SecretKey",
    "get_secrets_adapter",
    "create_hmac_signature",
    "verify_hmac_signature",
    "initialize_secrets",
    # TLS/SSL
    "TLSConfig",
    "DEFAULT_CIPHER_SUITES",
    "DEFAULT_TLS_VERSION",
    "DEFAULT_VERIFY_MODE",
    "wrap_client_socket",
    "wrap_server_socket",
    "generate_self_signed_cert",
    "get_env_tls_config",
]

__version__ = "1.1.0"
