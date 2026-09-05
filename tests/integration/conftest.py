"""Pytest configuration for tests/integration/.

Registers the ``needs_short_sun_path`` marker used by unix-domain socket
tests, so they can be skipped on platforms where ``sun_path`` is too short
(macOS caps sun_path at 104 bytes; pytest tmp paths often exceed that).
"""

from __future__ import annotations


def pytest_configure(config: object) -> None:
    config.addinivalue_line(  # type: ignore[attr-defined]
        "markers",
        "needs_short_sun_path: Unix-domain socket tests that need a "
        "sun_path under 104 bytes (Linux only).",
    )
