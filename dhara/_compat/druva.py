"""Compatibility shims for legacy Druva-prefixed names.

The Dhara project was renamed from Druva; these aliases remain for
backward compatibility with downstream code that hasn't migrated.
DruvaKeyError is the canonical error class (not an alias) and lives
in dhara.error.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def __getattr__(name: str):
    # Lazy resolution to avoid circular imports:
    # dhara.core.config and dhara.config.defaults both re-export
    # these aliases from this module, so eager imports here would deadlock.
    if name == "DruvaSettings":
        from dhara.core.config import DharaSettings

        return DharaSettings
    if name == "DruvaConfig":
        from dhara.config.defaults import DharaConfig

        return DharaConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["DruvaSettings", "DruvaConfig"]
