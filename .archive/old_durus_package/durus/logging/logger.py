"""Structured logger for Durus using standard library logging.

This module provides structured logging utilities for Durus,
following Oneiric patterns for context-aware logging.
"""

import logging
import sys
from typing import Any, Optional
from contextlib import contextmanager
from functools import wraps


# Create Durus logger
logger = logging.getLogger("durus")


def setup_logging(
    level: int = logging.INFO,
    format: str = "%(asctime)s %(name)s %(levelname)s %(message)s",
    output: Any = sys.stderr,
) -> None:
    """Setup structured logging for Durus.

    This function configures the root Durus logger with a handler
    and formatter. It respects the existing logger setup if already
    configured (matching the pattern in durus.logger.py).

    Args:
        level: Logging level (default: INFO)
        format: Log format string
        output: Output file-like object

    Examples:
        Basic setup:
        >>> setup_logging()

        Custom level and format:
        >>> setup_logging(logging.DEBUG, "%(name)s - %(message)s")

        Log to file:
        >>> with open('durus.log', 'w') as f:
        ...     setup_logging(output=f)
    """
    # Only setup if not already configured
    if logger.handlers:
        return

    handler = logging.StreamHandler(output)
    handler.setFormatter(logging.Formatter(format))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Get a Durus logger with optional name.

    Args:
        name: Optional logger name (auto-prefixed with 'durus.')

    Returns:
        Logger instance

    Examples:
        Get root Durus logger:
        >>> log = get_logger()

        Get named logger:
        >>> log = get_logger('storage')
        >>> # Returns 'durus.storage' logger
    """
    if name:
        return logger.getChild(name)
    return logger


def get_connection_logger(connection_id: str) -> logging.Logger:
    """Get a logger with connection context.

    This creates a child logger specifically for a connection,
    allowing for connection-specific log filtering and analysis.

    Args:
        connection_id: Unique connection identifier

    Returns:
        Logger bound with connection context

    Examples:
        >>> conn_logger = get_connection_logger('conn-001')
        >>> conn_logger.info("Connection established")
        # Logs: "durus.connection.conn-001 - Connection established"
    """
    return logger.getChild(f"connection.{connection_id}")


def get_storage_logger(backend: str, path: Optional[str] = None) -> logging.Logger:
    """Get a logger with storage context.

    This creates a child logger specifically for a storage backend,
    allowing for backend-specific log filtering and analysis.

    Args:
        backend: Storage backend name
        path: Optional storage path

    Returns:
        Logger bound with storage context

    Examples:
        Basic storage logger:
        >>> storage_logger = get_storage_logger('file')
        >>> # Returns 'durus.storage.file' logger

        With path context:
        >>> storage_logger = get_storage_logger('file', '/data/mydb.durus')
        >>> # Returns 'durus.storage.file./data_mydb.durus' logger
    """
    name = f"storage.{backend}"
    if path:
        # Sanitize path for logger name
        safe_path = path.replace("/", "_").replace(".", "_")
        name = f"{name}.{safe_path}"
    return logger.getChild(name)


@contextmanager
def log_operation(operation: str, **context):
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
    logger.debug("Started %s", operation, extra=context)
    try:
        yield
        logger.debug("Completed %s", operation)
    except Exception as e:
        logger.error("Failed %s: %s", operation, e, exc_info=True)
        raise


def log_operation_decorator(operation: Optional[str] = None):
    """Decorator for logging function operations.

    This decorator wraps a function with operation logging,
    similar to log_operation context manager but as a decorator.

    Args:
        operation: Operation name (defaults to function name)

    Returns:
        Decorated function

    Examples:
        @log_operation_decorator()
        def commit_transaction():
            # ... do commit work ...
            pass

        @log_operation_decorator("backup")
        def create_backup():
            # ... do backup work ...
            pass
    """

    def decorator(func):
        op_name = operation or func.__name__

        @wraps(func)
        def wrapper(*args, **kwargs):
            func_logger = get_logger(func.__module__)
            func_logger.debug("Started %s", op_name)
            try:
                result = func(*args, **kwargs)
                func_logger.debug("Completed %s", op_name)
                return result
            except Exception as e:
                func_logger.error("Failed %s: %s", op_name, e, exc_info=True)
                raise

        return wrapper

    return decorator


def log_context(**context):
    """Create a logging adapter with additional context.

    This function creates a logging adapter that automatically
    includes the provided context in all log messages.

    Args:
        **context: Context key-value pairs to include in logs

    Returns:
        LoggingAdapter with context

    Examples:
        >>> log = log_context(connection_id="conn-001", user="alice")
        >>> log.info("Processing request")
        # Logs with connection_id and user context
    """
    return logging.LoggerAdapter(logger, context)


# Ensure logging is setup on module import
# This matches the pattern in durus.logger.py
if not logger.handlers:
    setup_logging()
