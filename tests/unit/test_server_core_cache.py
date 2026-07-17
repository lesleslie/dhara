"""End-to-end tests for cache-adapter wiring through dhara.mcp.server_core."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from oneiric.adapters.cache import (
    MemoryCacheAdapter,
    MemoryCacheSettings,
    RedisCacheAdapter,
)


def _make_config(cache_backend: str = "memory") -> Any:
    cfg = MagicMock()
    cfg.cache_backend = cache_backend
    return cfg


def _make_core() -> Any:
    core = MagicMock()
    core._async_adapter_registry = MagicMock()
    core._logger = MagicMock()
    return core


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_backend_wires_memory_cache_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    from dhara.mcp import server_core

    captured: dict[str, Any] = {}

    async def fake_resolve(backend: str, settings: Any, registry: Any) -> Any:
        captured["backend"] = backend
        captured["settings"] = settings
        sentinel = MagicMock(spec=MemoryCacheAdapter)
        return sentinel

    monkeypatch.setattr(server_core, "resolve_cache_adapter", fake_resolve, raising=False)
    cfg = _make_config("memory")
    core = _make_core()
    result = await server_core._wire_cache(cfg, core)
    assert captured["backend"] == "memory"
    assert isinstance(captured["settings"], MemoryCacheSettings)
    assert isinstance(result, MemoryCacheAdapter)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_redis_backend_wires_redis_cache_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    from dhara.mcp import server_core

    sentinel = MagicMock(spec=RedisCacheAdapter)

    async def fake_resolve(backend: str, settings: Any, registry: Any) -> Any:
        return sentinel

    monkeypatch.setattr(server_core, "resolve_cache_adapter", fake_resolve, raising=False)
    cfg = _make_config("redis")
    core = _make_core()
    result = await server_core._wire_cache(cfg, core)
    assert isinstance(result, RedisCacheAdapter)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cache_adapter_resolved_log_fires_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    from dhara.mcp import server_core

    async def fake_resolve(backend: str, settings: Any, registry: Any) -> Any:
        return MagicMock(spec=MemoryCacheAdapter)

    monkeypatch.setattr(server_core, "resolve_cache_adapter", fake_resolve, raising=False)
    cfg = _make_config("memory")
    core = _make_core()
    await server_core._wire_cache(cfg, core)
    core._logger.info.assert_any_call(
        "cache-adapter-resolved",
        backend="memory",
        provider="memory",
        settings_class="MemoryCacheSettings",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_backend_does_not_resolve_redis_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    from dhara.mcp import server_core

    awaited_with: list[str] = []

    async def fake_resolve(backend: str, settings: Any, registry: Any) -> Any:
        awaited_with.append(backend)
        return MagicMock(spec=MemoryCacheAdapter)

    monkeypatch.setattr(server_core, "resolve_cache_adapter", fake_resolve, raising=False)
    cfg = _make_config("memory")
    core = _make_core()
    await server_core._wire_cache(cfg, core)
    assert awaited_with == ["memory"]
