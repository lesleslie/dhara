"""Configuration loader for Durus.

This module provides utilities for loading Durus configuration from
various sources (files, dictionaries, environment variables).
"""

import os
from pathlib import Path
from typing import Literal, Union, Optional
from copy import deepcopy
import yaml

from dhruva.config.defaults import DurusConfig, StorageConfig, CacheConfig, ConnectionConfig

# Maximum configuration file size to prevent DoS attacks (10MB)
MAX_CONFIG_SIZE = 10 * 1024 * 1024

# Valid storage backend types
VALID_STORAGE_BACKENDS = {"file", "sqlite", "client", "memory"}

# Valid port range for TCP/UDP
MIN_PORT = 1
MAX_PORT = 65535

# Maximum cache size to prevent memory exhaustion (1 billion entries)
MAX_CACHE_SIZE = 1_000_000_000


def load_config(
    source: Union[str, Path, dict],
    format: Literal["yaml", "json", "dict", "auto"] = "auto",
    max_size: int = MAX_CONFIG_SIZE,
) -> DurusConfig:
    """Load configuration from file or dictionary.

    Args:
        source: Path to config file, or dict with config values
        format: Config format ('yaml', 'json', 'dict', or 'auto' for detection)
        max_size: Maximum config file size in bytes (default: 10MB)

    Returns:
        Validated DurusConfig instance

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If configuration is invalid or file too large
        yaml.YAMLError: If YAML parsing fails

    Examples:
        Load from dictionary:
        >>> config = load_config({'storage': {'backend': 'memory'}})

        Load from YAML file:
        >>> config = load_config('config.yaml')

        Load from specific format:
        >>> config = load_config('config.yml', format='yaml')
    """
    # Handle dictionary input
    if isinstance(source, dict):
        return DurusConfig.from_dict(source)

    # Handle file input
    path = Path(source)

    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    # Check file size before reading to prevent DoS attacks
    file_size = path.stat().st_size
    if file_size > max_size:
        raise ValueError(
            f"Config file too large: {file_size:,} bytes > {max_size:,} bytes maximum"
        )

    # Auto-detect format from extension
    if format == "auto":
        suffix = path.suffix.lower()
        if suffix in [".yaml", ".yml"]:
            format = "yaml"
        elif suffix == ".json":
            format = "json"
        else:
            raise ValueError(
                f"Cannot detect format from extension '{suffix}'. "
                "Please specify format explicitly."
            )

    # Read and parse file
    content = path.read_text()

    if format == "yaml":
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"Failed to parse YAML file {path}: {e}")
    elif format == "json":
        import json

        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON file {path}: {e}")
    else:
        raise ValueError(f"Unsupported format: {format}")

    # Ensure we got a dictionary
    if not isinstance(data, dict):
        raise ValueError(
            f"Configuration file must contain a dictionary, got {type(data).__name__}"
        )

    return DurusConfig.from_dict(data)


def load_config_from_env(
    prefix: str = "DURUS",
    config_file_var: str = "CONFIG",
) -> Optional[DurusConfig]:
    """Load configuration from environment variables.

    This function checks for a configuration file path in the environment
    and loads it if found. Additional environment variables can override
    values in the config file.

    Args:
        prefix: Environment variable prefix (default: 'DURUS')
        config_file_var: Suffix for config file variable (default: 'CONFIG')

    Returns:
        DurusConfig instance if config file is found, None otherwise

    Raises:
        ValueError: If any environment variable has an invalid value
        TypeError: If type conversion fails for environment variable values
        FileNotFoundError: If config file specified in environment doesn't exist

    Examples:
        Set environment variable:
        export DURUS_CONFIG=/path/to/config.yaml

        Load in code:
        >>> config = load_config_from_env()
        >>> if config:
        ...     print(f"Loaded config: {config.storage.backend}")
    """
    # Check for config file path
    config_path = os.environ.get(f"{prefix}_{config_file_var}")

    if not config_path:
        return None

    # Load the configuration file
    config = load_config(config_path)

    # Override with specific environment variables if present
    # e.g., DURUS_STORAGE_BACKEND, DURUS_CACHE_SIZE

    # Validate storage backend
    if f"{prefix}_STORAGE_BACKEND" in os.environ:
        backend = os.environ[f"{prefix}_STORAGE_BACKEND"]
        if backend not in VALID_STORAGE_BACKENDS:
            raise ValueError(
                f"Invalid {prefix}_STORAGE_BACKEND: {backend}. "
                f"Must be one of: {', '.join(sorted(VALID_STORAGE_BACKENDS))}"
            )
        config.storage.backend = backend

    # Validate and sanitize storage path
    if f"{prefix}_STORAGE_PATH" in os.environ:
        path_str = os.environ[f"{prefix}_STORAGE_PATH"]

        # Check for path traversal attempts
        if '../' in path_str or '..\\\\' in path_str:
            raise ValueError(
                f"Invalid {prefix}_STORAGE_PATH: {path_str}. "
                f"Path traversal with '..' is not allowed from environment."
            )

        # Don't allow home directory expansion from env vars for security
        if path_str.startswith('~'):
            raise ValueError(
                f"Invalid {prefix}_STORAGE_PATH: {path_str}. "
                f"Home directory expansion not allowed from environment variables."
            )

        # Resolve to absolute path and validate
        try:
            path = Path(path_str).resolve()
        except (OSError, RuntimeError) as e:
            raise ValueError(
                f"Invalid {prefix}_STORAGE_PATH: {path_str}. "
                f"Error resolving path: {e}"
            )

        config.storage.path = path

    # Validate storage host (basic validation)
    if f"{prefix}_STORAGE_HOST" in os.environ:
        host = os.environ[f"{prefix}_STORAGE_HOST"].strip()
        if not host:
            raise ValueError(f"{prefix}_STORAGE_HOST cannot be empty")
        config.storage.host = host

    # Validate storage port with proper error handling
    if f"{prefix}_STORAGE_PORT" in os.environ:
        port_str = os.environ[f"{prefix}_STORAGE_PORT"]
        try:
            port = int(port_str)
        except ValueError as e:
            raise TypeError(
                f"{prefix}_STORAGE_PORT must be an integer: {port_str!r}"
            ) from e

        if not MIN_PORT <= port <= MAX_PORT:
            raise ValueError(
                f"Invalid {prefix}_STORAGE_PORT: {port}. "
                f"Must be between {MIN_PORT} and {MAX_PORT}"
            )
        config.storage.port = port

    # Validate cache size with bounds checking
    if f"{prefix}_CACHE_SIZE" in os.environ:
        size_str = os.environ[f"{prefix}_CACHE_SIZE"]
        try:
            size = int(size_str)
        except ValueError as e:
            raise TypeError(
                f"{prefix}_CACHE_SIZE must be an integer: {size_str!r}"
            ) from e

        if size < 0:
            raise ValueError(
                f"{prefix}_CACHE_SIZE must be non-negative: {size}"
            )
        if size > MAX_CACHE_SIZE:
            raise ValueError(
                f"{prefix}_CACHE_SIZE too large: {size:,} (max: {MAX_CACHE_SIZE:,})"
            )
        config.cache.size = size

    # Validate debug mode flag
    if f"{prefix}_DEBUG" in os.environ:
        debug_str = os.environ[f"{prefix}_DEBUG"].lower()
        valid_true_values = {"1", "true", "yes", "on", "enabled"}
        valid_false_values = {"0", "false", "no", "off", "disabled"}

        if debug_str not in valid_true_values | valid_false_values:
            raise ValueError(
                f"Invalid {prefix}_DEBUG: {os.environ[f'{prefix}_DEBUG']!r}. "
                f"Valid values: {', '.join(sorted(valid_true_values | valid_false_values))}"
            )

        config.debug_mode = debug_str in valid_true_values

    return config


def save_config(
    config: DurusConfig,
    path: Union[str, Path],
    format: Literal["yaml", "json"] = "yaml",
) -> None:
    """Save configuration to file.

    Args:
        config: DurusConfig instance to save
        path: Path to save the configuration file
        format: Format to save ('yaml' or 'json')

    Raises:
        ValueError: If format is not supported
        OSError: If file cannot be written

    Examples:
        >>> config = DurusConfig()
        >>> save_config(config, 'config.yaml')
    """
    path = Path(path)
    data = config.to_dict()

    if format == "yaml":
        content = yaml.dump(data, default_flow_style=False, sort_keys=False)
    elif format == "json":
        import json

        content = json.dumps(data, indent=2)
    else:
        raise ValueError(f"Unsupported format: {format}")

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write configuration
    path.write_text(content)


def merge_configs(*configs: DurusConfig) -> DurusConfig:
    """Merge multiple configurations, with later configs taking precedence.

    This is useful for layering configurations (defaults -> file -> env -> cli).

    Args:
        *configs: DurusConfig instances to merge

    Returns:
        Merged DurusConfig instance

    Examples:
        >>> default = DurusConfig()
        >>> override = DurusConfig(storage=StorageConfig(backend='memory'))
        >>> merged = merge_configs(default, override)
        >>> assert merged.storage.backend == 'memory'
    """
    if not configs:
        return DurusConfig()

    # Start with a deep copy of the first config
    result = deepcopy(configs[0])

    # Merge each subsequent config
    for config in configs[1:]:
        # Storage config - override if different from defaults
        if config.storage.backend != "memory":
            result.storage.backend = config.storage.backend
        if config.storage.path is not None:
            result.storage.path = config.storage.path
        if config.storage.host != "localhost":
            result.storage.host = config.storage.host
        if config.storage.port != 2972:
            result.storage.port = config.storage.port
        if config.storage.read_only:
            result.storage.read_only = config.storage.read_only

        # Cache config
        if config.cache.size != 100000:
            result.cache.size = config.cache.size
        if config.cache.shrink_threshold != 2.0:
            result.cache.shrink_threshold = config.cache.shrink_threshold
        if not config.cache.enabled:
            result.cache.enabled = config.cache.enabled

        # Connection config
        if config.connection.timeout != 30.0:
            result.connection.timeout = config.connection.timeout
        if config.connection.max_retries != 3:
            result.connection.max_retries = config.connection.max_retries
        if config.connection.retry_delay != 1.0:
            result.connection.retry_delay = config.connection.retry_delay

        # Debug mode
        if config.debug_mode:
            result.debug_mode = config.debug_mode

    return result
