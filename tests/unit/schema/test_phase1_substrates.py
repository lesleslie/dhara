"""Tests for Phase 1 substrate schemas.

Covers:
    * :class:`CapabilityDescriptor` — akosha://capabilities/{repo}/{kind}/{name}.json
    * :class:`EcosystemRunRecord`   — session-buddy://runs/{workflow_id}.json
"""

from __future__ import annotations

import pytest

from dhara.schema._base import SchemaValidationError
from dhara.schema._registry import SCHEMA_REGISTRY, to_dict, validate


# ---------------------------------------------------------------------------
# CapabilityDescriptor
# ---------------------------------------------------------------------------


class TestCapabilityDescriptor:
    def test_schema_is_registered(self) -> None:
        assert "capability_descriptor" in SCHEMA_REGISTRY
        assert "ecosystem_run_record" in SCHEMA_REGISTRY

    def test_import_shape(self) -> None:
        from dhara.schema import CapabilityDescriptor, EcosystemRunRecord

        assert CapabilityDescriptor.__name__ == "CapabilityDescriptor"
        assert EcosystemRunRecord.__name__ == "EcosystemRunRecord"

    def test_minimal_payload(self) -> None:
        payload = {
            "repo": "mahavishnu",
            "kind": "tool",
            "name": "pool_route_execute",
            "summary": "Route a prompt to the best pool.",
            "doc_hint": "mahavishnu.mcp.tools.pool_tools",
            "tags": ["pool", "routing"],
        }
        cap = validate("capability_descriptor", payload)
        assert cap.repo == "mahavishnu"
        assert cap.kind == "tool"
        assert cap.name == "pool_route_execute"
        assert cap.tags == ["pool", "routing"]
        assert cap.metadata == {}
        assert cap.indexed_at is None

    def test_invalid_kind_rejected(self) -> None:
        payload = {
            "repo": "mahavishnu",
            "kind": "not-a-kind",
            "name": "x",
            "summary": "y",
            "doc_hint": "z",
            "tags": [],
        }
        with pytest.raises(SchemaValidationError):
            validate("capability_descriptor", payload)

    def test_required_fields_missing(self) -> None:
        # Missing `summary`
        payload = {
            "repo": "mahavishnu",
            "kind": "tool",
            "name": "x",
            "doc_hint": "z",
            "tags": [],
        }
        with pytest.raises(SchemaValidationError):
            validate("capability_descriptor", payload)

    def test_to_dict_roundtrip(self) -> None:
        payload = {
            "repo": "akosha",
            "kind": "adapter",
            "name": "EmbeddingService",
            "summary": "Local all-MiniLM-L6-v2.",
            "doc_hint": "akosha.processing.embeddings",
            "tags": ["embedding", "ml"],
            "indexed_at": "2026-08-29T10:00:00+00:00",
            "metadata": {"model": "all-MiniLM-L6-v2"},
        }
        cap = validate("capability_descriptor", payload)
        d = to_dict(cap)
        assert d["repo"] == "akosha"
        assert d["kind"] == "adapter"
        cap2 = validate("capability_descriptor", d)
        assert cap2 == cap

    def test_all_three_kinds_accepted(self) -> None:
        for kind in ("tool", "adapter", "error"):
            payload = {
                "repo": "x",
                "kind": kind,
                "name": "n",
                "summary": "s",
                "doc_hint": "d",
                "tags": [],
            }
            cap = validate("capability_descriptor", payload)
            assert cap.kind == kind


# ---------------------------------------------------------------------------
# EcosystemRunRecord
# ---------------------------------------------------------------------------


class TestEcosystemRunRecord:
    def test_minimal_payload(self) -> None:
        payload = {
            "workflow_id": "10633f68-279a-4bcc-8c7b-634d870f71c8",
            "components": [],
            "summary": {"component_count": 0, "repos_seen": []},
            "mode": "phase1_stub",
        }
        rec = validate("ecosystem_run_record", payload)
        assert rec.workflow_id == "10633f68-279a-4bcc-8c7b-634d870f71c8"
        assert rec.components == []
        assert rec.summary == {"component_count": 0, "repos_seen": []}
        assert rec.mode == "phase1_stub"

    def test_full_payload(self) -> None:
        payload = {
            "workflow_id": "wf-abc",
            "components": [
                {
                    "repo": "mahavishnu",
                    "workflow_id": "wf-abc",
                    "status": "succeeded",
                    "started_at": "2026-08-29T00:00:00+00:00",
                    "finished_at": "2026-08-29T00:01:00+00:00",
                    "duration_ms": 60000,
                    "source": "live_fetcher",
                    "error": None,
                    "steps": [
                        {"name": "preflight", "ok": True},
                        {"name": "execute", "ok": True},
                    ],
                    "metadata": {"pool": "local-1"},
                },
                {
                    "repo": "akosha",
                    "workflow_id": "wf-abc",
                    "status": "running",
                    "source": "phase1_stub",
                },
                {
                    "repo": "session-buddy",
                    "workflow_id": "wf-abc",
                    "status": "succeeded",
                    "source": "phase1_stub",
                },
            ],
            "summary": {
                "workflow_id": "wf-abc",
                "component_count": 3,
                "repos_seen": ["akosha", "mahavishnu", "session-buddy"],
                "status_by_repo": {
                    "mahavishnu": "succeeded",
                    "akosha": "running",
                    "session-buddy": "succeeded",
                },
                "spans_3_components": True,
            },
            "mode": "phase1_stub",
        }
        rec = validate("ecosystem_run_record", payload)
        assert len(rec.components) == 3
        assert rec.components[0].repo == "mahavishnu"
        assert rec.components[0].duration_ms == 60000
        assert rec.components[1].status == "running"
        assert rec.summary["spans_3_components"] is True

    def test_invalid_status_rejected(self) -> None:
        payload = {
            "workflow_id": "wf-1",
            "components": [
                {
                    "repo": "x",
                    "workflow_id": "wf-1",
                    "status": "weird-status",
                    "source": "x",
                }
            ],
            "summary": {},
            "mode": "x",
        }
        with pytest.raises(SchemaValidationError):
            validate("ecosystem_run_record", payload)

    def test_required_workflow_id_missing(self) -> None:
        payload = {
            "components": [],
            "summary": {},
            "mode": "phase1_stub",
        }
        with pytest.raises(SchemaValidationError):
            validate("ecosystem_run_record", payload)

    def test_to_dict_roundtrip(self) -> None:
        payload = {
            "workflow_id": "wf-rt",
            "components": [
                {
                    "repo": "akosha",
                    "workflow_id": "wf-rt",
                    "status": "succeeded",
                    "source": "phase1_stub",
                }
            ],
            "summary": {"component_count": 1, "repos_seen": ["akosha"]},
            "mode": "phase1_stub",
        }
        rec = validate("ecosystem_run_record", payload)
        d = to_dict(rec)
        rec2 = validate("ecosystem_run_record", d)
        assert rec2 == rec
