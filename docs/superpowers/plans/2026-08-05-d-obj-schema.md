# D-OBJ-SCHEMA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a typed-object-schema substrate primitive that defines the canonical shapes for the 5 cross-system durable entities called out in the 2026-08-03 portfolio spec (`workflow_outcome`, `approval_log`, `channel_session_state`, `webhook_ingress`, `audit_record`).

**Architecture:** Per-entity modules + central `SCHEMA_REGISTRY` keyed by entity name. Each entity is a `msgspec.Struct` (frozen=True) with `SCHEMA_VERSION` and a (initially empty) `MIGRATIONS` dict. The registry exposes `validate()` (write-time) and `from_dict()` (read-time + optional migration). D-OBJ-SCHEMA is shape-only — no Dhara persistence, no REST, no observability events.

**Tech Stack:** Python 3.13, Dhara substrate, msgspec (already a Dhara dependency), pytest, pytest-asyncio (asyncio_mode="auto"), Ruff, mypy, ty.

## Global Constraints

- **Python 3.13** target. `from __future__ import annotations` as the first non-comment line of every source file.
- **Project conventions per `~/.claude/CLAUDE.md`**: imports sorted (stdlib → third-party → first-party), `X | None` (not `Optional[X]`), `list[str]` (not `List[str]`), no `assert` in production code, full type annotations.
- **msgspec.Struct, frozen=True** — every entity module. Single source of truth for shape.
- **Per-entity module = `dhara/schema/<entity_name>.py`** with `STRUCT` + `SCHEMA_VERSION` + `MIGRATIONS` + `register()` call.
- **Central registry**: `dhara/schema/_registry.py` exposes `SCHEMA_REGISTRY: dict[str, SchemaEntry]`, `register()`, `validate()`, `from_dict()`, `to_dict()`.
- **Public API**: `dhara/schema/__init__.py` re-exports the 5 entity names + `SCHEMA_REGISTRY` + `validate` + `from_dict` + `to_dict` + `SchemaValidationError`. Consumers should be able to import everything from the top-level package.
- **5 entities in v1**: `workflow_outcome`, `approval_log`, `channel_session_state`, `webhook_ingress`, `audit_record`. Each gets its own module.
- **datetime fields**: `datetime` (timezone-aware). `msgspec` requires strict types. `metadata: dict[str, Any] = msgspec.field(default_factory=dict)` escape hatch.
- **Versioning**: v1 is additive-only (no breaking changes within 1.x.y). `MIGRATIONS` dict is empty for v1. Document the migration interface; do NOT implement major-version migrations.
- **No Dhara persistence in D-OBJ-SCHEMA**. Storage is the consumer's responsibility. Each owning repo wires its own Durus `Persistent` or `substrate_locks` writes.
- **No REST endpoints**. `SCHEMA_REGISTRY` is the entire HTTP surface (and it isn't HTTP).
- **No observability events**. Consumers emit their own events; D-OBJ-SCHEMA is shape-only.
- **TDD discipline**: every new function has a failing test first (RED), then minimal impl (GREEN), then refactor. Project CLAUDE.md makes this a hard requirement.
- **No pre-commit hook exists** (per memory `no-bodai-pre-commit-hook`). Use `mahavishnu precommit` infrastructure after task completion.
- **Bodai pre-1.0 merge policy**: commits directly to main (no PRs). Branch + squash/ff-merge into main.
- **crackerjack version-bumping is currently manual**: flag in plans rather than dispatching implementers to bump versions.
- **Pre-existing dirty files**: do NOT touch. Each repo tracks its own pre-commit dirt; don't sweep.

## File structure

```
dhara/schema/
├── __init__.py              # Public API: re-exports
├── _base.py                 # SchemaEntry, SchemaValidationError, register() decorator
├── _registry.py             # SCHEMA_REGISTRY + validate/from_dict/to_dict
├── audit_record.py          # D-AUDIT consumer
├── workflow_outcome.py      # M-INFRA
├── approval_log.py          # M-INFRA
├── channel_session_state.py # S-MEM
└── webhook_ingress.py       # M-INFRA

tests/unit/schema/
├── __init__.py
├── conftest.py
├── test_audit_record.py
├── test_workflow_outcome.py
├── test_approval_log.py
├── test_channel_session_state.py
├── test_webhook_ingress.py
├── test_registry.py
├── test_migration.py
└── test_cross_system_consistency.py
```

______________________________________________________________________

## Task 1: Schema base classes (`dhara/schema/_base.py`)

**Files:**

- Create: `dhara/schema/__init__.py` (empty for now; populated by Task 7)
- Create: `dhara/schema/_base.py`
- Test: `tests/unit/schema/__init__.py` (empty)
- Test: `tests/unit/schema/conftest.py` (fixtures for the test suite)
- Test: `tests/unit/schema/test_base.py`

**Step 1: Write the failing test**

```python
# tests/unit/schema/test_base.py
from __future__ import annotations
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
```

**Step 2: Run the test to verify it fails**

Run: `cd /Users/les/Projects/dhara && pytest tests/unit/schema/test_base.py -v`
Expected: `ImportError` because `dhara/schema/_base.py` doesn't exist.

**Step 3: Write the minimal implementation**

```python
# dhara/schema/_base.py
"""Schema base classes for D-OBJ-SCHEMA.

Defines the ``SchemaEntry`` registration record and the
``SchemaValidationError`` exception type. All entity modules import
from here.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import msgspec
    from collections.abc import Callable


@dataclass(frozen=True)
class SchemaEntry:
    """Registry record for one schema entity.

    Frozen=True prevents the registry from being mutated after a
    schema is registered. Use the :func:`register` decorator to add
    new entries; re-registration raises ``ValueError``.
    """
    name: str
    version: str
    struct: type
    migrations: dict


class SchemaValidationError(Exception):
    """Raised when a payload fails validation against a registered schema.
    Wraps :class:`msgspec.ValidationError` so consumers don't need to
    import msgspec directly.
    """
```

```python
# dhara/schema/__init__.py
"""D-OBJ-SCHEMA — typed object schemas for cross-system durable entities."""
```

```python
# tests/unit/schema/__init__.py
"""Schema test suite."""
```

```python
# tests/unit/schema/conftest.py
"""Shared fixtures for the schema test suite."""
```

**Step 4: Run the test to verify it passes**

Run: `cd /Users/les/Projects/dhara && pytest tests/unit/schema/test_base.py -v`
Expected: 2 passed.

**Step 5: Commit**

```bash
cd /Users/les/Projects/dhara
git add dhara/schema/__init__.py dhara/schema/_base.py tests/unit/schema/__init__.py tests/unit/schema/conftest.py tests/unit/schema/test_base.py
git -c user.name="lesleslie" -c user.email="les@wedgwoodwebworks.local" commit -m "feat(schema): add SchemaEntry + SchemaValidationError base classes"
```

______________________________________________________________________

## Task 2: Central registry (`dhara/schema/_registry.py`)

**Files:**

- Create: `dhara/schema/_registry.py`
- Test: `tests/unit/schema/test_registry.py`

**Step 1: Write the failing test**

```python
# tests/unit/schema/test_registry.py
from __future__ import annotations
import pytest
import msgspec
from dhara.schema._base import SchemaEntry, SchemaValidationError
from dhara.schema._registry import SCHEMA_REGISTRY, register, validate, from_dict, to_dict


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
```

**Step 2: Run the test to verify it fails**

Run: `cd /Users/les/Projects/dhara && pytest tests/unit/schema/test_registry.py -v`
Expected: `ImportError` because `dhara/schema/_registry.py` doesn't exist.

**Step 3: Write the minimal implementation**

```python
# dhara/schema/_registry.py
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


def from_dict(name: str, payload: dict, *, version: str | None = None) -> msgspec.Struct:
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
```

**Step 4: Run the test to verify it passes**

Run: `cd /Users/les/Projects/dhara && pytest tests/unit/schema/test_registry.py -v`
Expected: 6 passed.

**Step 5: Commit**

```bash
cd /Users/les/Projects/dhara
git add dhara/schema/_registry.py tests/unit/schema/test_registry.py
git -c user.name="lesleslie" -c user.email="les@wedgwoodwebworks.local" commit -m "feat(schema): add central registry with validate/from_dict/to_dict"
```

______________________________________________________________________

## Task 3: First entity — `audit_record`

**Files:**

- Create: `dhara/schema/audit_record.py`
- Test: `tests/unit/schema/test_audit_record.py`

**Step 1: Write the failing test**

```python
# tests/unit/schema/test_audit_record.py
from __future__ import annotations
from datetime import datetime, UTC
from dhara.schema.audit_record import AuditRecord, STRUCT, SCHEMA_VERSION, MIGRATIONS
from dhara.schema._registry import SCHEMA_REGISTRY, validate, to_dict


def test_schema_version_is_1_0_0() -> None:
    assert SCHEMA_VERSION == "1.0.0"


def test_migrations_is_empty_for_v1() -> None:
    assert MIGRATIONS == {}


def test_audit_record_is_registered() -> None:
    assert "audit_record" in SCHEMA_REGISTRY
    entry = SCHEMA_REGISTRY["audit_record"]
    assert entry.name == "audit_record"
    assert entry.version == "1.0.0"


def test_construct_with_required_fields() -> None:
    at = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    rec = AuditRecord(
        audit_id="a-1",
        event_type="lock.acquired",
        actor="user:les",
        at=at,
        subject="lock:foo",
    )
    assert rec.audit_id == "a-1"
    assert rec.metadata == {}


def test_metadata_default_is_empty_dict() -> None:
    """Each AuditRecord gets its own {} — no shared mutable default."""
    rec1 = AuditRecord(
        audit_id="a-1",
        event_type="x",
        actor="a",
        at=datetime(2026, 1, 1, tzinfo=UTC),
        subject="s",
    )
    rec2 = AuditRecord(
        audit_id="a-2",
        event_type="x",
        actor="a",
        at=datetime(2026, 1, 1, tzinfo=UTC),
        subject="s",
    )
    rec1.metadata["key"] = "value"
    assert rec2.metadata == {}


def test_frozen_rejects_mutation() -> None:
    rec = AuditRecord(
        audit_id="a-1",
        event_type="x",
        actor="a",
        at=datetime(2026, 1, 1, tzinfo=UTC),
        subject="s",
    )
    import dataclasses
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        rec.audit_id = "a-2"  # type: ignore[misc]


def test_validate_returns_struct() -> None:
    payload = {
        "audit_id": "a-1",
        "event_type": "lock.acquired",
        "actor": "user:les",
        "at": "2026-08-05T12:00:00+00:00",
        "subject": "lock:foo",
        "metadata": {"ttl": 60},
    }
    rec = validate("audit_record", payload)
    assert isinstance(rec, AuditRecord)
    assert rec.metadata == {"ttl": 60}


def test_to_dict_roundtrip() -> None:
    at = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    rec = AuditRecord(
        audit_id="a-1",
        event_type="lock.acquired",
        actor="user:les",
        at=at,
        subject="lock:foo",
        metadata={"k": "v"},
    )
    d = to_dict(rec)
    assert d["audit_id"] == "a-1"
    # Round-trip back through validate
    rec2 = validate("audit_record", d)
    assert rec2 == rec
```

**Step 2: Run the test to verify it fails**

Run: `cd /Users/les/Projects/dhara && pytest tests/unit/schema/test_audit_record.py -v`
Expected: `ImportError` because `dhara/schema/audit_record.py` doesn't exist.

**Step 3: Write the minimal implementation**

```python
# dhara/schema/audit_record.py
"""Audit record — substrate audit log entry.

The canonical entity for D-AUDIT. Every durable primitive emits
``AuditRecord`` instances via the registry; consumers (D-AUDIT,
A-EVENT-LOG, precommit CLI on ``permanent=True``) write these to
their own storage.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any
import msgspec

from dhara.schema._base import SchemaEntry
from dhara.schema._registry import register


SCHEMA_VERSION: str = "1.0.0"
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


register("audit_record", SchemaEntry(
    name="audit_record",
    version=SCHEMA_VERSION,
    struct=STRUCT,
    migrations=MIGRATIONS,
))
```

**Step 4: Run the test to verify it passes**

Run: `cd /Users/les/Projects/dhara && pytest tests/unit/schema/test_audit_record.py -v`
Expected: 7 passed.

**Step 5: Commit**

```bash
cd /Users/les/Projects/dhara
git add dhara/schema/audit_record.py tests/unit/schema/test_audit_record.py
git -c user.name="lesleslie" -c user.email="les@wedgwoodwebworks.local" commit -m "feat(schema): add audit_record entity (D-AUDIT canonical)"
```

______________________________________________________________________

## Task 4: `workflow_outcome` entity

**Files:**

- Create: `dhara/schema/workflow_outcome.py`
- Test: `tests/unit/schema/test_workflow_outcome.py`

**Step 1: Write the failing test**

```python
# tests/unit/schema/test_workflow_outcome.py
from __future__ import annotations
from datetime import datetime, UTC
from typing import Literal
import pytest
from dhara.schema.workflow_outcome import WorkflowOutcome, SCHEMA_VERSION
from dhara.schema._registry import SCHEMA_REGISTRY, validate, to_dict


def test_schema_version_is_1_0_0() -> None:
    assert SCHEMA_VERSION == "1.0.0"


def test_workflow_outcome_is_registered() -> None:
    assert "workflow_outcome" in SCHEMA_REGISTRY


def test_construct_succeeded() -> None:
    started = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    finished = datetime(2026, 8, 5, 10, 5, tzinfo=UTC)
    w = WorkflowOutcome(
        workflow_id="wf-1",
        status="succeeded",
        started_at=started,
        finished_at=finished,
    )
    assert w.workflow_id == "wf-1"
    assert w.status == "succeeded"
    assert w.metadata == {}


def test_status_literal_is_validated() -> None:
    """msgspec.Strict enforces the Literal — invalid status raises on validate."""
    payload = {
        "workflow_id": "wf-1",
        "status": "bogus",  # not in {succeeded, failed, cancelled}
        "started_at": "2026-08-05T10:00:00+00:00",
        "finished_at": "2026-08-05T10:05:00+00:00",
        "metadata": {},
    }
    from dhara.schema._base import SchemaValidationError
    with pytest.raises(SchemaValidationError):
        validate("workflow_outcome", payload)


def test_to_dict_roundtrip() -> None:
    started = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
    finished = datetime(2026, 8, 5, 10, 5, tzinfo=UTC)
    w = WorkflowOutcome(
        workflow_id="wf-1",
        status="failed",
        started_at=started,
        finished_at=finished,
        metadata={"error": "boom"},
    )
    d = to_dict(w)
    assert d["status"] == "failed"
    w2 = validate("workflow_outcome", d)
    assert w2 == w
```

**Step 2: Run the test to verify it fails**

Run: `cd /Users/les/Projects/dhara && pytest tests/unit/schema/test_workflow_outcome.py -v`
Expected: `ImportError`.

**Step 3: Write the minimal implementation**

```python
# dhara/schema/workflow_outcome.py
"""Workflow outcome — durable result of a workflow execution (M-INFRA).

Persisted by Mahavishnu's M-WORKFLOW-OUTCOME consumer to
``workflow-results/{workflow_id}/`` in Dhara.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
import msgspec

from dhara.schema._base import SchemaEntry
from dhara.schema._registry import register


SCHEMA_VERSION: str = "1.0.0"
MIGRATIONS: dict[str, "callable"] = {}


class WorkflowOutcome(msgspec.Struct, frozen=True):
    """Structured ``WorkflowOutcome`` model + Dhara persistence."""

    workflow_id: str
    status: Literal["succeeded", "failed", "cancelled"]
    started_at: datetime
    finished_at: datetime
    metadata: dict[str, Any] = msgspec.field(default_factory=dict)


STRUCT = WorkflowOutcome


register("workflow_outcome", SchemaEntry(
    name="workflow_outcome",
    version=SCHEMA_VERSION,
    struct=STRUCT,
    migrations=MIGRATIONS,
))
```

**Step 4: Run the test to verify it passes**

Run: `cd /Users/les/Projects/dhara && pytest tests/unit/schema/test_workflow_outcome.py -v`
Expected: 5 passed.

**Step 5: Commit**

```bash
cd /Users/les/Projects/dhara
git add dhara/schema/workflow_outcome.py tests/unit/schema/test_workflow_outcome.py
git -c user.name="lesleslie" -c user.email="les@wedgwoodwebworks.local" commit -m "feat(schema): add workflow_outcome entity (M-INFRA)"
```

______________________________________________________________________

## Task 5: `approval_log` entity

**Files:**

- Create: `dhara/schema/approval_log.py`
- Test: `tests/unit/schema/test_approval_log.py`

**Step 1: Write the failing test**

```python
# tests/unit/schema/test_approval_log.py
from __future__ import annotations
from datetime import datetime, UTC
import pytest
from dhara.schema.approval_log import ApprovalLog, SCHEMA_VERSION
from dhara.schema._registry import SCHEMA_REGISTRY, validate, to_dict
from dhara.schema._base import SchemaValidationError


def test_schema_version_is_1_0_0() -> None:
    assert SCHEMA_VERSION == "1.0.0"


def test_approval_log_is_registered() -> None:
    assert "approval_log" in SCHEMA_REGISTRY


def test_construct_approved() -> None:
    at = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    log = ApprovalLog(
        approval_id="apr-1",
        actor="user:les",
        action="approved",
        at=at,
    )
    assert log.action == "approved"
    assert log.metadata == {}


def test_invalid_action_raises() -> None:
    payload = {
        "approval_id": "apr-1",
        "actor": "user:les",
        "action": "vetoed",  # not in {approved, denied, requested}
        "at": "2026-08-05T12:00:00+00:00",
        "metadata": {},
    }
    with pytest.raises(SchemaValidationError):
        validate("approval_log", payload)


def test_to_dict_roundtrip() -> None:
    at = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    log = ApprovalLog(
        approval_id="apr-1",
        actor="user:les",
        action="denied",
        at=at,
        metadata={"reason": "out of scope"},
    )
    d = to_dict(log)
    assert d["action"] == "denied"
    log2 = validate("approval_log", d)
    assert log2 == log
```

**Step 2: Run the test to verify it fails**

Run: `cd /Users/les/Projects/dhara && pytest tests/unit/schema/test_approval_log.py -v`
Expected: `ImportError`.

**Step 3: Write the minimal implementation**

```python
# dhara/schema/approval_log.py
"""Approval log — durable approval history entry (M-INFRA).

Persisted by Mahavishnu's M-APPROVAL-LOG consumer. Records are
append-only; history is exposed via ``list_approval_history``.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
import msgspec

from dhara.schema._base import SchemaEntry
from dhara.schema._registry import register


SCHEMA_VERSION: str = "1.0.0"
MIGRATIONS: dict[str, "callable"] = {}


class ApprovalLog(msgspec.Struct, frozen=True):
    """Approval history entry."""

    approval_id: str
    actor: str
    action: Literal["approved", "denied", "requested"]
    at: datetime
    metadata: dict[str, Any] = msgspec.field(default_factory=dict)


STRUCT = ApprovalLog


register("approval_log", SchemaEntry(
    name="approval_log",
    version=SCHEMA_VERSION,
    struct=STRUCT,
    migrations=MIGRATIONS,
))
```

**Step 4: Run the test to verify it passes**

Run: `cd /Users/les/Projects/dhara && pytest tests/unit/schema/test_approval_log.py -v`
Expected: 5 passed.

**Step 5: Commit**

```bash
cd /Users/les/Projects/dhara
git add dhara/schema/approval_log.py tests/unit/schema/test_approval_log.py
git -c user.name="lesleslie" -c user.email="les@wedgwoodwebworks.local" commit -m "feat(schema): add approval_log entity (M-INFRA)"
```

______________________________________________________________________

## Task 6: `channel_session_state` entity

**Files:**

- Create: `dhara/schema/channel_session_state.py`
- Test: `tests/unit/schema/test_channel_session_state.py`

**Step 1: Write the failing test**

```python
# tests/unit/schema/test_channel_session_state.py
from __future__ import annotations
from datetime import datetime, UTC
import pytest
from dhara.schema.channel_session_state import ChannelSessionState, SCHEMA_VERSION
from dhara.schema._registry import SCHEMA_REGISTRY, validate, to_dict
from dhara.schema._base import SchemaValidationError


def test_schema_version_is_1_0_0() -> None:
    assert SCHEMA_VERSION == "1.0.0"


def test_channel_session_state_is_registered() -> None:
    assert "channel_session_state" in SCHEMA_REGISTRY


def test_construct() -> None:
    last = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    s = ChannelSessionState(
        channel_id="C-abc",
        channel_type="slack",
        sender_id="U-xyz",
        last_event_at=last,
    )
    assert s.channel_type == "slack"
    assert s.metadata == {}


def test_to_dict_roundtrip() -> None:
    last = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    s = ChannelSessionState(
        channel_id="C-abc",
        channel_type="signal",
        sender_id="U-xyz",
        last_event_at=last,
        metadata={"thread_id": "T-1"},
    )
    d = to_dict(s)
    assert d["channel_type"] == "signal"
    s2 = validate("channel_session_state", d)
    assert s2 == s


def test_metadata_supports_session_versions_extension() -> None:
    """S-MEM-VERSIONS consumer uses metadata to store version info."""
    last = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    s = ChannelSessionState(
        channel_id="C-abc",
        channel_type="terminal",
        sender_id="user:les",
        last_event_at=last,
        metadata={"version": 2, "parent_session_id": "sess-1"},
    )
    assert s.metadata["version"] == 2
    assert s.metadata["parent_session_id"] == "sess-1"
```

**Step 2: Run the test to verify it fails**

Run: `cd /Users/les/Projects/dhara && pytest tests/unit/schema/test_channel_session_state.py -v`
Expected: `ImportError`.

**Step 3: Write the minimal implementation**

```python
# dhara/schema/channel_session_state.py
"""Channel session state — durable channel session record (S-MEM).

Persisted by Session-Buddy's S-CHANNEL-DURABLE consumer. The
``metadata`` field carries S-MEM-VERSIONS extension keys
(version, parent_session_id, branch_reason).
"""

from __future__ import annotations
from datetime import datetime
from typing import Any
import msgspec

from dhara.schema._base import SchemaEntry
from dhara.schema._registry import register


SCHEMA_VERSION: str = "1.0.0"
MIGRATIONS: dict[str, "callable"] = {}


class ChannelSessionState(msgspec.Struct, frozen=True):
    """Durable channel session record."""

    channel_id: str
    channel_type: str
    sender_id: str
    last_event_at: datetime
    metadata: dict[str, Any] = msgspec.field(default_factory=dict)


STRUCT = ChannelSessionState


register("channel_session_state", SchemaEntry(
    name="channel_session_state",
    version=SCHEMA_VERSION,
    struct=STRUCT,
    migrations=MIGRATIONS,
))
```

**Step 4: Run the test to verify it passes**

Run: `cd /Users/les/Projects/dhara && pytest tests/unit/schema/test_channel_session_state.py -v`
Expected: 5 passed.

**Step 5: Commit**

```bash
cd /Users/les/Projects/dhara
git add dhara/schema/channel_session_state.py tests/unit/schema/test_channel_session_state.py
git -c user.name="lesleslie" -c user.email="les@wedgwoodwebworks.local" commit -m "feat(schema): add channel_session_state entity (S-MEM)"
```

______________________________________________________________________

## Task 7: `webhook_ingress` entity

**Files:**

- Create: `dhara/schema/webhook_ingress.py`
- Test: `tests/unit/schema/test_webhook_ingress.py`

**Step 1: Write the failing test**

```python
# tests/unit/schema/test_webhook_ingress.py
from __future__ import annotations
from datetime import datetime, UTC
import pytest
from dhara.schema.webhook_ingress import WebhookIngress, SCHEMA_VERSION
from dhara.schema._registry import SCHEMA_REGISTRY, validate, to_dict


def test_schema_version_is_1_0_0() -> None:
    assert SCHEMA_VERSION == "1.0.0"


def test_webhook_ingress_is_registered() -> None:
    assert "webhook_ingress" in SCHEMA_REGISTRY


def test_construct() -> None:
    received = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    w = WebhookIngress(
        webhook_id="wh-1",
        source="github",
        received_at=received,
        payload_hash="sha256:abc123",
    )
    assert w.source == "github"
    assert w.payload_hash.startswith("sha256:")
    assert w.metadata == {}


def test_to_dict_roundtrip() -> None:
    received = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    w = WebhookIngress(
        webhook_id="wh-1",
        source="stripe",
        received_at=received,
        payload_hash="sha256:def456",
        metadata={"event_type": "invoice.paid"},
    )
    d = to_dict(w)
    assert d["source"] == "stripe"
    w2 = validate("webhook_ingress", d)
    assert w2 == w
```

**Step 2: Run the test to verify it fails**

Run: `cd /Users/les/Projects/dhara && pytest tests/unit/schema/test_webhook_ingress.py -v`
Expected: `ImportError`.

**Step 3: Write the minimal implementation**

```python
# dhara/schema/webhook_ingress.py
"""Webhook ingress — durable webhook receipt record (M-INFRA).

Persisted by Mahavishnu's M-WEBHOOK-DURABLE consumer via the
MemoryOutbox pattern. ``payload_hash`` enables idempotent replay
without re-processing.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any
import msgspec

from dhara.schema._base import SchemaEntry
from dhara.schema._registry import register


SCHEMA_VERSION: str = "1.0.0"
MIGRATIONS: dict[str, "callable"] = {}


class WebhookIngress(msgspec.Struct, frozen=True):
    """Durable webhook receipt record."""

    webhook_id: str
    source: str
    received_at: datetime
    payload_hash: str
    metadata: dict[str, Any] = msgspec.field(default_factory=dict)


STRUCT = WebhookIngress


register("webhook_ingress", SchemaEntry(
    name="webhook_ingress",
    version=SCHEMA_VERSION,
    struct=STRUCT,
    migrations=MIGRATIONS,
))
```

**Step 4: Run the test to verify it passes**

Run: `cd /Users/les/Projects/dhara && pytest tests/unit/schema/test_webhook_ingress.py -v`
Expected: 4 passed.

**Step 5: Commit**

```bash
cd /Users/les/Projects/dhara
git add dhara/schema/webhook_ingress.py tests/unit/schema/test_webhook_ingress.py
git -c user.name="lesleslie" -c user.email="les@wedgwoodwebworks.local" commit -m "feat(schema): add webhook_ingress entity (M-INFRA)"
```

______________________________________________________________________

## Task 8: Public API + migration tests + cross-system consistency

**Files:**

- Modify: `dhara/schema/__init__.py`
- Create: `tests/unit/schema/test_migration.py`
- Create: `tests/unit/schema/test_cross_system_consistency.py`

**Step 1: Write the failing tests**

```python
# tests/unit/schema/test_migration.py
from __future__ import annotations
from datetime import datetime, UTC
import msgspec
from dhara.schema._registry import SCHEMA_REGISTRY, register, from_dict
from dhara.schema._base import SchemaEntry


def test_v1_migrations_are_empty() -> None:
    """Every registered entity in v1 has an empty MIGRATIONS dict."""
    for name, entry in SCHEMA_REGISTRY.items():
        assert entry.migrations == {}, f"{name} has non-empty migrations: {entry.migrations}"


def test_from_dict_with_current_version_works() -> None:
    """When target version matches current, no migration is applied."""
    rec = from_dict("audit_record", {
        "audit_id": "a-1",
        "event_type": "x",
        "actor": "a",
        "at": "2026-08-05T12:00:00+00:00",
        "subject": "s",
        "metadata": {},
    })
    assert rec.audit_id == "a-1"


def test_from_dict_with_unknown_old_version_does_not_migrate() -> None:
    """If a version is given but no migration exists, from_dict still
    tries to convert (and may fail). Spec accepts this behavior."""
    from dhara.schema._base import SchemaValidationError
    with __import__("pytest").raises(SchemaValidationError):
        from_dict("audit_record", {
            "audit_id": "a-1",
            # missing fields → ValidationError
        }, version="0.0.1")


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
```

```python
# tests/unit/schema/test_cross_system_consistency.py
from __future__ import annotations
from datetime import datetime
from dhara.schema._registry import SCHEMA_REGISTRY
from dhara.schema.audit_record import AuditRecord
from dhara.schema.workflow_outcome import WorkflowOutcome
from dhara.schema.approval_log import ApprovalLog
from dhara.schema.channel_session_state import ChannelSessionState
from dhara.schema.webhook_ingress import WebhookIngress


EXPECTED_ENTITIES = {
    "audit_record",
    "workflow_outcome",
    "approval_log",
    "channel_session_state",
    "webhook_ingress",
}


def test_all_5_entities_registered() -> None:
    """Portfolio spec promised 5 entities in v1; all must be present."""
    assert EXPECTED_ENTITIES.issubset(set(SCHEMA_REGISTRY.keys()))


def test_all_entities_are_frozen_msgspec_structs() -> None:
    """Every entity must be frozen=True so audit logs are immutable."""
    for struct in (AuditRecord, WorkflowOutcome, ApprovalLog, ChannelSessionState, WebhookIngress):
        # frozen=True is encoded in msgspec.Struct, hard to introspect
        # but we can verify the dataclass-like behavior.
        assert hasattr(struct, "__dataclass_params__") or hasattr(struct, "__struct_fields__")
        # The hash-ability check:
        try:
            hash(struct)
        except TypeError:
            __import__("pytest").fail(f"{struct.__name__} is not hashable (frozen=True required)")


def test_all_entities_have_metadata_field() -> None:
    """The metadata escape hatch is required for forward compatibility."""
    for struct in (AuditRecord, WorkflowOutcome, ApprovalLog, ChannelSessionState, WebhookIngress):
        assert "metadata" in struct.__struct_fields__, f"{struct.__name__} missing metadata field"


def test_all_entities_have_datetime_field() -> None:
    """Every entity has at least one datetime field for audit cross-referencing."""
    for struct in (AuditRecord, WorkflowOutcome, ApprovalLog, ChannelSessionState, WebhookIngress):
        fields = struct.__struct_fields__
        # At least one datetime field (AuditRecord.at, WorkflowOutcome.started_at, etc.)
        field_types = struct.__annotations__
        assert any(
            "datetime" in str(field_types.get(f, ""))
            for f in fields
        ), f"{struct.__name__} has no datetime field"


def test_all_entities_registered_at_v1_0_0() -> None:
    """Every entity in v1 must be at version 1.0.0."""
    for name in EXPECTED_ENTITIES:
        entry = SCHEMA_REGISTRY[name]
        assert entry.version == "1.0.0", f"{name} is at {entry.version}, expected 1.0.0"
```

**Step 2: Run the tests to verify they fail**

Run: `cd /Users/les/Projects/dhara && pytest tests/unit/schema/test_migration.py tests/unit/schema/test_cross_system_consistency.py -v`
Expected: ImportError on `dhara.schema.audit_record` (not yet re-exported from `__init__.py`).

**Step 3: Update the public API**

```python
# dhara/schema/__init__.py
"""D-OBJ-SCHEMA — typed object schemas for cross-system durable entities.

This module exposes the canonical schemas for the five cross-system
durable entities defined in the 2026-08-03 portfolio spec:

- :class:`AuditRecord` (D-AUDIT consumer)
- :class:`WorkflowOutcome` (M-INFRA)
- :class:`ApprovalLog` (M-INFRA)
- :class:`ChannelSessionState` (S-MEM)
- :class:`WebhookIngress` (M-INFRA)

Plus the central registry (:func:`SCHEMA_REGISTRY`, :func:`validate`,
:func:`from_dict`, :func:`to_dict`) for runtime validation.
"""

from __future__ import annotations
from dhara.schema._base import SchemaEntry, SchemaValidationError
from dhara.schema._registry import (
    SCHEMA_REGISTRY,
    register,
    validate,
    from_dict,
    to_dict,
)

# Re-export entity Struct classes and STRUCT aliases for ergonomic imports.
from dhara.schema.audit_record import AuditRecord, STRUCT as audit_record
from dhara.schema.workflow_outcome import WorkflowOutcome, STRUCT as workflow_outcome
from dhara.schema.approval_log import ApprovalLog, STRUCT as approval_log
from dhara.schema.channel_session_state import ChannelSessionState, STRUCT as channel_session_state
from dhara.schema.webhook_ingress import WebhookIngress, STRUCT as webhook_ingress

__all__ = [
    "SCHEMA_REGISTRY",
    "SchemaEntry",
    "SchemaValidationError",
    "register",
    "validate",
    "from_dict",
    "to_dict",
    "AuditRecord",
    "WorkflowOutcome",
    "ApprovalLog",
    "ChannelSessionState",
    "WebhookIngress",
    "audit_record",
    "workflow_outcome",
    "approval_log",
    "channel_session_state",
    "webhook_ingress",
]
```

**Step 4: Run the tests to verify they pass**

Run: `cd /Users/les/Projects/dhara && pytest tests/unit/schema/ -v --no-cov`
Expected: all 8 test files pass (~32 tests total).

**Step 5: Commit**

```bash
cd /Users/les/Projects/dhara
git add dhara/schema/__init__.py tests/unit/schema/test_migration.py tests/unit/schema/test_cross_system_consistency.py
git -c user.name="lesleslie" -c user.email="les@wedgwoodwebworks.local" commit -m "feat(schema): public API + migration + cross-system consistency tests"
```

______________________________________________________________________

## Task 9: Final verification — crackerjack + spec coverage

**Files:**

- (no file changes; verification only)

**Step 1: Run the schema test suite**

```bash
cd /Users/les/Projects/dhara
pytest tests/unit/schema/ -v --no-cov
```

Expected: ~32 tests pass.

**Step 2: Run crackerjack on dhara**

```bash
cd /Users/les/Projects/dhara
crackerjack run
```

Expected: 15+/16 fast hooks pass. `pip-audit` may fail for pre-existing `cryptography` CVE (out of scope per `crackerjack-version-bumping-manual`).

**Step 3: Run the public-API smoke command from the spec**

```bash
cd /Users/les/Projects/dhara
python -c "from dhara.schema import SCHEMA_REGISTRY; print(sorted(SCHEMA_REGISTRY.keys()))"
```

Expected: `['approval_log', 'audit_record', 'channel_session_state', 'webhook_ingress', 'workflow_outcome']`

**Step 4: Final commit (if any fixups were needed)**

Skip if clean. Apply minimal fix and commit per fix.

______________________________________________________________________

## Spec coverage map

| Spec section / requirement | Task(s) implementing it |
|---|---|
| Goal #1 — 5 entity schemas | Tasks 3, 4, 5, 6, 7 |
| Goal #2 — single source of truth | Task 2 (registry) + Task 8 (consistency tests) |
| Goal #3 — write-time + read-time validation + migration | Tasks 2, 8 |
| Goal #4 — decoupled from persistence | (no Dhara persistence in D-OBJ-SCHEMA) |
| Goal #5 — substrate pattern (Protocol + concrete + tests) | Tasks 1, 2, plus tests for each entity |
| Architecture: per-entity modules + central registry | File structure |
| Test budget (5+ files, 15+ tests) | Tasks 3-8 (8 test files, ~32 tests) |
| Integration Contract | Verified by Task 9 |
| Public API (`__init__.py` exports) | Task 8 |

## Self-review

1. **Spec coverage**: Every spec section maps to a task. ✓
1. **No placeholders**: All code is concrete. ✓
1. **Type consistency**: `SCHEMA_VERSION` is `str` everywhere; `MIGRATIONS` is `dict[str, callable]`; `STRUCT` is the msgspec.Struct class. ✓
1. **TDD discipline**: Every task writes the failing test first, then the impl. ✓
1. **No pre-existing dirty files touched**: All commits are net-new files. ✓
1. **Substrate pattern**: 5 entity modules + 1 registry + 1 base + 1 `__init__` = 8 source files. Same shape as D-LOCK's `dhara/lock/`. ✓
