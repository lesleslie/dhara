"""Schema base classes for D-OBJ-SCHEMA.

Defines the ``SchemaEntry`` registration record and the
``SchemaValidationError`` exception type. All entity modules import
from here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import msgspec


@dataclass(frozen=True)
class SchemaEntry:
    """Registry record for one schema entity.

    Frozen=True prevents the registry from being mutated after a
    schema is registered. Use the :func:`register` decorator to add
    new entries; re-registration raises ``ValueError``.
    """

    name: str
    version: str
    struct: type[msgspec.Struct]
    migrations: dict[str, Callable[..., Any]]


class SchemaValidationError(Exception):
    """Raised when a payload fails validation against a registered schema.
    Wraps :class:`msgspec.ValidationError` so consumers don't need to
    import msgspec directly.
    """
