"""In-memory bounded queue for audit_record emission.

The MemoryOutbox sits between the AuditLogSubscriber (sync enqueue
on every dhara.put) and the background flush task (async drain
to the audit_log table). Sized to absorb short bursts; drops
oldest on overflow per the G6 contract.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dhara.schema.audit_record import AuditRecord


class MemoryOutbox:
    """Thread-safe bounded FIFO queue for audit_record emission."""

    def __init__(self, max_size: int = 1000) -> None:
        self._queue: deque[AuditRecord] = deque(maxlen=max_size)
        self._lock = threading.Lock()

    def enqueue(self, record: AuditRecord) -> bool:
        """Returns True if enqueued, False if dropped (overflow)."""
        with self._lock:
            was_full = len(self._queue) == self._queue.maxlen
            self._queue.append(record)
            return not was_full

    def drain(self) -> list[AuditRecord]:
        """Atomically remove and return all queued records."""
        with self._lock:
            records = list(self._queue)
            self._queue.clear()
            return records

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._queue)

    def peek(self) -> AuditRecord | None:
        with self._lock:
            return self._queue[0] if self._queue else None
