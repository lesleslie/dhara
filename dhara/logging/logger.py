"""Structured logger for Durus using structlog via Oneiric.

This module provides structured logging utilities for Durus,
following Oneiric patterns for context-aware logging.

Public API (must be preserved):
- get_logger(name) -> BoundLogger
- log_operation(operation, **context) -> context manager
- log_context(**context) -> LoggerAdapter
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from functools import wraps
from typing import Any

from oneiric.core.logging import LoggingConfig, configure_logging
from oneiric.core.logging import get_logger as _oneiric_get_logger

# === Public API: preserved signatures ===


def get_logger(name: str | None = None) -> Any:
    """Get a Dhara logger with optional name.

    Args:
        name: Optional logger name (auto-prefixed with 'dhara.')

    Returns:
        structlog BoundLogger

    Examples:
        Get root Dhara logger:
        >>> log = get_logger()

        Get named logger:
        >>> log = get_logger('storage')
        >>> # Returns 'dhara.storage' logger
    """
    prefixed = f"dhara.{name}" if name else "dhara"
    return _oneiric_get_logger(prefixed)


@contextmanager
def log_operation(operation: str, **context: Any) -> Iterator[None]:
    """Context manager for logging operations.

    This context manager logs the start and completion (or failure)
    of an operation, providing structured operation tracking.

    Args:
        operation: Operation name
        **context: Additional context to log

    Yields:
        None

    Examples:
        Basic usage:
        >>> with log_operation("commit", oid_count=100):
        ...     # ... do commit work ...
        # Logs: "Started commit" with context
        # Logs: "Completed commit" on success

        With exception handling:
        >>> try:
        ...     with log_operation("load", oid=123):
        ...         raise ValueError("Invalid data")
        ... except ValueError:
        ...     pass
        # Logs: "Failed load: Invalid data" with traceback
    """
    log = get_logger()
    log.debug("Started %s", operation, **context)
    try:
        yield
        log.debug("Completed %s", operation)
    except Exception:
        log.exception("Failed %s", operation)
        raise


def log_context(**context: Any) -> Any:
    """Create a logging adapter with additional context.

    This function creates a logging adapter that automatically
    includes the provided context in all log messages.

    Args:
        **context: Context key-value pairs to include in logs

    Returns:
        structlog BoundLogger with bound context

    Examples:
        >>> log = log_context(connection_id="conn-001", user="alice")
        >>> log.info("Processing request")
        # Logs with connection_id and user context
    """
    return get_logger().bind(**context)


def get_connection_logger(connection_id: str) -> Any:
    """Get a logger with connection context.

    Args:
        connection_id: Unique connection identifier

    Returns:
        structlog BoundLogger bound with connection context
    """
    return get_logger(f"connection.{connection_id}")


def get_storage_logger(backend: str, path: str | None = None) -> Any:
    """Get a logger with storage context.

    Args:
        backend: Storage backend name
        path: Optional storage path

    Returns:
        structlog BoundLogger bound with storage context
    """
    name = f"storage.{backend}"
    if path:
        safe_path = path.replace("/", "_").replace(".", "_")
        name = f"{name}.{safe_path}"
    return get_logger(name)


def log_operation_decorator(operation: str | None = None) -> Any:
    """Decorator for logging function operations.

    Args:
        operation: Operation name (defaults to function name)

    Returns:
        Decorated function with operation logging
    """

    def decorator(func):
        op_name = operation or func.__name__

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            log = get_logger(func.__module__)
            log.debug("Started %s", op_name)
            try:
                result = func(*args, **kwargs)
                log.debug("Completed %s", op_name)
                return result
            except Exception:
                log.exception("Failed %s", op_name)
                raise

        return wrapper

    return decorator


def setup_logging(
    level: int | str = "INFO",
    format: str = "%(asctime)s %(name)s %(levelname)s %(message)s",
    output: Any = sys.stderr,
    emit_json: bool = False,
    traceback_style: str = "string",
) -> None:
    """Setup structured logging for Durus via Oneiric.

    Args:
        level: Logging level (default: INFO)
        format: Log format string (passed as info only; structlog uses its own)
        output: Output file-like object (target sink)
        emit_json: Emit JSON logs (default: False → ConsoleRenderer)
        traceback_style: 'string' for human-readable, 'dict' for AI-friendly (default: string)

    Examples:
        Basic setup:
        >>> setup_logging()

        JSON output:
        >>> setup_logging(emit_json=True)

        Dict tracebacks:
        >>> setup_logging(emit_json=True, traceback_style="dict")
    """
    # Map string level to int for LoggingConfig
    if isinstance(level, str):
        level_upper = level.upper()
    else:
        level_upper = logging.getLevelName(level)

    # Determine sink target
    if output in (sys.stderr, None):
        target = "stderr"
    elif output == sys.stdout:
        target = "stdout"
    else:
        # File-like object — route to stderr (Console output)
        target = "stderr"

    from oneiric.core.logging import LoggingSinkConfig

    configure_logging(
        LoggingConfig(
            level=level_upper,
            emit_json=emit_json,
            sinks=[LoggingSinkConfig(target=target)],
        )
    )


# === Module-level logger (backward compatibility) ===
# Keep a stdlib logger reference for code that imports `logger` directly from this module.
# Internal code should use get_logger() / log_operation() etc.
import logging as _stdlib_logging

logger: _stdlib_logging.Logger = _stdlib_logging.getLogger("dhara")


# Ensure logging is initialized on module import
# (lazy init — only configure once)
_log_initialized = False


def _ensure_logging() -> None:
    global _log_initialized
    if not _log_initialized:
        setup_logging()
        _log_initialized = True


# Trigger logging init on first get_logger / log_operation call
# but NOT on plain module import (don't auto-init stdlib logger)
# Uncomment if you need Dhara logging to auto-init on import:
# _ensure_logging()
