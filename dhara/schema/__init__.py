"""D-OBJ-SCHEMA — typed object schemas for the engine.

This module exposes the schema registry infrastructure plus the one
surviving engine-side entity schema (``ChannelSessionState``).

Surviving schemas:

- :class:`ChannelSessionState` (engine-side — durable channel session
  record). The ``metadata`` field carries session-versioning extension
  keys (version, parent_session_id, branch_reason).

Plus the central registry (:func:`SCHEMA_REGISTRY`, :func:`validate`,
:func:`from_dict`, :func:`to_dict`) for runtime validation.

The previously-exported Bodai-flavored schemas (``approval_log``,
``audit_record``, ``capability_descriptor``, ``ecosystem_run_record``,
``webhook_ingress``, ``workflow_outcome``) were removed in Wave 2 — they
served Bodai consumers (mahavishnu, session-buddy, akosha) that have all
migrated off Dhara. Engine-side persistence is unaffected.
"""

from __future__ import annotations

from dhara.schema._base import SchemaEntry, SchemaValidationError
from dhara.schema._registry import (
    SCHEMA_REGISTRY,
    from_dict,
    register,
    to_dict,
    validate,
)

# Re-export entity Struct classes and STRUCT aliases for ergonomic imports.
from dhara.schema.channel_session_state import STRUCT as channel_session_state
from dhara.schema.channel_session_state import ChannelSessionState

__all__ = [
    "SCHEMA_REGISTRY",
    "ChannelSessionState",
    "SchemaEntry",
    "SchemaValidationError",
    "channel_session_state",
    "from_dict",
    "register",
    "to_dict",
    "validate",
]
