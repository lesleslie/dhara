"""Deprecated compatibility shim for legacy ``durus.persistent`` imports.

Prefer ``dhara.core.persistent`` for active code. This module remains only for
backward compatibility with older imports and pickled data.
"""

from __future__ import annotations

import warnings

from dhara.core.persistent import ConnectionBase, Persistent, PersistentBase

warnings.warn(
    "dhara.persistent is deprecated; use dhara.core.persistent instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["Persistent", "PersistentBase", "ConnectionBase"]
