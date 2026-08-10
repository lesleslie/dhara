# tests/unit/schema/test_webhook_ingress.py
from __future__ import annotations

from datetime import UTC, datetime

from dhara.schema._registry import SCHEMA_REGISTRY, to_dict, validate
from dhara.schema.webhook_ingress import SCHEMA_VERSION, WebhookIngress


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
