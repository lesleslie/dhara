"""AuditLogSubscriber — emits audit_record on every durable write.

Subscribes to dhara.put events. Validates the audit payload via
SCHEMA_REGISTRY. On success, enqueues the typed AuditRecord into the
MemoryOutbox for asynchronous flush. On validation failure, emits
a fallback log entry but does NOT raise — the G6 contract forbids
substrate failures from breaking the producer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from oneiric.core.logging import get_logger

from dhara.schema._registry import validate

if TYPE_CHECKING:
    from dhara.audit.outbox import MemoryOutbox
    from dhara.schema.audit_record import AuditRecord

_logger = get_logger("dhara.audit")


@dataclass(frozen=True)
class WriteEvent:
    """Snapshot of a dhara.put invocation."""

    entity_type: str
    entity_id: str
    payload: dict[str, object]


class AuditLogSubscriber:
    """Hooks dhara.put and emits structured audit_record."""

    _instance: AuditLogSubscriber | None = None

    def __init__(self, outbox: MemoryOutbox) -> None:
        self._outbox = outbox
        self._registered = False

    @classmethod
    def get_instance(cls) -> AuditLogSubscriber | None:
        """Returns the globally-registered subscriber, or None."""
        return cls._instance

    def register(self) -> None:
        """Register as the active subscriber. Idempotent."""
        if not self._registered:
            AuditLogSubscriber._instance = self
            self._registered = True

    def unregister(self) -> None:
        """Unregister. Safe to call when not registered."""
        if AuditLogSubscriber._instance is self:
            AuditLogSubscriber._instance = None
            self._registered = False

    def on_put(self, event: WriteEvent) -> None:
        """Validate and enqueue audit_record for the given write event.

        G6 contract: NEVER raises. On validation failure, logs and returns.
        The entity_type/entity_id of the underlying write are carried
        alongside the validated ``AuditRecord`` through the MemoryOutbox
        so the flusher can populate the audit_log table's entity columns
        (per migration 0004 schema). The audit_record payload itself
        carries only the validated event fields.
        """
        try:
            record: AuditRecord = validate("audit_record", event.payload)
            self._outbox.enqueue(event.entity_type, event.entity_id, record)
        except Exception as exc:  # noqa: BLE001 — G6 contract: never raise
            _logger.warning(
                "audit_record_validation_failed",
                error=str(exc),
                entity_type=event.entity_type,
                entity_id=event.entity_id,
            )
