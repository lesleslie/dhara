"""Deprecated compatibility package that forwards legacy ``druva`` imports."""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys
import warnings
from typing import Any

import dhara as _dhara

warnings.warn(
    "The 'druva' package is deprecated; use 'dhara' instead.",
    DeprecationWarning,
    stacklevel=2,
)


class _DruvaAliasLoader(importlib.abc.Loader):
    """Load ``druva.*`` modules by reusing the matching ``dhara.*`` module."""

    def __init__(self, target_name: str):
        self.target_name = target_name

    def create_module(self, spec):  # type: ignore[override]
        module = importlib.import_module(self.target_name)
        sys.modules[spec.name] = module
        return module

    def exec_module(self, module):  # type: ignore[override]
        return None


class _DruvaAliasFinder(importlib.abc.MetaPathFinder):
    """Resolve legacy ``druva.*`` imports through the canonical ``dhara.*`` tree."""

    def find_spec(self, fullname: str, path, target=None):  # type: ignore[override]
        if not fullname.startswith("druva."):
            return None

        target_name = "dhara." + fullname[len("druva.") :]
        target_spec = importlib.util.find_spec(target_name)
        if target_spec is None:
            return None

        is_package = target_spec.submodule_search_locations is not None
        spec = importlib.machinery.ModuleSpec(
            fullname,
            _DruvaAliasLoader(target_name),
            is_package=is_package,
        )
        if is_package:
            spec.submodule_search_locations = list(
                target_spec.submodule_search_locations or []
            )
        spec.origin = getattr(target_spec, "origin", None)
        return spec


if not any(isinstance(finder, _DruvaAliasFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, _DruvaAliasFinder())


def __getattr__(name: str) -> Any:
    return getattr(_dhara, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_dhara)))


__all__ = getattr(_dhara, "__all__", [])
__version__ = getattr(_dhara, "__version__", "0.0.0")
