from __future__ import annotations
import dataclasses
import pytest
from dhara.schema._base import SchemaEntry, SchemaValidationError


def test_schema_entry_is_frozen_dataclass() -> None:
    """SchemaEntry is a frozen dataclass so the registry cannot be mutated after registration."""
    entry = SchemaEntry(
        name="test",
        version="1.0.0",
        struct=dict,  # placeholder; we'll use a real Struct in registry tests
        migrations={},
    )
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        entry.name = "other"  # type: ignore[misc]


def test_schema_validation_error_is_an_exception() -> None:
    """SchemaValidationError is a regular Exception subclass."""
    err = SchemaValidationError("bad")
    assert isinstance(err, Exception)
    assert str(err) == "bad"