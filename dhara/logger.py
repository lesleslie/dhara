"""
Backward-compatibility logging shim for Dhara.

Provides the legacy stdlib-based API (logger, log, direct_output, is_logging)
while delegating to structlog via Oneiric for actual formatting/output.

This module intentionally keeps the original API shape so existing code
(dhara server, storage backends, CLI) continues to work unchanged.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

# Oneiric structlog integration
from oneiric.core.logging import (
    LoggingConfig,
    configure_logging,
)
from oneiric.core.logging import (
    get_logger as _structlog_get_logger,
)

# ---- Public API (original signatures, same behavior) ----

logger: logging.Logger = logging.getLogger("dhara")


class _LogFunction:
    """A callable that routes `log(level, msg, *args)` to structlog."""

    __slots__ = ("_log",)

    def __init__(self) -> None:
        self._log: Any = None

    def _ensure(self) -> Any:
        if self._log is None:
            self._log = _structlog_get_logger("dhara")
        return self._log

    def __call__(self, level: int, msg: str, *args: Any) -> None:
        log = self._ensure()
        if level >= logging.ERROR:
            log.error(msg, *args)
        elif level >= logging.WARNING:
            log.warning(msg, *args)
        elif level >= logging.INFO:
            log.info(msg, *args)
        else:
            log.debug(msg, *args)


log = _LogFunction()


def direct_output(file: Any) -> None:
    configure_logging(
        LoggingConfig(
            level="INFO",
            emit_json=False,
            traceback_style="string",
            sinks=[],
        )
    )
    logger.handlers.clear()
    handler = logging.StreamHandler(file)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    logger.setLevel(logging.INFO)
    if file is sys.__stderr__:
        return
    if sys.stdout is sys.__stdout__:
        sys.stdout = file
    else:
        log(100, "sys.stdout already customized.")
    if sys.stderr is sys.__stderr__:
        sys.stderr = file
    else:
        log(100, "sys.stderr already customized.")


def is_logging(level: int) -> bool:
    return logger.getEffectiveLevel() <= level


if not logger.handlers:
    direct_output(sys.stderr)
