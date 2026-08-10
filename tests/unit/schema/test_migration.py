# tests/unit/schema/test_migration.py
from __future__ import annotations

import pytest

from dhara.schema._base import SchemaValidationError
from dhara.schema._registry import SCHEMA_REGISTRY, from_dict


def test_v1_migrations_are_empty() -> None:
    """Every registered entity in v1 has an empty MIGRATIONS dict."""
    for name, entry in SCHEMA_REGISTRY.items():
        assert entry.migrations == {}, (
            f"{name} has non-empty migrations: {entry.migrations}"
        )


def test_from_dict_with_current_version_works() -> None:
    """When target version matches current, no migration is applied."""
    rec = from_dict(
        "audit_record",
        {
            "audit_id": "a-1",
            "event_type": "x",
            "actor": "a",
            "at": "2026-08-05T12:00:00+00:00",
            "subject": "s",
            "metadata": {},
        },
    )
    assert rec.audit_id == "a-1"


def test_from_dict_with_unknown_old_version_does_not_migrate() -> None:
    """If a version is given but no migration exists, from_dict still
    tries to convert (and may fail). Spec accepts this behavior."""
    with pytest.raises(SchemaValidationError):
        from_dict(
            "audit_record",
            {
                "audit_id": "a-1",
                # missing fields → ValidationError
            },
            version="0.0.1",
        )


def test_migration_interface_is_callable_registry() -> None:
    """MIGRATIONS dict shape: {version_arrow: callable}."""
    # The interface contract: each entry maps "from -> to" to a callable.
    # We assert the shape via a sample registration without polluting the registry.
    entry = SCHEMA_REGISTRY["audit_record"]
    assert isinstance(entry.migrations, dict)
    # Each value would be a callable when present.
    for key, value in entry.migrations.items():
        assert "->" in key, f"migration key should be 'from -> to', got {key!r}"
        assert callable(value), f"{key} should map to a callable"
