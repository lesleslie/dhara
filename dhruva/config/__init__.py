"""
Durus Configuration Module

This module provides centralized configuration for Durus applications,
following Oneiric patterns for configuration management.
"""

from .defaults import (
    CacheConfig,
    ConnectionConfig,
    DhruvaConfig,
    StorageConfig,
)
from .loader import (
    load_config,
    load_config_from_env,
    merge_configs,
    save_config,
)
from .security import SecurityConfig, get_security_config, initialize_security

__all__ = [
    # Security configuration
    "SecurityConfig",
    "get_security_config",
    "initialize_security",
    # Core configuration classes
    "DhruvaConfig",
    "StorageConfig",
    "CacheConfig",
    "ConnectionConfig",
    # Configuration utilities
    "load_config",
    "load_config_from_env",
    "save_config",
    "merge_configs",
]

__version__ = "2.0.0"
