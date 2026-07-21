"""Registry-mediated cache-adapter lookup for the Dhara MCP server.

Asks Dhara's AsyncAdapterRegistry for the canonical Oneiric cache-adapter
class (stored as a `factory_path` string in the dict returned by
`registry.get_adapter_async(domain, key, provider)`), imports it via
the factory path, instantiates with caller-supplied settings, awaits
`init()`, and returns the live adapter. Raises `LifecycleError` for any
configuration error (unknown backend, missing factory, failed import).
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any, Literal

from oneiric.adapters.cache import (
    MemoryCacheAdapter,
    MemoryCacheSettings,
    RedisCacheAdapter,
    RedisCacheSettings,
)
from oneiric.core.lifecycle import LifecycleError

Backend = Literal["memory", "redis"]

CacheAdapter = RedisCacheAdapter | MemoryCacheAdapter

ImportFn = Callable[[str], Any]

ALLOWED_BACKENDS: tuple[str, ...] = ("memory", "redis")


def _default_import(name: str) -> Any:
    """Import `module:Class` from `name`. Whitespace-tolerant on either side of the colon."""
    module_name, _, attr = name.partition(":")
    if not module_name or not attr:
        raise LifecycleError(f"malformed factory path: {name!r}")
    module = importlib.import_module(module_name.strip())
    return getattr(module, attr.strip())


async def resolve_cache_adapter(
    backend: Backend,
    settings: RedisCacheSettings | MemoryCacheSettings | None,
    registry: Any,
    import_fn: ImportFn = _default_import,
) -> CacheAdapter:
    if backend not in ALLOWED_BACKENDS:
        raise LifecycleError(
            f"unknown cache backend: {backend!r}; expected one of {ALLOWED_BACKENDS}"
        )
    entry = await registry.get_adapter_async("adapter", "cache", backend)
    if entry is None:
        raise LifecycleError(f"cache adapter not registered for backend={backend!r}")
    factory_path = (
        entry["factory_path"]
        if isinstance(entry, dict)
        else getattr(entry, "factory_path", None)
    )
    if not factory_path:
        raise LifecycleError(
            f"registry entry for backend={backend!r} has no factory_path"
        )
    try:
        adapter_cls = import_fn(factory_path)
    except (ImportError, AttributeError) as exc:
        raise LifecycleError(
            f"failed to import cache adapter factory {factory_path!r}"
        ) from exc
    instance = adapter_cls(settings)
    await instance.init()
    return instance
