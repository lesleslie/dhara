"""Capability descriptor — Phase 1 substrate for ``akosha://capabilities/{repo}/{kind}/{name}.json``.

Persisted by Akosha's ``cross_repo_capability_search`` tool. Each
descriptor is a single capability (tool / adapter / error convention)
in a Bodai component, indexed for semantic + token-overlap search.

D-CAP-DESC (Phase 1)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

import msgspec

from dhara.schema._base import SchemaEntry
from dhara.schema._registry import register

SCHEMA_VERSION: str = "1.0.0"
MIGRATIONS: dict[str, Callable[..., Any]] = {}


CapabilityKind = Literal["tool", "adapter", "error"]


class CapabilityDescriptor(msgspec.Struct, frozen=True):
    """One indexed capability inside a Bodai component.

    Persisted at ``akosha://capabilities/{repo}/{kind}/{name}.json`` by
    Akosha's Phase 1 ``cross_repo_capability_search`` registration.
    """

    repo: str
    kind: CapabilityKind
    name: str
    summary: str
    doc_hint: str
    tags: list[str] = msgspec.field(default_factory=list)
    indexed_at: str | None = None
    metadata: dict[str, Any] = msgspec.field(default_factory=dict)


STRUCT = CapabilityDescriptor


register(
    "capability_descriptor",
    SchemaEntry(
        name="capability_descriptor",
        version=SCHEMA_VERSION,
        struct=STRUCT,
        migrations=MIGRATIONS,
    ),
)
