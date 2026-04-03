"""Druva Operational Modes System.

This module provides a mode-based architecture for Druva, enabling
simplified setup for development (lite mode) and full capabilities
for production (standard mode).

Mode Types:
- Lite: Zero-configuration development mode with local storage
- Standard: Full-featured production mode with configurable storage

Usage:
    from dhara.modes import create_mode, get_mode

    # Create mode instance
    mode = create_mode("lite")
    mode.initialize()

    # Or detect from environment
    mode = get_mode()
    print(f"Running in {mode.get_name()} mode")

    # List all modes
    from dhara.modes import list_modes
    for mode_info in list_modes():
        print(f"{mode_info['name']}: {mode_info['description']}")
"""

from __future__ import annotations

from dhara.modes.base import (
    ModeConfigurationError,
    ModeValidationError,
    OperationalMode,
    OperationalModeError,
    create_mode,
    get_mode,
    list_modes,
)
from dhara.modes.lite import LiteMode
from dhara.modes.standard import StandardMode

__all__ = [
    # Base classes and functions
    "OperationalMode",
    "OperationalModeError",
    "ModeValidationError",
    "ModeConfigurationError",
    "create_mode",
    "get_mode",
    "list_modes",
    # Mode implementations
    "LiteMode",
    "StandardMode",
]
