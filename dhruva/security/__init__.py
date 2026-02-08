"""
Durus Security Module

This module provides secure secrets management using Oneiric secrets adapters,
designed specifically for HMAC signing operations in Durus applications.
"""

from .oneiric_secrets import (
    OneiricSecretsAdapter,
    SecretKey,
    create_hmac_signature,
    get_secrets_adapter,
    initialize_secrets,
    verify_hmac_signature,
)

__all__ = [
    "OneiricSecretsAdapter",
    "SecretKey",
    "get_secrets_adapter",
    "create_hmac_signature",
    "verify_hmac_signature",
    "initialize_secrets",
]

__version__ = "1.0.0"
