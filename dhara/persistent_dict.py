"""Deprecated compatibility shim for legacy ``durus.persistent_dict`` imports.

Prefer ``dhara.collections.dict`` for active code. This module remains only for
backward compatibility with older imports and pickled data.
"""

from __future__ import annotations

import warnings

from dhara.collections.dict import *

warnings.warn(
    "dhara.persistent_dict is deprecated; use dhara.collections.dict instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["PersistentDict"]
