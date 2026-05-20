"""Tests for dhara._compat — durus import alias layer."""

from __future__ import annotations

import importlib
import importlib.util
import builtins
import sys
from types import ModuleType

import pytest

from dhara._compat import (
    _DURUS_MODULE_ALIASES,
    _DurusAliasFinder,
    _DurusAliasLoader,
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
        loader.create_module(spec)
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

    def test_find_spec_returns_none_when_target_import_missing(
        self, monkeypatch
    ):
        finder = _DurusAliasFinder()
        monkeypatch.setattr(importlib.util, "find_spec", lambda *_args, **_kwargs: None)
        assert finder.find_spec("durus.persistent", None) is None


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


class TestLegacyShims:
    @pytest.mark.parametrize(
        "module_name",
        [
            "dhara.file_storage",
            "dhara.connection",
            "dhara.persistent",
            "dhara.persistent_dict",
            "dhara.persistent_list",
            "dhara.persistent_set",
        ],
    )
    def test_legacy_shims_removed(self, module_name: str):
        sys.modules.pop(module_name, None)
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module_name)


class TestCompatReload:
    def test_reload_uses_fallback_and_skips_duplicate_registration(self, monkeypatch):
        fake_backend = ModuleType("dhara._persistent")
        original_backend = sys.modules.get("dhara._persistent")
        try:
            monkeypatch.setitem(sys.modules, "dhara._persistent", fake_backend)
            compat = importlib.import_module("dhara._compat")
            importlib.reload(compat)

            assert "durus" in sys.modules
            assert any(isinstance(f, _DurusAliasFinder) for f in sys.meta_path)
        finally:
            if original_backend is not None:
                sys.modules["dhara._persistent"] = original_backend
            else:
                sys.modules.pop("dhara._persistent", None)
            importlib.reload(importlib.import_module("dhara._compat"))


class TestCompatModuleBody:
    def test_module_body_skips_duplicate_registration(self):
        compat_path = importlib.import_module("dhara._compat").__file__
        assert compat_path is not None
        source = open(compat_path, "r", encoding="utf-8").read()
        code = compile(source, compat_path, "exec")
        original_durus = sys.modules.get("durus")
        original_meta_path = list(sys.meta_path)
        original_any = builtins.any
        sys.modules["durus"] = ModuleType("durus")
        sys.modules["durus"].__path__ = []  # type: ignore[attr-defined]

        try:
            sys.modules.pop("dhara._compat", None)
            builtins.any = lambda _iterable: True  # type: ignore[assignment]
            module_globals = {
                "__name__": "dhara._compat_temp",
                "__file__": compat_path,
                "__package__": "dhara",
                "ModuleType": ModuleType,
                "sys": sys,
                "importlib": importlib,
                "_DurusAliasFinder": _DurusAliasFinder,
            }
            exec(code, module_globals)
            assert "durus" in sys.modules
            assert hasattr(sys.modules["durus"], "__path__")
        finally:
            builtins.any = original_any
            if original_durus is not None:
                sys.modules["durus"] = original_durus
            else:
                sys.modules.pop("durus", None)
            sys.meta_path[:] = original_meta_path
