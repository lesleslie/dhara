"""Channel session state — durable channel session record (S-MEM).

Persisted by Session-Buddy's S-CHANNEL-DURABLE consumer. The
``metadata`` field carries S-MEM-VERSIONS extension keys
(version, parent_session_id, branch_reason).
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


class ChannelSessionState(msgspec.Struct, frozen=True):
    """Durable channel session record."""

    channel_id: str
    channel_type: str
    sender_id: str
    last_event_at: datetime
    metadata: dict[str, Any] = msgspec.field(default_factory=dict)


STRUCT = ChannelSessionState


register(
    "channel_session_state",
    SchemaEntry(
        name="channel_session_state",
        version=SCHEMA_VERSION,
        struct=STRUCT,
        migrations=MIGRATIONS,
    ),
)
