"""Tests for dhara.mcp.adapter_lookup.resolve_cache_adapter.

Mocks AsyncAdapterRegistry with the real-shaped dict return contract:
`{"factory_path": "module:Class", ...}` per
dhara/mcp/adapter_tools.py:894-924.
"""
from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock

import pytest

from oneiric.adapters.cache import MemoryCacheAdapter, RedisCacheAdapter
from oneiric.core.lifecycle import LifecycleError


def _import(name: str) -> Any:
    module_name, _, attr = name.partition(":")
    return getattr(importlib.import_module(module_name), attr)


def _registry_with(payload: dict[tuple[str, str, str], str | None]) -> MagicMock:
    """Build a registry mock whose get_adapter_async returns AdapterEntry-shaped dicts."""
    reg = MagicMock()

    async def get_adapter(domain: str, key: str, provider: str) -> dict[str, Any] | None:
        factory_path = payload.get((domain, key, provider))
        if factory_path is None:
            return None
        return {"factory_path": factory_path}

    reg.get_adapter_async = get_adapter
    return reg


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolves_memory_backend() -> None:
    from dhara.mcp.adapter_lookup import resolve_cache_adapter

    reg = _registry_with(
        {("adapter", "cache", "memory"): "oneiric.adapters.cache.memory:MemoryCacheAdapter"}
    )
    adapter = await resolve_cache_adapter("memory", None, reg, _import)
    assert isinstance(adapter, MemoryCacheAdapter)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolves_redis_backend() -> None:
    from dhara.mcp.adapter_lookup import resolve_cache_adapter
    from oneiric.adapters.cache import RedisCacheSettings

    settings = RedisCacheSettings(url="redis://example:6379/0")
    reg = _registry_with(
        {("adapter", "cache", "redis"): "oneiric.adapters.cache.redis:RedisCacheAdapter"}
    )
    adapter = await resolve_cache_adapter("redis", settings, reg, _import)
    assert isinstance(adapter, RedisCacheAdapter)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unknown_backend_raises_lifecycle_error() -> None:
    from dhara.mcp.adapter_lookup import resolve_cache_adapter

    reg = _registry_with({})
    with pytest.raises(LifecycleError):
        await resolve_cache_adapter("redis", None, reg, _import)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalid_backend_string_raises_lifecycle_error() -> None:
    from dhara.mcp.adapter_lookup import resolve_cache_adapter

    reg = _registry_with({})
    with pytest.raises(LifecycleError):
        await resolve_cache_adapter("redisS", None, reg, _import)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_init_is_awaited_on_resolved_adapter() -> None:
    from dhara.mcp.adapter_lookup import resolve_cache_adapter
    from unittest.mock import AsyncMock

    init = AsyncMock()
    sentinel = MagicMock(spec=MemoryCacheAdapter)
    sentinel.init = init

    reg = MagicMock()

    async def get_adapter(domain: str, key: str, provider: str) -> dict[str, Any] | None:
        return {"factory_path": "oneiric.adapters.cache.memory:MemoryCacheAdapter"}

    reg.get_adapter_async = get_adapter

    def fake_import(name: str) -> Any:
        if name == "oneiric.adapters.cache.memory:MemoryCacheAdapter":
            return lambda settings: sentinel
        return _import(name)

    adapter = await resolve_cache_adapter("memory", None, reg, fake_import)
    init.assert_awaited_once()
    assert adapter is sentinel


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dict_factory_path_field_is_read_not_attr() -> None:
    """Guard against reverting to `getattr(entry, "factory")` — that always returns None on a dict."""
    from dhara.mcp.adapter_lookup import resolve_cache_adapter

    class WrongShape:
        factory = "oneiric.adapters.cache.memory:MemoryCacheAdapter"

    reg = MagicMock()

    async def get_adapter(domain: str, key: str, provider: str) -> Any:
        return WrongShape()

    reg.get_adapter_async = get_adapter

    with pytest.raises(LifecycleError):
        await resolve_cache_adapter("memory", None, reg, _import)
