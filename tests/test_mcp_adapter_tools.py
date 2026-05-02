"""Tests for dhara/mcp/adapter_tools.py -- Adapter, AdapterRegistry, and async tool impls."""

from __future__ import annotations

import importlib
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from dhara.mcp.adapter_tools import (
    Adapter,
    AdapterRegistry,
    _import_factory,
    get_adapter_health_impl,
    get_adapter_impl,
    list_adapter_versions_impl,
    list_adapters_impl,
    store_adapter_impl,
    validate_adapter_impl,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_adapter_dict(
    domain: str = "adapter",
    key: str = "cache",
    provider: str = "redis",
    version: str = "1.0.0",
    **overrides: Any,
) -> dict[str, Any]:
    """Return a minimal adapter creation payload."""
    base = {
        "domain": domain,
        "key": key,
        "provider": provider,
        "version": version,
        "factory_path": "myapp.adapters.RedisCache",
        "config": {},
        "dependencies": [],
        "capabilities": ["cache"],
        "metadata": {"category": "storage"},
    }
    base.update(overrides)
    return base


def _store_sample_adapter(
    registry: AdapterRegistry,
    domain: str = "adapter",
    key: str = "cache",
    provider: str = "redis",
    version: str = "1.0.0",
    factory_path: str = "myapp.adapters.RedisCache",
    **kwargs: Any,
) -> str:
    """Store one adapter through the registry and return its id."""
    return registry.store_adapter(
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
# _import_factory
# ---------------------------------------------------------------------------


class TestImportFactory:
    """Tests for the _import_factory helper."""

    def test_imports_valid_path(self) -> None:
        module, cls = _import_factory("os.path.join")
        import os.path

        assert module is os.path
        assert cls is os.path.join

    def test_imports_builtin_module(self) -> None:
        module, cls = _import_factory("collections.OrderedDict")
        from collections import OrderedDict

        assert cls is OrderedDict

    def test_raises_on_invalid_path(self) -> None:
        with pytest.raises((ImportError, ModuleNotFoundError)):
            _import_factory("nonexistent_module.SomeClass")

    def test_raises_on_missing_attribute(self) -> None:
        with pytest.raises(AttributeError):
            _import_factory("os.path.totally_fake_function_xyz")

    def test_druva_to_dhara_fallback(self) -> None:
        """If a 'druva.' path fails, it retries with 'dhara.'."""
        with patch("importlib.import_module", side_effect=ImportError("no druva")) as mock_import:
            with pytest.raises(ImportError):
                _import_factory("druva.some.module.MyClass")

        calls = mock_import.call_args_list
        assert len(calls) == 2
        assert calls[0][0][0] == "druva.some.module"
        assert calls[1][0][0] == "dhara.some.module"

    def test_druva_fallback_succeeds(self) -> None:
        """If druva path fails but dhara path succeeds, return the result."""
        from dhara.collections.dict import PersistentDict

        call_count = 0
        original_import = importlib.import_module

        def _mock_import(path: str) -> Any:
            nonlocal call_count
            call_count += 1
            if path == "druva.collections.dict":
                raise ImportError("no druva")
            return original_import(path)

        with patch("importlib.import_module", side_effect=_mock_import):
            module, cls = _import_factory("druva.collections.dict.PersistentDict")

        assert call_count == 2
        assert cls is PersistentDict


# ---------------------------------------------------------------------------
# Adapter model
# ---------------------------------------------------------------------------


class TestAdapter:
    """Tests for the Adapter persistent model."""

    def test_default_attributes(self) -> None:
        a = Adapter(domain="adapter", key="cache", provider="redis")
        assert a.domain == "adapter"
        assert a.key == "cache"
        assert a.provider == "redis"
        assert a.version == "1.0.0"
        assert a.config == {}
        assert a.dependencies == []
        assert a.capabilities == []
        assert a.metadata == {}
        assert a.health_status == "unknown"
        assert a.last_health_check is None

    def test_factory_path_default(self) -> None:
        a = Adapter(domain="adapter", key="cache", provider="redis")
        assert a.factory_path == "adapter.cache.redis"

    def test_factory_path_explicit(self) -> None:
        a = Adapter(
            domain="adapter",
            key="cache",
            provider="redis",
            factory_path="mypackage.RedisFactory",
        )
        assert a.factory_path == "mypackage.RedisFactory"

    def test_to_dict_keys(self) -> None:
        a = Adapter(domain="adapter", key="cache", provider="redis", version="2.1.0")
        d = a.to_dict()
        assert d["domain"] == "adapter"
        assert d["key"] == "cache"
        assert d["provider"] == "redis"
        assert d["version"] == "2.1.0"
        assert d["adapter_id"] == "adapter:cache:redis"
        assert d["schema_version"] == 1
        assert "created_at" in d
        assert "updated_at" in d
        assert d["health_status"] == "unknown"
        assert d["last_health_check"] is None

    def test_update_version_tracks_history(self) -> None:
        a = Adapter(domain="a", key="b", provider="c", version="1.0.0")
        a.update_version("2.0.0", changelog="Major upgrade", config={"x": 1})

        assert a.version == "2.0.0"
        assert a.config == {"x": 1}
        assert len(a.version_history) == 1
        assert a.version_history[0]["version"] == "1.0.0"
        assert a.version_history[0]["changelog"] == "Major upgrade"

    def test_update_version_history_limit(self) -> None:
        a = Adapter(domain="a", key="b", provider="c", version="0.0.1")
        for i in range(1, 13):
            a.update_version(f"0.0.{i + 1}", changelog=f"v{i}")
        assert len(a.version_history) == 10

    def test_update_version_sets_arbitrary_fields(self) -> None:
        a = Adapter(domain="a", key="b", provider="c", version="1.0.0")
        a.update_version(
            "2.0.0",
            changelog="expand capabilities",
            capabilities=["read", "write"],
            dependencies=["other"],
        )
        assert a.capabilities == ["read", "write"]
        assert a.dependencies == ["other"]

    def test_rollback_to_version_success(self) -> None:
        a = Adapter(
            domain="a",
            key="b",
            provider="c",
            version="1.0.0",
            capabilities=["x"],
        )
        a.update_version(
            "2.0.0",
            changelog="changed",
            capabilities=["y"],
            dependencies=["dep"],
        )
        assert a.capabilities == ["y"]

        result = a.rollback_to_version("1.0.0")
        assert result is True
        assert a.version == "1.0.0"
        assert a.capabilities == ["x"]
        assert a.dependencies == []

    def test_rollback_to_version_not_found(self) -> None:
        a = Adapter(domain="a", key="b", provider="c", version="1.0.0")
        assert a.rollback_to_version("99.99.99") is False

    def test_to_dict_last_health_check_with_value(self) -> None:
        a = Adapter(domain="a", key="b", provider="c")
        now = datetime.now()
        a.last_health_check = now
        d = a.to_dict()
        assert d["last_health_check"] == now.isoformat()


# ---------------------------------------------------------------------------
# AdapterRegistry
# ---------------------------------------------------------------------------


class TestAdapterRegistryInit:
    """Tests for AdapterRegistry initialization and structure."""

    def test_creates_adapters_dict(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        root = connection.get_root()
        assert "adapters" in root

    def test_creates_health_checks_dict(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        root = connection.get_root()
        assert "health_checks" in root

    def test_existing_structure_preserved(self, connection: Any) -> None:
        """Second initialization should not overwrite existing data."""
        from dhara.collections.dict import PersistentDict

        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry)
        assert registry.count() == 1

        # Re-init should not wipe
        registry2 = AdapterRegistry(connection)
        assert registry2.count() == 1


class TestAdapterRegistryStore:
    """Tests for AdapterRegistry.store_adapter."""

    def test_store_new_adapter(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        adapter_id = _store_sample_adapter(registry)
        assert adapter_id == "adapter:cache:redis"
        assert registry.count() == 1

    def test_store_returns_adapter_id(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        aid = registry.store_adapter(
            domain="service",
            key="storage",
            provider="s3",
            version="3.0.0",
            factory_path="myapp.S3Storage",
            config={"region": "us-east-1"},
            dependencies=["adapter:cache:redis"],
            capabilities=["read", "write"],
            metadata={"author": "team"},
        )
        assert aid == "service:storage:s3"

    def test_store_update_existing_adapter(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry, version="1.0.0")
        _store_sample_adapter(registry, version="2.0.0")

        adapter = registry.get_adapter("adapter", "cache", "redis")
        assert adapter is not None
        assert adapter["version"] == "2.0.0"

    def test_store_update_preserves_history(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry, version="1.0.0")
        _store_sample_adapter(registry, version="2.0.0")

        versions = registry.list_adapter_versions("adapter", "cache", "redis")
        version_strs = [v["version"] for v in versions]
        assert "1.0.0" in version_strs
        assert "2.0.0" in version_strs

    def test_store_multiple_providers(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry, provider="redis")
        _store_sample_adapter(registry, provider="memcached")
        assert registry.count() == 2


class TestAdapterRegistryGet:
    """Tests for AdapterRegistry.get_adapter."""

    def test_get_by_provider(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry, provider="redis", version="1.0.0")
        result = registry.get_adapter("adapter", "cache", "redis")
        assert result is not None
        assert result["provider"] == "redis"

    def test_get_missing_returns_none(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        assert registry.get_adapter("x", "y", "z") is None

    def test_get_without_provider_returns_first_match(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry, provider="redis")
        _store_sample_adapter(registry, provider="memcached")
        result = registry.get_adapter("adapter", "cache")
        assert result is not None
        assert result["domain"] == "adapter"

    def test_get_without_provider_no_match(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        assert registry.get_adapter("nope", "nope") is None

    def test_get_by_version(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry, provider="redis", version="1.0.0")
        _store_sample_adapter(registry, provider="memcached", version="2.0.0")

        result = registry.get_adapter("adapter", "cache", version="2.0.0")
        assert result is not None
        assert result["version"] == "2.0.0"

    def test_get_by_version_not_found(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry, version="1.0.0")
        assert registry.get_adapter("adapter", "cache", version="9.9.9") is None


class TestAdapterRegistryList:
    """Tests for AdapterRegistry.list_adapters."""

    def test_list_all(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry, provider="redis")
        _store_sample_adapter(registry, provider="memcached")
        assert len(registry.list_adapters()) == 2

    def test_list_empty(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        assert registry.list_adapters() == []

    def test_list_filter_by_domain(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry, domain="adapter")
        _store_sample_adapter(registry, domain="service")
        result = registry.list_adapters(domain="adapter")
        assert len(result) == 1
        assert result[0]["domain"] == "adapter"

    def test_list_filter_by_category(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(
            registry,
            metadata={"category": "storage"},
        )
        _store_sample_adapter(
            registry,
            provider="memcached",
            metadata={"category": "cache"},
        )
        result = registry.list_adapters(category="storage")
        assert len(result) == 1

    def test_list_combined_filters(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(
            registry,
            domain="adapter",
            metadata={"category": "storage"},
        )
        _store_sample_adapter(
            registry,
            domain="service",
            metadata={"category": "storage"},
        )
        result = registry.list_adapters(domain="adapter", category="storage")
        assert len(result) == 1


class TestAdapterRegistryVersions:
    """Tests for AdapterRegistry.list_adapter_versions."""

    def test_versions_empty_for_missing(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        assert registry.list_adapter_versions("x", "y", "z") == []

    def test_versions_includes_current(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry, version="1.0.0")
        versions = registry.list_adapter_versions("adapter", "cache", "redis")
        assert len(versions) == 1
        assert versions[0]["version"] == "1.0.0"
        assert versions[0]["changelog"] == "Current version"

    def test_versions_history_sorted_descending(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry, version="1.0.0")
        _store_sample_adapter(registry, version="2.0.0")
        _store_sample_adapter(registry, version="3.0.0")
        versions = registry.list_adapter_versions("adapter", "cache", "redis")
        version_strs = [v["version"] for v in versions]
        assert version_strs[0] == "3.0.0"
        assert "1.0.0" in version_strs
        assert "2.0.0" in version_strs


class TestAdapterRegistryValidate:
    """Tests for AdapterRegistry.validate_adapter."""

    def test_validate_missing_adapter(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        result = registry.validate_adapter("x", "y", "z")
        assert result["valid"] is False
        assert len(result["errors"]) == 1

    def test_validate_with_bad_factory_path(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(
            registry,
            factory_path="nonexistent_module.BadClass",
        )
        result = registry.validate_adapter("adapter", "cache", "redis")
        assert result["valid"] is False
        assert any("not importable" in e.lower() or "not found" in e.lower() for e in result["errors"])

    def test_validate_with_good_factory_path(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(
            registry,
            factory_path="os.path.join",
        )
        result = registry.validate_adapter("adapter", "cache", "redis")
        assert result["valid"] is True
        assert result["errors"] == []

    def test_validate_warns_on_missing_dependency(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(
            registry,
            factory_path="os.path.join",
            dependencies=["missing:dep"],
        )
        result = registry.validate_adapter("adapter", "cache", "redis")
        assert "Dependency not found: missing:dep" in result["warnings"]

    def test_validate_warns_on_empty_capabilities(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(
            registry,
            factory_path="os.path.join",
            capabilities=[],
        )
        result = registry.validate_adapter("adapter", "cache", "redis")
        assert "No capabilities declared" in result["warnings"]

    def test_validate_with_satisfied_dependencies(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(
            registry,
            provider="redis",
            factory_path="os.path.join",
            capabilities=["cache"],
        )
        _store_sample_adapter(
            registry,
            provider="memcached",
            factory_path="os.path.join",
            dependencies=["adapter:cache:redis"],
            capabilities=["cache"],
        )
        result = registry.validate_adapter("adapter", "cache", "memcached")
        # The dependency should be found, so no warning for it
        dep_warnings = [w for w in result["warnings"] if "Dependency not found" in w]
        assert len(dep_warnings) == 0


class TestAdapterRegistryHealth:
    """Tests for AdapterRegistry.check_adapter_health."""

    def test_health_missing_adapter(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        result = registry.check_adapter_health("x", "y", "z")
        assert result["healthy"] is False
        assert result["error"] == "Adapter not found"

    def test_health_healthy_adapter(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(
            registry,
            factory_path="os.path.join",
        )
        result = registry.check_adapter_health("adapter", "cache", "redis")
        assert result["healthy"] is True
        assert result["status"] == "healthy"
        assert result["last_check"] is not None

    def test_health_unhealthy_adapter(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(
            registry,
            factory_path="nonexistent.module.Factory",
        )
        result = registry.check_adapter_health("adapter", "cache", "redis")
        assert result["healthy"] is False
        assert result["status"] == "unhealthy"

    def test_health_stores_result(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry, factory_path="os.path.join")
        registry.check_adapter_health("adapter", "cache", "redis")

        root = connection.get_root()
        health_checks = root["health_checks"]
        assert "adapter:cache:redis" in health_checks

    def test_health_updates_adapter_status(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry, factory_path="os.path.join")
        registry.check_adapter_health("adapter", "cache", "redis")

        root = connection.get_root()
        adapter = root["adapters"]["adapter:cache:redis"]
        assert adapter.health_status == "healthy"
        assert adapter.last_health_check is not None


class TestAdapterRegistryCount:
    """Tests for AdapterRegistry.count."""

    def test_count_empty(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        assert registry.count() == 0

    def test_count_after_stores(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry, provider="redis")
        _store_sample_adapter(registry, provider="memcached")
        _store_sample_adapter(registry, domain="service", key="db", provider="pg")
        assert registry.count() == 3


# ---------------------------------------------------------------------------
# Async tool implementations
# ---------------------------------------------------------------------------


class TestStoreAdapterImpl:
    """Tests for the store_adapter_impl async wrapper."""

    @pytest.mark.asyncio
    async def test_store_success(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        result = await store_adapter_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
            factory_path="myapp.Redis",
            config={},
            dependencies=[],
            capabilities=["cache"],
            metadata={},
        )
        assert result["success"] is True
        assert result["adapter_id"] == "adapter:cache:redis"
        assert result["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_store_error_handling(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        registry.store_adapter = MagicMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
        result = await store_adapter_impl(
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


class TestGetAdapterImpl:
    """Tests for the get_adapter_impl async wrapper."""

    @pytest.mark.asyncio
    async def test_get_found(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry)
        result = await get_adapter_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
        )
        assert result["success"] is True
        assert result["adapter"]["adapter_id"] == "adapter:cache:redis"

    @pytest.mark.asyncio
    async def test_get_not_found(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        result = await get_adapter_impl(
            registry=registry,
            domain="x",
            key="y",
        )
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_get_error_handling(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        registry.get_adapter = MagicMock(side_effect=RuntimeError("fail"))  # type: ignore[method-assign]
        result = await get_adapter_impl(
            registry=registry,
            domain="a",
            key="b",
        )
        assert result["success"] is False
        assert "fail" in result["error"]


class TestListAdaptersImpl:
    """Tests for the list_adapters_impl async wrapper."""

    @pytest.mark.asyncio
    async def test_list_empty(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        result = await list_adapters_impl(registry=registry)
        assert result["success"] is True
        assert result["count"] == 0
        assert result["adapters"] == []

    @pytest.mark.asyncio
    async def test_list_with_results(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry, provider="redis")
        _store_sample_adapter(registry, provider="memcached")
        result = await list_adapters_impl(registry=registry)
        assert result["success"] is True
        assert result["count"] == 2
        assert len(result["adapters"]) == 2

    @pytest.mark.asyncio
    async def test_list_with_filters(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry, domain="adapter")
        result = await list_adapters_impl(
            registry=registry,
            domain="adapter",
            category="storage",
        )
        assert result["filters"]["domain"] == "adapter"
        assert result["filters"]["category"] == "storage"

    @pytest.mark.asyncio
    async def test_list_error_handling(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        registry.list_adapters = MagicMock(side_effect=RuntimeError("oops"))  # type: ignore[method-assign]
        result = await list_adapters_impl(registry=registry)
        assert result["success"] is False
        assert "oops" in result["error"]
        assert result["adapters"] == []


class TestListAdapterVersionsImpl:
    """Tests for the list_adapter_versions_impl async wrapper."""

    @pytest.mark.asyncio
    async def test_versions_found(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry, version="1.0.0")
        _store_sample_adapter(registry, version="2.0.0")
        result = await list_adapter_versions_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
        )
        assert result["success"] is True
        assert result["count"] >= 2
        assert len(result["versions"]) >= 2

    @pytest.mark.asyncio
    async def test_versions_empty(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        result = await list_adapter_versions_impl(
            registry=registry,
            domain="x",
            key="y",
            provider="z",
        )
        assert result["success"] is True
        assert result["count"] == 0
        assert result["versions"] == []

    @pytest.mark.asyncio
    async def test_versions_error_handling(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        registry.list_adapter_versions = MagicMock(side_effect=RuntimeError("err"))  # type: ignore[method-assign]
        result = await list_adapter_versions_impl(
            registry=registry,
            domain="a",
            key="b",
            provider="c",
        )
        assert result["success"] is False
        assert "err" in result["error"]
        assert result["versions"] == []


class TestValidateAdapterImpl:
    """Tests for the validate_adapter_impl async wrapper."""

    @pytest.mark.asyncio
    async def test_validate_success(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry, factory_path="os.path.join")
        result = await validate_adapter_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
        )
        assert result["success"] is True
        assert result["validation"]["valid"] is True

    @pytest.mark.asyncio
    async def test_validate_not_found(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        result = await validate_adapter_impl(
            registry=registry,
            domain="x",
            key="y",
            provider="z",
        )
        assert result["success"] is True  # the impl itself succeeds
        assert result["validation"]["valid"] is False

    @pytest.mark.asyncio
    async def test_validate_error_handling(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        registry.validate_adapter = MagicMock(side_effect=RuntimeError("bad"))  # type: ignore[method-assign]
        result = await validate_adapter_impl(
            registry=registry,
            domain="a",
            key="b",
            provider="c",
        )
        assert result["success"] is False
        assert "bad" in result["error"]

    @pytest.mark.asyncio
    async def test_validate_with_version(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry, factory_path="os.path.join")
        result = await validate_adapter_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
            version="1.0.0",
        )
        assert result["success"] is True


class TestGetAdapterHealthImpl:
    """Tests for the get_adapter_health_impl async wrapper."""

    @pytest.mark.asyncio
    async def test_health_healthy(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        _store_sample_adapter(registry, factory_path="os.path.join")
        result = await get_adapter_health_impl(
            registry=registry,
            domain="adapter",
            key="cache",
            provider="redis",
        )
        assert result["success"] is True
        assert result["health"]["healthy"] is True

    @pytest.mark.asyncio
    async def test_health_not_found(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        result = await get_adapter_health_impl(
            registry=registry,
            domain="x",
            key="y",
            provider="z",
        )
        assert result["success"] is True
        assert result["health"]["healthy"] is False

    @pytest.mark.asyncio
    async def test_health_error_handling(self, connection: Any) -> None:
        registry = AdapterRegistry(connection)
        registry.check_adapter_health = MagicMock(side_effect=RuntimeError("crash"))  # type: ignore[method-assign]
        result = await get_adapter_health_impl(
            registry=registry,
            domain="a",
            key="b",
            provider="c",
        )
        assert result["success"] is False
        assert "crash" in result["error"]
