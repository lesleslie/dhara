"""
Dhara configuration module.

This module provides centralized configuration for Dhara applications,
following Oneiric patterns for configuration management.

`dhara.core.config` is the canonical runtime settings surface for the
MCP server and CLI. This package remains for lightweight dataclass-based
configuration helpers and compatibility with older Dhara/Druva code.
"""

from .defaults import (
    CacheConfig,
    ConnectionConfig,
    DharaConfig,
    DruvaConfig,
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
    "DharaConfig",
    "DruvaConfig",
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
