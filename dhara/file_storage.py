"""Deprecated compatibility shim for legacy ``durus.file_storage`` imports.

Prefer ``dhara.storage.file`` for active code. This module remains only for
backward compatibility with older imports and pickled data.
"""

from __future__ import annotations

import warnings

from dhara.storage.file import *

warnings.warn(
    "dhara.file_storage is deprecated; use dhara.storage.file instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["FileStorage"]
