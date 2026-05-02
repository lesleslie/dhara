"""Deprecated compatibility shim for legacy ``durus.connection`` imports.

Prefer ``dhara.core.connection`` for active code. This module remains only for
backward compatibility with older imports and pickled data.
"""

from __future__ import annotations

import warnings

from dhara.core.connection import ROOT_OID, Connection

warnings.warn(
    "dhara.connection is deprecated; use dhara.core.connection instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["Connection", "ROOT_OID"]
