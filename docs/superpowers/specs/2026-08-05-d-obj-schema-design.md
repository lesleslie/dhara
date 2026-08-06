______________________________________________________________________

## status: draft role: per-primitive-spec date: 2026-08-05 last_reviewed: 2026-08-05 superseded_by: null blocks_on: [D-LOCK] topic: typed-object-schemas, substrate-primitive, cross-system-shapes

# D-OBJ-SCHEMA Design — Typed Object Schemas for Cross-System Durable Entities

**Date:** 2026-08-05
**Status:** Draft (pending user review)
**Owner:** Dhara (Layer 0 substrate)
**Author:** Claude (Mahavishnu Orchestrator, brainstorming session)
**Purpose:** Ship a typed-object-schema substrate primitive that defines the canonical shapes for the five cross-system durable entities called out in the 2026-08-03 portfolio spec. Provides a single source of truth for `workflow_outcome`, `approval_log`, `channel_session_state`, `webhook_ingress`, and `audit_record` so downstream consumers (M-INFRA, S-MEM, A-RUBRIC, D-AUDIT) coordinate on identical shapes without each repo re-inventing its own pydantic/msgspec definitions.

______________________________________________________________________

## Context

D-LOCK shipped on 2026-08-04 (Layer 0 substrate primitive #1). The 2026-08-03 portfolio spec calls out D-OBJ-SCHEMA as Layer 0 primitive #2 — the typed object schemas that every Layer 1 durable primitive consumes. Without a shared schema layer, M-WORKFLOW-OUTCOME, M-APPROVAL-LOG, A-EVENT-LOG, A-RUBRIC-TABLE, and S-MEM-VERSIONS each invent their own object shape, and cross-system payloads (REST, observability, audit) drift.

The portfolio spec frames D-OBJ-SCHEMA as the foundational shape layer that ships "first" in the D-WIRE sequence (per §Sequencing: "D-OBJ-SCHEMA first (defines the shapes every other durable primitive consumes)").

Existing prior art in Dhara:
- `dhara/serialize/factory.py` and `dhara/serialize/msgspec.py` already wrap msgspec for low-level wire-format serialization. D-OBJ-SCHEMA does NOT replace those — it sits above them as the typed-shape layer.
- `dhara/serialize/record.py` defines the `Persistent` adapter for object-graph serialization. D-OBJ-SCHEMA provides the typed SHAPES that flow through that adapter.

Open question #1 from the portfolio ("Dhara ownership of typed schemas") was resolved in brainstorming: D-OBJ-SCHEMA lives in Dhara (same substrate repo as D-LOCK), not in a shared `bodai-contracts` package.

## Goals

1. Ship a typed-object-schema primitive (`dhara.schema`) that defines the 5 cross-system durable entities called out in the portfolio.
2. Provide a single source of truth for each entity's shape, version, and migration path. Consumers REGISTER the entity centrally; cross-system code reads the registered schema, not a re-defined local shape.
3. Three surface guarantees: write-time validation (malformed payload rejected at the boundary), read-time decoding (handle schema drift), and version migration (additive fields only for v1).
4. Decouple schema definition from persistence. D-OBJ-SCHEMA does NOT store any data; persistence is the consumer's job (each owning repo uses Durus-style `Persistent` or `substrate_locks` for its own writes).
5. Mirror the D-LOCK substrate pattern: Protocol + concrete impl + tests + observability + REST surface (where applicable). For D-OBJ-SCHEMA, the "REST surface" is just the schema registry (no HTTP endpoints).

## Non-goals

- D-OBJ-SCHEMA does NOT provide Dhara persistence. Each consumer writes its own Durus `Persistent` objects using the schema-defined shapes.
- D-OBJ-SCHEMA does NOT provide REST endpoints. Schemas are data, not services.
- D-OBJ-SCHEMA does NOT provide observability events. Consumers emit their own events; D-OBJ-SCHEMA only stores the `audit_record` shape they fill in.
- D-OBJ-SCHEMA does NOT provide schema-versioning across major versions. v1 disallows breaking changes (additive fields only); major version migrations are deferred.

## Architecture overview

Per-entity modules + central registry:

```
dhara/schema/
├── __init__.py              # Public API: SCHEMA_REGISTRY, validate, from_dict, to_dict
├── _base.py                 # SchemaEntry, SCHEMA_VERSION helpers, Protocol
├── _registry.py             # Central SCHEMA_REGISTRY dict; register() decorator
├── workflow_outcome.py      # msgspec.Struct + SCHEMA_VERSION
├── approval_log.py          # msgspec.Struct + SCHEMA_VERSION
├── channel_session_state.py # msgspec.Struct + SCHEMA_VERSION
├── webhook_ingress.py       # msgspec.Struct + SCHEMA_VERSION
└── audit_record.py          # msgspec.Struct + SCHEMA_VERSION
```

Each entity module exports:
- `STRUCT` — the msgspec.Struct class
- `SCHEMA_VERSION` — `Literal["1.0.0"]` (v1 starts at 1.0.0)
- `MIGRATIONS` — `dict[str, Callable[[dict], dict]]` (empty for v1; populated when fields evolve)

The central registry (`dhara/schema/_registry.py`) exposes:
- `SCHEMA_REGISTRY: dict[str, SchemaEntry]` — keyed by entity name (`"workflow_outcome"`, etc.)
- `register(entity_name: str)` — decorator for entity modules
- `validate(entity_name: str, payload: dict) -> Struct` — write-time validation; raises `SchemaValidationError` on mismatch
- `from_dict(entity_name: str, payload: dict, *, version: str | None = None) -> Struct` — read-time decoding + optional migration
- `to_dict(entity: Struct) -> dict` — JSON-compatible serialization

The public API in `dhara/schema/__init__.py` re-exports the 5 entity names + the registry helpers. Consumers do `from dhara.schema import workflow_outcome, validate, SCHEMA_REGISTRY`.

## Data model

The 5 entities are typed shapes with a small, focused field set. Each MUST be additive-only within v1 (no breaking changes). Initial field sets:

| Entity | Owner | Fields |
|---|---|---|
| `workflow_outcome` | M-INFRA | `workflow_id: str`, `status: Literal["succeeded", "failed", "cancelled"]`, `started_at: datetime`, `finished_at: datetime`, `metadata: dict[str, Any]` |
| `approval_log` | M-INFRA | `approval_id: str`, `actor: str`, `action: Literal["approved", "denied", "requested"]`, `at: datetime`, `metadata: dict[str, Any]` |
| `channel_session_state` | S-MEM | `channel_id: str`, `channel_type: str`, `sender_id: str`, `last_event_at: datetime`, `metadata: dict[str, Any]` |
| `webhook_ingress` | M-INFRA | `webhook_id: str`, `source: str`, `received_at: datetime`, `payload_hash: str`, `metadata: dict[str, Any]` |
| `audit_record` | D-AUDIT | `audit_id: str`, `event_type: str`, `actor: str`, `at: datetime`, `subject: str`, `metadata: dict[str, Any]` |

Each entity:

- Uses `msgspec.Struct` (not `BaseModel`, not `dataclass`) for performance + native Python typing.
- All `datetime` fields use `datetime` (timezone-aware) — `msgspec` requires strict types; no `datetime.now()` without `[UTC, datetime]`.
- `metadata: dict[str, Any]` is the escape hatch for evolving fields. Callers may attach new top-level keys there without consuming a schema-migration slot.
- `SCHEMA_VERSION = "1.0.0"` for v1. Bumping to "1.0.1" means ADDITIVE (new field with default). "2.0.0" means breaking (rename, remove, type change).

## Consumers (downstream)

The portfolio spec uses these 5 entities across 5+ consumers:

| Consumer | Entity(es) used | Where it writes |
|---|---|---|
| M-WORKFLOW-OUTCOME | `workflow_outcome` | `workflow-results/{workflow_id}/` (Dhara paths) |
| M-APPROVAL-LOG | `approval_log` | Approval history storage |
| M-WEBHOOK-DURABLE | `webhook_ingress` | MemoryOutbox webhook storage |
| S-CHANNEL-DURABLE | `channel_session_state` | `_ChannelSessionStore` |
| S-MEM-VERSIONS | `channel_session_state.metadata` (versions extension) | session-buddy parent_session_id |
| A-EVENT-LOG | `audit_record` | Akosha durable event log |
| A-RUBRIC-TABLE | `audit_record.metadata` (rubric scoring) | `rubrics` table |
| D-AUDIT | `audit_record` | substrate audit log |
| Precommit CLI | `audit_record` (absorbed via D-LOCK `permanent=True`) | substrate_locks.metadata |

D-OBJ-SCHEMA does NOT enforce which consumer uses which entity. It only provides the shape. Consumers register their usage through the central registry if they want to participate in cross-system observability.

## Per-entity contract

Every entity follows the same module shape:

```python
# dhara/schema/audit_record.py
"""Audit record — substrate audit log entry."""

from __future__ import annotations
from datetime import datetime
from typing import Any, Literal

import msgspec

SCHEMA_VERSION: str = "1.0.0"

# Empty for v1; populated when fields evolve additively.
MIGRATIONS: dict[str, "callable"] = {}

class AuditRecord(msgspec.Struct, frozen=True):
    """Substrate audit log entry. Written by every durable primitive."""
    audit_id: str
    event_type: str
    actor: str
    at: datetime
    subject: str
    metadata: dict[str, Any] = msgspec.field(default_factory=dict)

STRUCT = AuditRecord
```

Plus the `register("audit_record")` decorator at module bottom (or in `__init__.py`). The registry stores:

```python
@dataclass(frozen=True)
class SchemaEntry:
    name: str
    version: str
    struct: type[msgspec.Struct]
    migrations: dict[str, Callable]
```

## Validation surface

Write-time (entry boundary):
```python
from dhara.schema import validate, SchemaValidationError

# At the boundary (e.g., REST endpoint, MCP tool, webhook ingress):
try:
    record = validate("audit_record", raw_payload)
except SchemaValidationError as e:
    return 4xx response
```

Read-time (decode + migrate):
```python
from dhara.schema import from_dict

# At Dhara deserialization time:
record = from_dict("audit_record", stored_dict)  # dispatches to AuditRecord
```

Both paths yield the same `msgspec.Struct` instance. Consumers should treat the `Struct` as the canonical Python object; round-trip through `to_dict()` if they need JSON.

## Versioning and migration

For v1: **additive fields only**. The migration registry is empty. New fields can be added with `msgspec.field(default_factory=...)` defaults backwards-compatibly.

If a v1 entity needs to evolve in a breaking way:

1. Bump `SCHEMA_VERSION` to "1.0.1" (additive) or "2.0.0" (breaking).
2. Add a migration entry: `MIGRATIONS["1.0.0 -> 1.0.1"] = lambda payload: {**payload, "new_field": "default"}`.
3. Bumping to "2.0.0" is out of scope for v1; out of scope for D-OBJ-SCHEMA's first implementation.

Consumers reading old data call `from_dict(entity_name, payload, version=old_version)` and the registry auto-applies migrations up to the current `SCHEMA_VERSION`.

## Observability

D-OBJ-SCHEMA does NOT emit events. Consumers emit their own events; the schema is the payload shape, not the trigger.

Reporting items (per `feature-tracking/TEMPLATE.md`):
- Shipped: `dhara.schema` module with 5 entities + registry.
- Wired: registered by D-LOCK (`audit_record.metadata` via `permanent=True`); registered by M-INFRA (workflow_outcome, approval_log, webhook_ingress).
- Adopted: at least one cross-system consumer (Mahavishnu or Akosha) reads/writes a registered entity in a real workflow.

## Testing (TDD)

The spec ships with tests written BEFORE the impl (per project CLAUDE.md TDD discipline):

1. `tests/unit/schema/test_workflow_outcome.py` — round-trip via `to_dict` / `from_dict`; missing field raises `SchemaValidationError`; extra field raises `SchemaValidationError`.
2. `tests/unit/schema/test_audit_record.py` — same RED/GREEN pattern for the canonical entity.
3. `tests/unit/schema/test_registry.py` — `SCHEMA_REGISTRY` contains all 5 entities by v1; `register()` decorator populates new entries; `validate(name, payload)` returns the right Struct.
4. `tests/unit/schema/test_migration.py` — v1 migrations are empty; `from_dict` round-trips unchanged; future migration entries apply correctly (covered by a mocked-up example).
5. `tests/unit/schema/test_cross_system_consistency.py` — the 5 entities share the same base invariants (datetime fields, metadata field, frozen=True).

Test count budget: 5 test files × ~3-5 tests each = ~15-25 tests. All must pass.

## Integration Contract

**Triggered from:** Any cross-system code that writes a durable entity (M-WORKFLOW-OUTCOME, M-APPROVAL-LOG, A-EVENT-LOG, S-CHANNEL-DURABLE, D-AUDIT, M-WEBHOOK-DURABLE, A-RUBRIC-TABLE, precommit CLI on `permanent=True`).
**Returns to / updates:** None (D-OBJ-SCHEMA is data-only; consumers update their own durable storage).
**Demonstrable by:** `pytest tests/unit/schema/ -v` → 15+ tests pass; `python -c "from dhara.schema import SCHEMA_REGISTRY; print(list(SCHEMA_REGISTRY))"` lists all 5 entities.
**Rollback signal:** Downstream consumer can't validate a payload it previously accepted → check `SCHEMA_REGISTRY` for missing entry; revert per-entity module commit.
**Observability added:** None (consumers emit their own events; D-OBJ-SCHEMA is shape-only).

## Spec coverage map

| Spec section / requirement | Covered by |
|---|---|
| Goal #1 — typed object schemas for 5 entities | 5 entity modules + registry |
| Goal #2 — single source of truth | `SCHEMA_REGISTRY` + `register()` |
| Goal #3 — write-time + read-time validation + version migration | `validate()` + `from_dict()` + `MIGRATIONS` |
| Goal #4 — decoupled from persistence | (no Dhara persistence in D-OBJ-SCHEMA) |
| Goal #5 — substrate pattern (Protocol + concrete + tests) | `_base.py::SchemaEntry` + `_registry.py` + tests |
| Architecture: per-entity modules + central registry | `dhara/schema/` layout |
| Test budget (5+ files, 15+ tests) | `tests/unit/schema/` |
| Integration Contract | 5 consumers registered |

## Open questions for the planning phase

1. **Frozen=True semantics**: Should entities be `frozen=True` (immutable Struct) or mutable? Frozen is safer for audit logs; mutable is friendlier for in-place updates. Recommend frozen=True for v1 (audit-log use case dominates).
2. **datetime tz enforcement**: msgspec requires strict types. Should we use `datetime` (which permits naive) or `Annotated[datetime, BeforeValidator(add_utc_tz)]` (forces tz-aware)? Recommend `datetime` for v1; tz enforcement is a consumer concern.
3. **Registry global vs. injected**: The `SCHEMA_REGISTRY` is a module-level singleton. Is that idiomatic for msgspec + Bodai patterns, or should it be constructor-injected? Recommend module-level for v1 (matches D-LOCK's module-level `DharaLock` Protocol pattern).
4. **What gets shipped in `dhara/schema/__init__.py`?**: All 5 entities exposed + `SCHEMA_REGISTRY` + `validate` + `from_dict` + `to_dict` + `SchemaValidationError`. Consumers should be able to import everything from the top-level package.

## Appendix A — Two illustrative entities (full source)

```python
# dhara/schema/audit_record.py
from __future__ import annotations
from datetime import datetime
from typing import Any
import msgspec
from dhara.schema._base import SchemaEntry, register

SCHEMA_VERSION: str = "1.0.0"
MIGRATIONS: dict[str, "callable"] = {}

class AuditRecord(msgspec.Struct, frozen=True):
    audit_id: str
    event_type: str
    actor: str
    at: datetime
    subject: str
    metadata: dict[str, Any] = msgspec.field(default_factory=dict)

STRUCT = AuditRecord
register("audit_record", SchemaEntry(
    name="audit_record",
    version=SCHEMA_VERSION,
    struct=STRUCT,
    migrations=MIGRATIONS,
))
```

```python
# dhara/schema/_registry.py
from __future__ import annotations
from typing import Callable
import msgspec
from dhara.schema._base import SchemaEntry, SchemaValidationError

SCHEMA_REGISTRY: dict[str, SchemaEntry] = {}

def register(name: str, entry: SchemaEntry) -> None:
    if name in SCHEMA_REGISTRY:
        raise ValueError(f"Schema {name!r} already registered")
    SCHEMA_REGISTRY[name] = entry

def validate(name: str, payload: dict) -> msgspec.Struct:
    entry = SCHEMA_REGISTRY.get(name)
    if entry is None:
        raise SchemaValidationError(f"Unknown schema: {name!r}")
    try:
        return msgspec.convert(payload, entry.struct)
    except msgspec.ValidationError as e:
        raise SchemaValidationError(str(e)) from e

def from_dict(name: str, payload: dict, *, version: str | None = None) -> msgspec.Struct:
    entry = SCHEMA_REGISTRY.get(name)
    if entry is None:
        raise SchemaValidationError(f"Unknown schema: {name!r}")
    # Run migrations from old version to current if necessary
    if version is not None and version != entry.version:
        migrate = entry.migrations.get(f"{version} -> {entry.version}")
        if migrate is not None:
            payload = migrate(payload)
    return msgspec.convert(payload, entry.struct)

def to_dict(entity: msgspec.Struct) -> dict:
    return msgspec.to_builtins(entity)
```

## Appendix B — What D-OBJ-SCHEMA does NOT do

- ❌ Persist data
- ❌ Emit observability events
- ❌ Provide REST endpoints
- ❌ Provide a CLI
- ❌ Provide a Dhara connection (storage is consumer's responsibility)
- ❌ Cross-version migrations across major versions (v1 disallows breaking changes)

Its surface is intentionally minimal: **shape definitions + validation + migration + serialization**. The 5 entities are the "single source of truth" for cross-system durable payloads.
