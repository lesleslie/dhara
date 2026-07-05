from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from contextlib import suppress
from typing import Any, Protocol

from dhara.events.events import DomainEvent

logger = logging.getLogger(__name__)


class Subscriber(Protocol):
    """Protocol every event subscriber must satisfy.

    ``handle`` is async so subscribers can perform I/O without blocking the
    bus. Errors raised by ``handle`` are logged and swallowed by the bus —
    a failing subscriber must never block delivery to other subscribers.
    """

    async def handle(self, event: DomainEvent) -> None: ...


class EventBus:
    """In-process async event bus with typed fan-out.

    Routing key is the concrete event class (e.g. ``SettingsVersionActivated``),
    not the ``event_type`` discriminator, so subscribers opt in to a specific
    subclass. Subscribers run concurrently via ``asyncio.gather`` and per-
    subscriber exceptions are isolated — one bad subscriber does not affect
    delivery to the others.
    """

    def __init__(self) -> None:
        self._subscribers: dict[type[DomainEvent], list[Subscriber]] = defaultdict(list)

    def subscribe(
        self,
        event_type: type[DomainEvent],
        subscriber: Subscriber,
    ) -> None:
        """Register ``subscriber`` to receive every published ``event_type``."""
        if not isinstance(event_type, type) or not issubclass(event_type, DomainEvent):
            raise TypeError(
                f"event_type must be a DomainEvent subclass, got {event_type!r}"
            )
        self._subscribers[event_type].append(subscriber)

    def unsubscribe(
        self,
        event_type: type[DomainEvent],
        subscriber: Subscriber,
    ) -> None:
        """Remove ``subscriber`` from the routing list for ``event_type``."""
        bucket = self._subscribers.get(event_type, [])
        with suppress(ValueError):
            # Idempotent: silent if the subscriber wasn't registered.
            bucket.remove(subscriber)

    async def publish(self, event: DomainEvent) -> None:
        """Fan out ``event`` to every subscriber registered for its type.

        Returns when every subscriber has completed (or failed). Subscriber
        failures are caught, logged, and isolated — they never propagate out
        of ``publish`` and never abort sibling deliveries.
        """
        event_cls = type(event)
        subs = list(self._subscribers.get(event_cls, ()))
        if not subs:
            return

        async def _deliver(sub: Subscriber) -> None:
            try:
                await sub.handle(event)
            except Exception:
                # Log full traceback but never let one subscriber break the rest.
                logger.exception(
                    "subscriber %r failed handling event %s",
                    sub,
                    getattr(event, "event_type", event_cls.__name__),
                )

        # asyncio.gather returns when all tasks complete; we already isolated
        # errors inside _deliver, so no exception propagation from the gather.
        await asyncio.gather(*(_deliver(s) for s in subs))

    def subscriber_count(self, event_type: type[DomainEvent]) -> int:
        """Return the number of subscribers registered for ``event_type``."""
        return len(self._subscribers.get(event_type, ()))

    def clear(self) -> None:
        """Remove every subscriber. Useful for tests."""
        self._subscribers.clear()


__all__ = ["EventBus", "Subscriber"]


# Marker for static checkers — Subscriber is a Protocol; keep import local.
_ = Any
