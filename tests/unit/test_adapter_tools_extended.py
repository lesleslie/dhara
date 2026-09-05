"""Extended coverage for dhara/mcp/adapter_tools.py.

Pushes the AsyncAdapterRegistry class and the six async tool implementations
(store/get/list/list_versions/validate/get_health) from ~77% to >=92%.

The async methods mirror the sync AdapterRegistry class but use AsyncConnection
and an ``_initialized`` short-circuit flag instead of repeated structure
creation. The tool implementations wrap registry methods with structured error
handling, returning ``{"success": False, "error": str(e)}`` envelopes.

We use ``AsyncMemoryStorage`` directly (the same pattern as
``tests/test_async_adapter_registry.py``) rather than Protocol fakes because
``AsyncAdapterRegistry`` interacts with persistent collections (``__setitem__``,
``__contains__``, ``__getitem__``) that are easier to drive via the real
storage than via hand-rolled mocks.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from dhara.core.connection import AsyncConnection
from dhara.mcp.adapter_tools import (
    AsyncAdapterRegistry,
    get_adapter_async_impl,
    get_adapter_health_async_impl,
    list_adapter_versions_async_impl,
    list_adapters_async_impl,
    store_adapter_async_impl,
    validate_adapter_async_impl,
)
from dhara.storage.memory import AsyncMemoryStorage


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_registry() -> AsyncAdapterRegistry:
    """Build an AsyncAdapterRegistry backed by an in-memory AsyncConnection."""
    storage = AsyncMemoryStorage()
    await storage.init()
    conn = await AsyncConnection.new(storage)
    return AsyncAdapterRegistry(conn)


async def _store(
    registry: AsyncAdapterRegistry,
    domain: str = "adapter",
    key: str = "cache",
    provider: str = "redis",
    version: str = "1.0.0",
    factory_path: str = "os.path.join",
    **kwargs: Any,
) -> str:
    """Store one adapter through the async registry."""
    return await registry.store_adapter_async(
        domain=domain,
        key=key,
        provider=provider,
        version=version,
        factory_path=factory_path,
        config=kwargs.get("config", {}),
        dependencies=kwargs.get("dependencies", []),
        capabilities=kwargs.get("capabilities", ["cache"]),
        metadata=kwargs.get("metadata", {}),
    )


# ---------------------------------------------------------------------------
# AsyncAdapterRegistry — init / structure
# ---------------------------------------------------------------------------


class TestAsyncAdapterRegistryInit:
    """Tests for AsyncAdapterRegistry initialization."""

    @pytest.mark.asyncio
    async def test_init_creates_adapters_dict(self) -> None:
        registry = await _make_registry()
        await registry._ensure_root_async()
        root = await registry.connection.get_root()
        assert "adapters" in root

    @pytest.mark.asyncio
    async def test_init_creates_health_checks_dict(self) -> None:
        registry = await _make_registry()
        await registry._ensure_root_async()
        root = await registry.connection.get_root()
        assert "health_checks" in root

    @pytest.mark.asyncio
    async def test_init_sets_initialized_flag(self) -> None:
        registry = await _make_registry()
        await registry._ensure_root_async()
        assert registry._initialized is True

    @pytest.mark.asyncio
    async def test_init_idempotent_on_repeat(self) -> None:
        """Calling _ensure_root_async twice does not re-create structure."""
        registry = await _make_registry()
        await registry._ensure_root_async()
        # Second call is a no-op short-circuit
        await registry._ensure_root_async()
        assert registry._initialized is True

    @pytest.mark.asyncio
    async def test_init_preserves_existing_data(self) -> None:
        """Re-init does not wipe adapters already stored."""
        registry = await _make_registry()
        await _store(registry, version="1.0.0")
        assert await registry.count_async() == 1

        # Calling _ensure_root_async again must NOT clear existing adapters
        await registry._ensure_root_async()
        assert await registry.count_async() == 1


# ---------------------------------------------------------------------------
# AsyncAdapterRegistry.store_adapter_async
# ---------------------------------------------------------------------------


class TestStoreAdapterAsync:
    """Tests for AsyncAdapterRegistry.store_adapter_async."""

    @pytest.mark.asyncio
    async def test_store_creates_new_adapter(self) -> None:
        registry = await _make_registry()
        adapter_id = await _store(registry)
        assert adapter_id == "adapter:cache:redis"
        assert await registry.count_async() == 1

    @pytest.mark.asyncio
    async def test_store_update_existing_preserves_history(self) -> None:
        registry = await _make_registry()
        await _store(registry, version="1.0.0")
        await _store(registry, version="2.0.0")

        adapter = await registry.get_adapter_async("adapter", "cache", "redis")
        assert adapter is not None
        assert adapter["version"] == "2.0.0"

        versions = await registry.list_adapter_versions_async(
            domain="adapter",
            key="cache",
            provider="redis",
        )
        assert len(versions) == 2

    @pytest.mark.asyncio
    async def test_store_propagates_changelog(self) -> None:
        registry = await _make_registry()
        await _store(registry, version="1.0.0")
        await _store(registry, version="2.0.0", metadata={"changelog": "Upgrade"})

        versions = await registry.list_adapter_versions_async(
            domain="adapter",
            key="cache",
            provider="redis",
        )
        # The 1.0.0 entry carries the changelog; 2.0.0 is "Current version"
        old = [v for v in versions if v["version"] == "1.0.0"][0]
        assert old["changelog"] == "Upgrade"

    @pytest.mark.asyncio
    async def test_store_default_changelog(self) -> None:
        """Without an explicit changelog, history records 'Manual update'."""
        registry = await _make_registry()
        await _store(registry, version="1.0.0")
        await _store(registry, version="2.0.0", metadata={})

        versions = await registry.list_adapter_versions_async(
            domain="adapter",
            key="cache",
            provider="redis",
        )
        old = [v for v in versions if v["version"] == "1.0.0"][0]
        assert old["changelog"] == "Manual update"

    @pytest.mark.asyncio
    async def test_store_multiple_providers(self) -> None:
        registry = await _make_registry()
        await _store(registry, provider="redis")
        await _store(registry, provider="memcached")
        await _store(registry, domain="service", key="db", provider="pg")
        assert await registry.count_async() == 3


# ---------------------------------------------------------------------------
# AsyncAdapterRegistry.get_adapter_async
# ---------------------------------------------------------------------------


class TestGetAdapterAsync:
    """Tests for AsyncAdapterRegistry.get_adapter_async."""

    @pytest.mark.asyncio
    async def test_get_by_provider(self) -> None:
        registry = await _make_registry()
        await _store(registry, provider="redis")
        result = await registry.get_adapter_async("adapter", "cache", "redis")
        assert result is not None
        assert result["provider"] == "redis"

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self) -> None:
        registry = await _make_registry()
        assert await registry.get_adapter_async("x", "y", "z") is None

    @pytest.mark.asyncio
    async def test_get_without_provider_returns_first_match(self) -> None:
        registry = await _make_registry()
        await _store(registry, provider="redis")
        await _store(registry, provider="memcached")
        result = await registry.get_adapter_async("adapter", "cache")
        assert result is not None
        assert result["domain"] == "adapter"

    @pytest.mark.asyncio
    async def test_get_without_provider_no_match(self) -> None:
        registry = await _make_registry()
        assert await registry.get_adapter_async("nope", "nope") is None

    @pytest.mark.asyncio
    async def test_get_by_specific_version(self) -> None:
        registry = await _make_registry()
        await _store(registry, provider="redis", version="1.0.0")
        await _store(registry, provider="memcached", version="2.0.0")

        result = await registry.get_adapter_async("adapter", "cache", version="2.0.0")
        assert result is not None
        assert result["provider"] == "memcached"
        assert result["version"] == "2.0.0"

    @pytest.mark.asyncio
    async def test_get_by_version_not_found(self) -> None:
        registry = await _make_registry()
        await _store(registry, version="1.0.0")
        assert await registry.get_adapter_async("adapter", "cache", version="9.9.9") is None

    @pytest.mark.asyncio
    async def test_get_missing_provider_with_version(self) -> None:
        """provider+version combination with no adapters returns None."""
        registry = await _make_registry()
        assert (
            await registry.get_adapter_async("nope", "nope", "redis", "1.0.0") is None
        )


# ---------------------------------------------------------------------------
# AsyncAdapterRegistry.list_adapters_async
# ---------------------------------------------------------------------------


class TestListAdaptersAsync:
    """Tests for AsyncAdapterRegistry.list_adapters_async."""

    @pytest.mark.asyncio
    async def test_list_all(self) -> None:
        registry = await _make_registry()
        await _store(registry, provider="redis")
        await _store(registry, provider="memcached")
        assert len(await registry.list_adapters_async()) == 2

    @pytest.mark.asyncio
    async def test_list_empty(self) -> None:
        registry = await _make_registry()
        assert await registry.list_adapters_async() == []

    @pytest.mark.asyncio
    async def test_list_filter_by_domain(self) -> None:
        registry = await _make_registry()
        await _store(registry, domain="adapter")
        await _store(registry, domain="service")
        result = await registry.list_adapters_async(domain="adapter")
        assert len(result) == 1
        assert result[0]["domain"] == "adapter"

    @pytest.mark.asyncio
    async def test_list_filter_by_category(self) -> None:
        registry = await _make_registry()
        await _store(registry, metadata={"category": "storage"})
        await _store(registry, provider="memcached", metadata={"category": "cache"})
        result = await registry.list_adapters_async(category="storage")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_list_combined_filters(self) -> None:
        registry = await _make_registry()
        await _store(registry, domain="adapter", metadata={"category": "storage"})
        await _store(registry, domain="service", metadata={"category": "storage"})
        result = await registry.list_adapters_async(domain="adapter", category="storage")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# AsyncAdapterRegistry.list_adapter_versions_async
# ---------------------------------------------------------------------------


class TestListAdapterVersionsAsync:
    """Tests for AsyncAdapterRegistry.list_adapter_versions_async."""

    @pytest.mark.asyncio
    async def test_versions_empty_for_missing(self) -> None:
        registry = await _make_registry()
        assert await registry.list_adapter_versions_async("x", "y", "z") == []

    @pytest.mark.asyncio
    async def test_versions_includes_current(self) -> None:
        registry = await _make_registry()
        await _store(registry, version="1.0.0")
        versions = await registry.list_adapter_versions_async(
            domain="adapter", key="cache", provider="redis",
        )
        assert len(versions) == 1
        assert versions[0]["version"] == "1.0.0"
        assert versions[0]["changelog"] == "Current version"

    @pytest.mark.asyncio
    async def test_versions_history_sorted_descending(self) -> None:
        registry = await _make_registry()
        await _store(registry, version="1.0.0")
        await _store(registry, version="2.0.0")
        await _store(registry, version="3.0.0")
        versions = await registry.list_adapter_versions_async(
            domain="adapter", key="cache", provider="redis",
        )
        version_strs = [v["version"] for v in versions]
        assert version_strs[0] == "3.0.0"
        assert "1.0.0" in version_strs
        assert "2.0.0" in version_strs


# ---------------------------------------------------------------------------
# AsyncAdapterRegistry.validate_adapter_async
# ---------------------------------------------------------------------------


class TestValidateAdapterAsync:
    """Tests for AsyncAdapterRegistry.validate_adapter_async."""

    @pytest.mark.asyncio
    async def test_validate_missing_adapter(self) -> None:
        registry = await _make_registry()
        result = await registry.validate_adapter_async("x", "y", "z")
        assert result["valid"] is False
        assert len(result["errors"]) == 1
        assert "not found" in result["errors"][0].lower()

    @pytest.mark.asyncio
    async def test_validate_with_bad_factory_path(self) -> None:
        registry = await _make_registry()
        await _store(registry, factory_path="nonexistent_module.BadClass")
        result = await registry.validate_adapter_async("adapter", "cache", "redis")
        assert result["valid"] is False
        assert any("not importable" in e.lower() for e in result["errors"])

    @pytest.mark.asyncio
    async def test_validate_with_good_factory_path(self) -> None:
        registry = await _make_registry()
        await _store(registry, factory_path="os.path.join")
        result = await registry.validate_adapter_async("adapter", "cache", "redis")
        assert result["valid"] is True
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_validate_with_attribute_error(self) -> None:
        registry = await _make_registry()
        await _store(registry, factory_path="os.path.missing_attr")
        result = await registry.validate_adapter_async("adapter", "cache", "redis")
        assert result["valid"] is False
        assert any("Factory class not found" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_validate_with_generic_factory_error(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        registry = await _make_registry()
        await _store(registry, factory_path="os.path.join")

        monkeypatch.setattr(
            "dhara.mcp.adapter_tools._import_factory",
            lambda factory_path: (_ for _ in ()).throw(ValueError("boom")),
        )

        result = await registry.validate_adapter_async("adapter", "cache", "redis")
        assert result["valid"] is False
        assert any("Factory validation error" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_validate_warns_on_missing_dependency(self) -> None:
        registry = await _make_registry()
        await _store(
            registry,
            factory_path="os.path.join",
            dependencies=["missing:dep"],
        )
        result = await registry.validate_adapter_async("adapter", "cache", "redis")
        assert "Dependency not found: missing:dep" in result["warnings"]

    @pytest.mark.asyncio
    async def test_validate_warns_on_empty_capabilities(self) -> None:
        registry = await _make_registry()
        await _store(
            registry,
            factory_path="os.path.join",
            capabilities=[],
        )
        result = await registry.validate_adapter_async("adapter", "cache", "redis")
        assert "No capabilities declared" in result["warnings"]

    @pytest.mark.asyncio
    async def test_validate_with_dependency_without_colon(self) -> None:
        registry = await _make_registry()
        await _store(
            registry,
            factory_path="os.path.join",
            dependencies=["missingdep"],
        )
        result = await registry.validate_adapter_async("adapter", "cache", "redis")
        assert "Dependency not found: missingdep" in result["warnings"]

    @pytest.mark.asyncio
    async def test_validate_with_satisfied_dependency(self) -> None:
        registry = await _make_registry()
        await _store(
            registry,
            provider="redis",
            factory_path="os.path.join",
            capabilities=["cache"],
        )
        await _store(
            registry,
            provider="memcached",
            factory_path="os.path.join",
            dependencies=["adapter:cache:redis"],
            capabilities=["cache"],
        )
        result = await registry.validate_adapter_async("adapter", "cache", "memcached")
        dep_warnings = [w for w in result["warnings"] if "Dependency not found" in w]
        assert len(dep_warnings) == 0


# ---------------------------------------------------------------------------
# AsyncAdapterRegistry.check_adapter_health_async
# ---------------------------------------------------------------------------


class TestCheckAdapterHealthAsync:
    """Tests for AsyncAdapterRegistry.check_adapter_health_async."""

    @pytest.mark.asyncio
    async def test_health_missing_adapter(self) -> None:
        registry = await _make_registry()
        result = await registry.check_adapter_health_async("x", "y", "z")
        assert result["healthy"] is False
        assert result["error"] == "Adapter not found"
        assert result["last_check"] is None

    @pytest.mark.asyncio
    async def test_health_healthy_adapter(self) -> None:
        registry = await _make_registry()
        await _store(registry, factory_path="os.path.join")
        result = await registry.check_adapter_health_async("adapter", "cache", "redis")
        assert result["healthy"] is True
        assert result["status"] == "healthy"
        assert result["last_check"] is not None

    @pytest.mark.asyncio
    async def test_health_unhealthy_adapter(self) -> None:
        registry = await _make_registry()
        await _store(registry, factory_path="nonexistent.module.Factory")
        result = await registry.check_adapter_health_async("adapter", "cache", "redis")
        assert result["healthy"] is False
        assert result["status"] == "unhealthy"
        assert "error" in result

    @pytest.mark.asyncio
    async def test_health_stores_result(self) -> None:
        registry = await _make_registry()
        await _store(registry, factory_path="os.path.join")
        await registry.check_adapter_health_async("adapter", "cache", "redis")

        root = await registry.connection.get_root()
        health_checks = root["health_checks"]
        assert "adapter:cache:redis" in health_checks

    @pytest.mark.asyncio
    async def test_health_updates_adapter_status(self) -> None:
        registry = await _make_registry()
        await _store(registry, factory_path="os.path.join")
        await registry.check_adapter_health_async("adapter", "cache", "redis")

        root = await registry.connection.get_root()
        adapter = root["adapters"]["adapter:cache:redis"]
        assert adapter.health_status == "healthy"
        assert adapter.last_health_check is not None


# ---------------------------------------------------------------------------
# AsyncAdapterRegistry.count_async
# ---------------------------------------------------------------------------


class TestCountAsync:
    """Tests for AsyncAdapterRegistry.count_async."""

    @pytest.mark.asyncio
    async def test_count_empty(self) -> None:
        registry = await _make_registry()
        assert await registry.count_async() == 0

    @pytest.mark.asyncio
    async def test_count_after_stores(self) -> None:
        registry = await _make_registry()
        await _store(registry, provider="redis")
        await _store(registry, provider="memcached")
        await _store(registry, domain="service", key="db", provider="pg")
        assert await registry.count_async() == 3


# ---------------------------------------------------------------------------
# Async tool implementations (the `_impl` wrappers)
# ---------------------------------------------------------------------------


class TestStoreAdapterAsyncImpl:
    """Tests for store_adapter_async_impl."""

    @pytest.mark.asyncio
    async def test_store_success(self) -> None:
        registry = await _make_registry()
        result = await store_adapter_async_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
            factory_path="os.path.join",
            config={},
            dependencies=[],
            capabilities=["cache"],
            metadata={},
        )
        assert result["success"] is True
        assert result["adapter_id"] == "adapter:cache:redis"
        assert result["version"] == "1.0.0"
        assert "Stored" in result["message"]

    @pytest.mark.asyncio
    async def test_store_error_handling(self) -> None:
        registry = await _make_registry()
        # Force the inner call to raise
        registry.store_adapter_async = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("boom"),
        )
        result = await store_adapter_async_impl(
            registry=registry,
            domain="a",
            key="b",
            provider="c",
            version="1.0.0",
            factory_path="x",
            config={},
            dependencies=[],
            capabilities=[],
            metadata={},
        )
        assert result["success"] is False
        assert "boom" in result["error"]


class TestGetAdapterAsyncImpl:
    """Tests for get_adapter_async_impl."""

    @pytest.mark.asyncio
    async def test_get_found(self) -> None:
        registry = await _make_registry()
        await _store(registry)
        result = await get_adapter_async_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
        )
        assert result["success"] is True
        assert result["adapter"]["adapter_id"] == "adapter:cache:redis"

    @pytest.mark.asyncio
    async def test_get_not_found(self) -> None:
        registry = await _make_registry()
        result = await get_adapter_async_impl(
            registry=registry,
            domain="x",
            key="y",
        )
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_get_error_handling(self) -> None:
        registry = await _make_registry()
        registry.get_adapter_async = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("fail"),
        )
        result = await get_adapter_async_impl(
            registry=registry,
            domain="a",
            key="b",
        )
        assert result["success"] is False
        assert "fail" in result["error"]


class TestListAdaptersAsyncImpl:
    """Tests for list_adapters_async_impl."""

    @pytest.mark.asyncio
    async def test_list_empty(self) -> None:
        registry = await _make_registry()
        result = await list_adapters_async_impl(registry=registry)
        assert result["success"] is True
        assert result["count"] == 0
        assert result["adapters"] == []

    @pytest.mark.asyncio
    async def test_list_with_results(self) -> None:
        registry = await _make_registry()
        await _store(registry, provider="redis")
        await _store(registry, provider="memcached")
        result = await list_adapters_async_impl(registry=registry)
        assert result["success"] is True
        assert result["count"] == 2
        assert len(result["adapters"]) == 2

    @pytest.mark.asyncio
    async def test_list_with_filters(self) -> None:
        registry = await _make_registry()
        await _store(registry, domain="adapter")
        result = await list_adapters_async_impl(
            registry=registry,
            domain="adapter",
            category="storage",
        )
        assert result["filters"]["domain"] == "adapter"
        assert result["filters"]["category"] == "storage"

    @pytest.mark.asyncio
    async def test_list_error_handling(self) -> None:
        registry = await _make_registry()
        registry.list_adapters_async = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("oops"),
        )
        result = await list_adapters_async_impl(registry=registry)
        assert result["success"] is False
        assert "oops" in result["error"]
        assert result["adapters"] == []


class TestListAdapterVersionsAsyncImpl:
    """Tests for list_adapter_versions_async_impl."""

    @pytest.mark.asyncio
    async def test_versions_found(self) -> None:
        registry = await _make_registry()
        await _store(registry, version="1.0.0")
        await _store(registry, version="2.0.0")
        result = await list_adapter_versions_async_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
        )
        assert result["success"] is True
        assert result["count"] == 2
        assert len(result["versions"]) == 2

    @pytest.mark.asyncio
    async def test_versions_empty(self) -> None:
        registry = await _make_registry()
        result = await list_adapter_versions_async_impl(
            registry=registry,
            domain="x",
            key="y",
            provider="z",
        )
        assert result["success"] is True
        assert result["count"] == 0
        assert result["versions"] == []

    @pytest.mark.asyncio
    async def test_versions_error_handling(self) -> None:
        registry = await _make_registry()
        registry.list_adapter_versions_async = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("err"),
        )
        result = await list_adapter_versions_async_impl(
            registry=registry,
            domain="a",
            key="b",
            provider="c",
        )
        assert result["success"] is False
        assert "err" in result["error"]
        assert result["versions"] == []


class TestValidateAdapterAsyncImpl:
    """Tests for validate_adapter_async_impl."""

    @pytest.mark.asyncio
    async def test_validate_success(self) -> None:
        registry = await _make_registry()
        await _store(registry, factory_path="os.path.join")
        result = await validate_adapter_async_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
        )
        assert result["success"] is True
        assert result["validation"]["valid"] is True

    @pytest.mark.asyncio
    async def test_validate_not_found(self) -> None:
        registry = await _make_registry()
        result = await validate_adapter_async_impl(
            registry=registry,
            domain="x",
            key="y",
            provider="z",
        )
        assert result["success"] is True
        assert result["validation"]["valid"] is False

    @pytest.mark.asyncio
    async def test_validate_with_version(self) -> None:
        registry = await _make_registry()
        await _store(registry, factory_path="os.path.join")
        result = await validate_adapter_async_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_validate_error_handling(self) -> None:
        registry = await _make_registry()
        registry.validate_adapter_async = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("bad"),
        )
        result = await validate_adapter_async_impl(
            registry=registry,
            domain="a",
            key="b",
            provider="c",
        )
        assert result["success"] is False
        assert "bad" in result["error"]


class TestGetAdapterHealthAsyncImpl:
    """Tests for get_adapter_health_async_impl."""

    @pytest.mark.asyncio
    async def test_health_healthy(self) -> None:
        registry = await _make_registry()
        await _store(registry, factory_path="os.path.join")
        result = await get_adapter_health_async_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
        )
        assert result["success"] is True
        assert result["health"]["healthy"] is True

    @pytest.mark.asyncio
    async def test_health_not_found(self) -> None:
        registry = await _make_registry()
        result = await get_adapter_health_async_impl(
            registry=registry,
            domain="x",
            key="y",
            provider="z",
        )
        assert result["success"] is True
        assert result["health"]["healthy"] is False

    @pytest.mark.asyncio
    async def test_health_error_handling(self) -> None:
        registry = await _make_registry()
        registry.check_adapter_health_async = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("crash"),
        )
        result = await get_adapter_health_async_impl(
            registry=registry,
            domain="a",
            key="b",
            provider="c",
        )
        assert result["success"] is False
        assert "crash" in result["error"]
