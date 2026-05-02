"""Tests for dhara._compat — durus import alias layer."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from types import ModuleType

import pytest

from dhara._compat import (
    _DurusAliasFinder,
    _DurusAliasLoader,
    _DURUS_MODULE_ALIASES,
)


class TestDurusAliasLoader:
    def test_init_stores_target_name(self):
        loader = _DurusAliasLoader("dhara.core.persistent")
        assert loader.target_name == "dhara.core.persistent"

    def test_create_module_imports_target(self):
        loader = _DurusAliasLoader("dhara.core.persistent")
        spec = importlib.util.find_spec("dhara._compat")
        mod = loader.create_module(spec)
        assert mod is not None
        assert isinstance(mod, type(importlib.import_module("dhara.core.persistent")))

    def test_create_module_stores_in_sys_modules(self):
        loader = _DurusAliasLoader("dhara.core.persistent")
        spec = importlib.machinery.ModuleSpec(
            "durus.persistent_test_unique",
            loader,
        )
        mod = loader.create_module(spec)
        assert "durus.persistent_test_unique" in sys.modules
        sys.modules.pop("durus.persistent_test_unique", None)

    def test_exec_module_returns_none(self):
        loader = _DurusAliasLoader("dhara.core.persistent")
        assert loader.exec_module(None) is None


class TestDurusAliasFinder:
    def test_find_spec_unknown_returns_none(self):
        finder = _DurusAliasFinder()
        assert finder.find_spec("nonexistent.module", None) is None

    def test_find_spec_returns_spec_for_known_alias(self):
        finder = _DurusAliasFinder()
        spec = finder.find_spec("durus.persistent", None)
        assert spec is not None
        assert spec.name == "durus.persistent"

    def test_find_spec_returns_none_when_target_missing(self):
        finder = _DurusAliasFinder()
        # Temporarily use a nonexistent target
        spec = finder.find_spec("durus.nonexistent_target_xyz", None)
        assert spec is None


class TestModuleAliases:
    def test_aliases_dict_has_expected_keys(self):
        assert "durus.persistent" in _DURUS_MODULE_ALIASES
        assert "durus.persistent_dict" in _DURUS_MODULE_ALIASES

    def test_durus_module_exists_in_sys_modules(self):
        assert "durus" in sys.modules
        assert isinstance(sys.modules["durus"], ModuleType)

    def test_finder_installed_in_meta_path(self):
        assert any(isinstance(f, _DurusAliasFinder) for f in sys.meta_path)

    def test_can_import_via_alias(self):
        mod = importlib.import_module("durus.persistent")
        assert hasattr(mod, "Persistent")
