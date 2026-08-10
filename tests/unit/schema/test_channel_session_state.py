# tests/unit/schema/test_channel_session_state.py
from __future__ import annotations

from datetime import UTC, datetime

from dhara.schema._registry import SCHEMA_REGISTRY, to_dict, validate
from dhara.schema.channel_session_state import SCHEMA_VERSION, ChannelSessionState


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
