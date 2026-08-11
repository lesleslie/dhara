"""Webhook ingress — durable webhook receipt record (M-INFRA).

Persisted by Mahavishnu's M-WEBHOOK-DURABLE consumer via the
MemoryOutbox pattern. ``payload_hash`` enables idempotent replay
without re-processing.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

import msgspec

from dhara.schema._base import SchemaEntry
from dhara.schema._registry import register

SCHEMA_VERSION: str = "1.0.0"
MIGRATIONS: dict[str, Callable[..., Any]] = {}


class WebhookIngress(msgspec.Struct, frozen=True):
    """Durable webhook receipt record."""

    webhook_id: str
    source: str
    received_at: datetime
    payload_hash: str
    metadata: dict[str, Any] = msgspec.field(default_factory=dict)


STRUCT = WebhookIngress


register(
    "webhook_ingress",
    SchemaEntry(
        name="webhook_ingress",
        version=SCHEMA_VERSION,
        struct=STRUCT,
        migrations=MIGRATIONS,
    ),
)
