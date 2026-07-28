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
    "DEFAULT_CIPHER_SUITES",
    "DEFAULT_TLS_VERSION",
    "DEFAULT_VERIFY_MODE",
    # Oneiric secrets
    "OneiricSecretsAdapter",
    "SecretKey",
    # TLS/SSL
    "TLSConfig",
    "create_hmac_signature",
    "generate_self_signed_cert",
    "get_env_tls_config",
    "get_secrets_adapter",
    "initialize_secrets",
    "verify_hmac_signature",
    "wrap_client_socket",
    "wrap_server_socket",
]

__version__ = "1.1.0"
