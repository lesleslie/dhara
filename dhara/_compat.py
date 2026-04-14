"""Backward compatibility aliases for old ``durus`` import paths."""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys
from types import ModuleType

_DURUS_MODULE_ALIASES = {
    "durus.persistent": "dhara.core.persistent",
    "durus.persistent_dict": "dhara.collections.dict",
    "durus.persistent_list": "dhara.collections.list",
    "durus.persistent_set": "dhara.collections.set",
}


class _DurusAliasLoader(importlib.abc.Loader):
    def __init__(self, target_name: str):
        self.target_name = target_name

    def create_module(self, spec):  # type: ignore[override]
        module = importlib.import_module(self.target_name)
        sys.modules[spec.name] = module
        return module

    def exec_module(self, module):  # type: ignore[override]
        return None


class _DurusAliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path, target=None):  # type: ignore[override]
        target_name = _DURUS_MODULE_ALIASES.get(fullname)
        if target_name is None:
            return None

        target_spec = importlib.util.find_spec(target_name)
        if target_spec is None:
            return None

        spec = importlib.machinery.ModuleSpec(
            fullname,
            _DurusAliasLoader(target_name),
            is_package=target_spec.submodule_search_locations is not None,
        )
        spec.origin = getattr(target_spec, "origin", None)
        return spec


if "durus" not in sys.modules:
    durus_module = ModuleType("durus")
    durus_module.__path__ = []  # type: ignore[attr-defined]
    sys.modules["durus"] = durus_module


if not any(isinstance(finder, _DurusAliasFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, _DurusAliasFinder())
