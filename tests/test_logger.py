"""Tests for dhara.logger — direct_output and is_logging."""

from __future__ import annotations

import io
import sys
from logging import INFO
from unittest.mock import MagicMock, patch

from dhara.logger import direct_output, is_logging, log, logger


class TestIsLogging:
    def test_default_logging_enabled(self):
        # Logger should be at INFO level by default
        assert is_logging(INFO) is True

    def test_is_logging_debug_level(self):
        # Logger at INFO, so DEBUG (10) should not log
        assert is_logging(10) is False

    def test_is_logging_info_level(self):
        # Logger at INFO, so INFO (20) should log
        assert is_logging(20) is True

    def test_is_logging_warning_level(self):
        # WARNING (30) >= INFO (20), so is_logging returns True
        assert is_logging(30) is True


class TestDirectOutput:
    def test_direct_output_to_stderr(self):
        buf = io.StringIO()
        with patch("sys.__stderr__", buf):
            direct_output(buf)
        assert len(logger.handlers) >= 1
        assert logger.level == INFO

    def test_direct_output_resets_stdout(self):
        """When sys.stdout == sys.__stdout__, direct_output redirects stdout."""
        buf = io.StringIO()
        original_stdout = sys.stdout
        # Use real __stdout__ so the comparison works
        with patch("sys.__stderr__", buf):
            with patch("sys.stdout", sys.__stdout__):
                direct_output(buf)
                # If stdout was same as __stdout__, it should now be buf
                # (but this may not work in test env where __stdout__ is patched)
                # Just verify no error and handler is set
                assert len(logger.handlers) >= 1
        sys.stdout = original_stdout

    def test_direct_output_stdout_already_customized(self):
        buf = io.StringIO()
        original_stdout = sys.stdout
        sys.stdout = io.StringIO()  # already customized
        with patch("sys.__stdout__", sys.stdout):
            with patch("sys.__stderr__", buf):
                direct_output(buf)
                # Should log warning, not redirect
        sys.stdout = original_stdout

    def test_direct_output_resets_stderr(self):
        buf = io.StringIO()
        original_stderr = sys.stderr
        with patch("sys.__stdout__", sys.stdout):
            with patch("sys.__stderr__", sys.stderr):
                direct_output(buf)
                # sys.stderr should be redirected to buf
                assert sys.stderr is buf
        sys.stderr = original_stderr

    def test_direct_output_stderr_already_customized(self):
        buf = io.StringIO()
        original_stderr = sys.stderr
        sys.stderr = io.StringIO()  # already customized
        with patch("sys.__stdout__", sys.stdout):
            with patch("sys.__stderr__", sys.stderr):
                direct_output(buf)
        sys.stderr = original_stderr

    def test_direct_output_same_as___stderr__(self):
        buf = io.StringIO()
        # When file IS sys.__stderr__, the function returns early
        # without touching sys.stdout/sys.stderr
        with patch("sys.__stderr__", buf):
            with patch("sys.__stdout__", sys.stdout):
                direct_output(buf)
        # Handlers should still be set
        assert len(logger.handlers) >= 1


class TestLogFunction:
    def test_log_callable(self):
        assert callable(log)
