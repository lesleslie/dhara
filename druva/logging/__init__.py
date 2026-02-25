"""Structured logging for Durus.

This module provides structured logging utilities following Oneiric patterns,
with context-aware logging and operation tracking.
"""

from .logger import (
    get_connection_logger,
    get_logger,
    get_storage_logger,
    log_context,
    log_operation,
    log_operation_decorator,
    logger,
    setup_logging,
)

__all__ = [
    "get_logger",
    "get_connection_logger",
    "get_storage_logger",
    "setup_logging",
    "log_operation",
    "log_operation_decorator",
    "log_context",
    "logger",
]

__version__ = "1.0.0"
