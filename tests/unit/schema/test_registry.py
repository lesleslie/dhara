from __future__ import annotations

import msgspec
import pytest

from dhara.schema._base import SchemaEntry, SchemaValidationError
from dhara.schema._registry import (
    SCHEMA_REGISTRY,
    from_dict,
    register,
    to_dict,
    validate,
)


# Use a simple struct for testing the registry
class SampleEntity(msgspec.Struct, frozen=True):
    name: str
    value: int


SAMPLE_ENTRY = SchemaEntry(
    name="sample",
    version="1.0.0",
    struct=SampleEntity,
    migrations={},
)


def test_validate_returns_struct_on_valid_payload() -> None:
    register("sample_test", SAMPLE_ENTRY)
    try:
        result = validate("sample_test", {"name": "x", "value": 1})
        assert isinstance(result, SampleEntity)
        assert result.name == "x"
        assert result.value == 1
    finally:
        SCHEMA_REGISTRY.pop("sample_test", None)


def test_validate_raises_on_unknown_schema() -> None:
    with pytest.raises(SchemaValidationError, match="Unknown schema"):
        validate("nonexistent", {})


def test_validate_raises_on_invalid_payload() -> None:
    register("sample_test2", SAMPLE_ENTRY)
    try:
        # Missing required field "value"
        with pytest.raises(SchemaValidationError):
            validate("sample_test2", {"name": "x"})
    finally:
        SCHEMA_REGISTRY.pop("sample_test2", None)


def test_from_dict_roundtrips_payload() -> None:
    register("sample_test3", SAMPLE_ENTRY)
    try:
        result = from_dict("sample_test3", {"name": "x", "value": 42})
        assert result.value == 42
    finally:
        SCHEMA_REGISTRY.pop("sample_test3", None)


def test_to_dict_roundtrips_payload() -> None:
    entity = SampleEntity(name="x", value=42)
    d = to_dict(entity)
    assert d == {"name": "x", "value": 42}


def test_register_raises_on_duplicate() -> None:
    register("sample_dup", SAMPLE_ENTRY)
    try:
        with pytest.raises(ValueError, match="already registered"):
            register("sample_dup", SAMPLE_ENTRY)
    finally:
        SCHEMA_REGISTRY.pop("sample_dup", None)
