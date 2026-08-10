"""Central schema registry for D-OBJ-SCHEMA.

Exposes :data:`SCHEMA_REGISTRY` (a dict keyed by entity name) and the
:func:`register`, :func:`validate`, :func:`from_dict`, :func:`to_dict`
helpers. Consumers should never construct SchemaEntry directly;
use the :func:`register` decorator or the :func:`register` function
from the entity module.
"""

from __future__ import annotations

from typing import Any

import msgspec

from dhara.schema._base import SchemaEntry, SchemaValidationError

SCHEMA_REGISTRY: dict[str, SchemaEntry] = {}


def register(name: str, entry: SchemaEntry) -> None:
    """Register a schema entry. Raises ValueError on duplicate name."""
    if name in SCHEMA_REGISTRY:
        raise ValueError(f"Schema {name!r} already registered")
    SCHEMA_REGISTRY[name] = entry


def validate(name: str, payload: dict) -> msgspec.Struct:
    """Validate a payload against a registered schema. Returns the Struct instance."""
    entry = SCHEMA_REGISTRY.get(name)
    if entry is None:
        raise SchemaValidationError(f"Unknown schema: {name!r}")
    try:
        return msgspec.convert(payload, entry.struct)
    except msgspec.ValidationError as e:
        raise SchemaValidationError(str(e)) from e


def from_dict(
    name: str, payload: dict, *, version: str | None = None
) -> msgspec.Struct:
    """Decode a payload into a Struct. Apply migrations if a non-current version is given."""
    entry = SCHEMA_REGISTRY.get(name)
    if entry is None:
        raise SchemaValidationError(f"Unknown schema: {name!r}")
    if version is not None and version != entry.version:
        migrate = entry.migrations.get(f"{version} -> {entry.version}")
        if migrate is not None:
            payload = migrate(payload)
    try:
        return msgspec.convert(payload, entry.struct)
    except msgspec.ValidationError as e:
        raise SchemaValidationError(str(e)) from e


def to_dict(entity: msgspec.Struct) -> dict[str, Any]:
    """Serialize a Struct to a JSON-compatible dict."""
    return msgspec.to_builtins(entity)
