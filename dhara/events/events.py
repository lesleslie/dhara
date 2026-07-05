from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def _utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(UTC)


class DomainEvent(BaseModel):
    """Base class for all Dhara substrate domain events.

    Every event carries a stable ``event_id``, the moment it ``occurred_at``,
    an ``event_type`` discriminator, and an optional ``tenant_id`` for
    multi-tenant routing. Concrete event subclasses set ``event_type`` as a
    class literal so the in-process bus can route by type without a registry.
    """

    event_id: str = Field(default_factory=lambda: uuid4().hex)
    occurred_at: datetime = Field(default_factory=_utc_now)
    tenant_id: str | None = None

    event_type: str  # set by subclass literals

    model_config = {"frozen": True}


class SettingsVersionActivated(DomainEvent):
    """A new adapter settings version was activated for a tenant."""

    event_type: Literal["SettingsVersionActivated"] = "SettingsVersionActivated"
    version_id: str
    activated_by: str

    @field_validator("activated_by")
    @classmethod
    def _non_empty_actor(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("activated_by must be a non-empty actor identifier")
        return value


class ContextVersionPublished(DomainEvent):
    """A new tenant context version was published."""

    event_type: Literal["ContextVersionPublished"] = "ContextVersionPublished"
    version_id: str
    published_by: str
    context: dict[str, Any] = Field(default_factory=dict)


class ProgressSnapshotRecorded(DomainEvent):
    """A workflow progress snapshot was recorded."""

    event_type: Literal["ProgressSnapshotRecorded"] = "ProgressSnapshotRecorded"
    workflow_id: str
    step: str
    progress_percent: float

    @field_validator("progress_percent")
    @classmethod
    def _in_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"progress_percent must be in [0.0, 1.0], got {value!r}")
        return value


__all__ = [
    "ContextVersionPublished",
    "DomainEvent",
    "ProgressSnapshotRecorded",
    "SettingsVersionActivated",
]
