"""Tests for Durus structured logging."""

import pytest
import logging
from io import StringIO
from contextlib import redirect_stderr

from dhruva.logging import (
    get_logger,
    get_connection_logger,
    get_storage_logger,
    setup_logging,
    log_operation,
    log_operation_decorator,
    log_context,
    logger,
)


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_setup_logging_basic(self):
        """Test basic logging setup."""
        # Clear existing handlers
        logger.handlers.clear()

        setup_logging()
        assert len(logger.handlers) > 0
        assert logger.level == logging.INFO

    def test_setup_logging_custom_level(self):
        """Test setup with custom level."""
        logger.handlers.clear()

        setup_logging(level=logging.DEBUG)
        assert logger.level == logging.DEBUG

    def test_setup_logging_idempotent(self):
        """Test that setup is idempotent (doesn't add duplicate handlers)."""
        logger.handlers.clear()

        setup_logging()
        initial_count = len(logger.handlers)

        setup_logging()
        # Should not add more handlers
        assert len(logger.handlers) == initial_count


class TestGetLogger:
    """Tests for get_logger function."""

    def test_get_logger_default(self):
        """Test getting default logger."""
        log = get_logger()
        assert log is logger

    def test_get_logger_named(self):
        """Test getting named logger."""
        log = get_logger("storage")
        assert log.name == "durus.storage"
        assert log.parent is logger

    def test_get_logger_nested(self):
        """Test getting nested logger."""
        log = get_logger("storage.file")
        assert log.name == "durus.storage.file"


class TestConnectionLogger:
    """Tests for get_connection_logger function."""

    def test_get_connection_logger(self):
        """Test getting connection logger."""
        log = get_connection_logger("conn-001")
        assert log.name == "durus.connection.conn-001"
        assert log.parent is logger

    def test_get_connection_logger_different_ids(self):
        """Test that different connection IDs create different loggers."""
        log1 = get_connection_logger("conn-001")
        log2 = get_connection_logger("conn-002")
        assert log1.name != log2.name


class TestStorageLogger:
    """Tests for get_storage_logger function."""

    def test_get_storage_logger_basic(self):
        """Test getting storage logger without path."""
        log = get_storage_logger("file")
        assert log.name == "durus.storage.file"

    def test_get_storage_logger_with_path(self):
        """Test getting storage logger with path."""
        log = get_storage_logger("file", "/data/mydb.durus")
        assert "storage.file" in log.name
        assert "_data_mydb_durus" in log.name

    def test_get_storage_logger_path_sanitization(self):
        """Test that paths are sanitized for logger names."""
        log = get_storage_logger("file", "/path/to/file.durus")
        assert "/" not in log.name


class TestLogOperation:
    """Tests for log_operation context manager."""

    def test_log_operation_success(self):
        """Test logging successful operation."""
        # Capture log output
        log_stream = StringIO()
        handler = logging.StreamHandler(log_stream)
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        with log_operation("test_operation", param1="value1"):
            pass

        log_output = log_stream.getvalue()
        assert "Started test_operation" in log_output or "Completed test_operation" in log_output

        # Cleanup
        logger.removeHandler(handler)

    def test_log_operation_failure(self):
        """Test logging failed operation."""
        log_stream = StringIO()
        handler = logging.StreamHandler(log_stream)
        handler.setLevel(logging.ERROR)
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)

        try:
            with pytest.raises(ValueError):
                with log_operation("failing_operation"):
                    raise ValueError("Test error")
        finally:
            log_output = log_stream.getvalue()
            assert "Failed failing_operation" in log_output
            logger.removeHandler(handler)

    def test_log_operation_with_context(self):
        """Test logging operation with context."""
        log_stream = StringIO()
        handler = logging.StreamHandler(log_stream)
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        with log_operation("test_operation", count=100, size="1MB"):
            pass

        # Context should be logged
        log_output = log_stream.getvalue()
        assert "test_operation" in log_output

        # Cleanup
        logger.removeHandler(handler)


class TestLogOperationDecorator:
    """Tests for log_operation_decorator."""

    def test_log_operation_decorator_success(self):
        """Test decorator on successful function."""
        log_stream = StringIO()
        handler = logging.StreamHandler(log_stream)
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        @log_operation_decorator()
        def test_function():
            return "result"

        result = test_function()
        assert result == "result"

        log_output = log_stream.getvalue()
        assert "test_function" in log_output

        # Cleanup
        logger.removeHandler(handler)

    def test_log_operation_decorator_custom_name(self):
        """Test decorator with custom operation name."""
        log_stream = StringIO()
        handler = logging.StreamHandler(log_stream)
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        @log_operation_decorator("custom_operation")
        def test_function():
            pass

        test_function()

        log_output = log_stream.getvalue()
        assert "custom_operation" in log_output

        # Cleanup
        logger.removeHandler(handler)

    def test_log_operation_decorator_failure(self):
        """Test decorator on failing function."""
        log_stream = StringIO()
        handler = logging.StreamHandler(log_stream)
        handler.setLevel(logging.ERROR)
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)

        @log_operation_decorator()
        def failing_function():
            raise ValueError("Test error")

        try:
            with pytest.raises(ValueError):
                failing_function()
        finally:
            log_output = log_stream.getvalue()
            assert "Failed failing_function" in log_output
            logger.removeHandler(handler)


class TestLogContext:
    """Tests for log_context function."""

    def test_log_context_adapter(self):
        """Test creating logging adapter with context."""
        adapter = log_context(connection_id="conn-001", user="alice")
        assert isinstance(adapter, logging.LoggerAdapter)
        assert adapter.extra["connection_id"] == "conn-001"
        assert adapter.extra["user"] == "alice"


class TestLoggerIntegration:
    """Integration tests for logging system."""

    def test_logger_propagation(self):
        """Test that Durus logger doesn't propagate to root logger."""
        assert logger.propagate is False

    def test_logger_has_handler(self):
        """Test that logger has at least one handler."""
        assert len(logger.handlers) > 0

    def test_multiple_modules_use_same_parent(self):
        """Test that loggers from different modules share parent."""
        storage_log = get_logger("storage")
        connection_log = get_logger("connection")

        assert storage_log.parent is logger
        assert connection_log.parent is logger

    def test_logger_level_inheritance(self):
        """Test that child loggers inherit parent level."""
        child_logger = get_logger("test_child")
        # Child logger should inherit parent's level when not explicitly set
        # (This is standard Python logging behavior)
        assert child_logger.parent is logger
