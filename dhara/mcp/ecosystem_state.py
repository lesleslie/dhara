from __future__ import annotations

"""Durable ecosystem state primitives for Dhara MCP tools.

This module provides lightweight persistent structures for:
- service registration and capability metadata
- health snapshots and lease-like heartbeat timestamps
- append-only event logging with retention

The goal is to give Mahavishnu and sibling services a stable durable substrate
without requiring each caller to reinvent its own key layout over raw KV calls.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from dhara.collections.dict import PersistentDict
from dhara.collections.list import PersistentList
from dhara.core.connection import Connection


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class EventRetention:
    retention_days: int = 30

    def cutoff(self) -> datetime:
        return _utcnow() - timedelta(days=self.retention_days)


class EcosystemStateStore:
    """Persistent store for ecosystem service metadata and event history."""

    REGISTRY_SCHEMA_VERSION = 1
    EVENT_SCHEMA_VERSION = 1

    def __init__(
        self,
        connection: Connection,
        event_retention: EventRetention | None = None,
    ) -> None:
        self.connection = connection
        self.event_retention = event_retention or EventRetention()
        self._ensure_root()

    def _ensure_root(self) -> None:
        root = self.connection.get_root()
        changed = False

        if "ecosystem_services" not in root:
            root["ecosystem_services"] = PersistentDict()  # type: ignore[assignment]
            changed = True
        if "ecosystem_events" not in root:
            root["ecosystem_events"] = PersistentList()  # type: ignore[assignment]
            changed = True

        if changed:
            self.connection.commit()

    def _services(self) -> PersistentDict:
        root = self.connection.get_root()
        return root["ecosystem_services"]  # type: ignore[return-value]

    def _events(self) -> PersistentList:
        root = self.connection.get_root()
        return root["ecosystem_events"]  # type: ignore[return-value]

    def _normalize_service_record(self, service: dict[str, Any]) -> dict[str, Any]:
        payload = dict(service)
        payload.setdefault("schema_version", self.REGISTRY_SCHEMA_VERSION)
        payload.setdefault("capabilities", [])
        payload.setdefault("metadata", {})
        payload.setdefault("status", "unknown")
        return payload

    def _normalize_event_record(self, event: dict[str, Any]) -> dict[str, Any]:
        payload = dict(event)
        payload.setdefault("schema_version", self.EVENT_SCHEMA_VERSION)
        payload.setdefault("payload", {})
        return payload

    def upsert_service(
        self,
        service_id: str,
        service_type: str,
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        status: str = "unknown",
        lease_expires_at: str | None = None,
        heartbeat_at: str | None = None,
    ) -> dict[str, Any]:
        services = self._services()
        now = _utcnow().isoformat()

        existing = dict(services.get(service_id, {}))
        created_at = existing.get("created_at", now)

        record = {
            "schema_version": self.REGISTRY_SCHEMA_VERSION,
            "service_id": service_id,
            "service_type": service_type,
            "capabilities": list(capabilities or []),
            "metadata": dict(metadata or {}),
            "status": status,
            "lease_expires_at": lease_expires_at,
            "heartbeat_at": heartbeat_at or now,
            "created_at": created_at,
            "updated_at": now,
        }

        services[service_id] = PersistentDict(record)  # type: ignore[assignment]
        self.connection.commit()
        return record

    def get_service(self, service_id: str) -> dict[str, Any] | None:
        services = self._services()
        if service_id not in services:
            return None
        return self._normalize_service_record(dict(services[service_id]))

    def list_services(
        self,
        service_type: str | None = None,
        capability: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        services = self._services()
        results: list[dict[str, Any]] = []

        for service in services.values():
            payload = self._normalize_service_record(dict(service))
            if service_type and payload.get("service_type") != service_type:
                continue
            if status and payload.get("status") != status:
                continue
            if capability and capability not in payload.get("capabilities", []):
                continue
            results.append(payload)

        results.sort(key=lambda item: item.get("service_id", ""))
        return results

    def record_event(
        self,
        event_type: str,
        source_service: str,
        payload: dict[str, Any] | None = None,
        related_service: str | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        events = self._events()
        event = {
            "schema_version": self.EVENT_SCHEMA_VERSION,
            "event_type": event_type,
            "source_service": source_service,
            "related_service": related_service,
            "payload": dict(payload or {}),
            "timestamp": timestamp or _utcnow().isoformat(),
        }
        events.append(PersistentDict(event))  # type: ignore[arg-type]
        self._prune_events(events)
        self.connection.commit()
        return event

    def list_events(
        self,
        event_type: str | None = None,
        source_service: str | None = None,
        related_service: str | None = None,
        limit: int | None = 100,
    ) -> list[dict[str, Any]]:
        events = self._events()
        cutoff = self.event_retention.cutoff()
        results: list[dict[str, Any]] = []

        for item in events:
            event = self._normalize_event_record(dict(item))
            ts = event.get("timestamp")
            try:
                event_dt = (
                    datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if isinstance(ts, str)
                    else None
                )
            except ValueError:
                event_dt = None
            if event_dt is not None and event_dt.tzinfo is None:
                event_dt = event_dt.replace(tzinfo=timezone.utc)
            if event_dt is not None and event_dt < cutoff:
                continue
            if event_type and event.get("event_type") != event_type:
                continue
            if source_service and event.get("source_service") != source_service:
                continue
            if related_service and event.get("related_service") != related_service:
                continue
            results.append(event)

        if limit is not None:
            results = results[-int(limit) :]
        return results

    def _prune_events(self, events: PersistentList) -> None:
        cutoff = self.event_retention.cutoff()
        kept = []
        for item in events:
            event = self._normalize_event_record(dict(item))
            ts = event.get("timestamp")
            try:
                event_dt = (
                    datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if isinstance(ts, str)
                    else None
                )
            except ValueError:
                event_dt = None
            if event_dt is not None and event_dt.tzinfo is None:
                event_dt = event_dt.replace(tzinfo=timezone.utc)
            if event_dt is None or event_dt >= cutoff:
                kept.append(item)
        if len(kept) != len(events):
            events[:] = kept
