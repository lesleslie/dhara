"""Coverage probe for dhara._compat import-time branch behavior."""

from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path
from types import ModuleType


def test_import_time_finder_guard_skips_duplicate_registration():
    compat_path = Path(__file__).resolve().parents[1] / "dhara" / "_compat.py"
    source = compat_path.read_text(encoding="utf-8")
    code = compile(source, str(compat_path), "exec")

    original_any = builtins.any
    original_durus = sys.modules.get("durus")
    original_meta_path = list(sys.meta_path)

    try:
        sys.modules["durus"] = ModuleType("durus")
        sys.modules["durus"].__path__ = []  # type: ignore[attr-defined]
        builtins.any = lambda _iterable: True  # type: ignore[assignment]

        module_globals = {
            "__name__": "dhara._compat_probe",
            "__file__": str(compat_path),
            "__package__": "dhara",
            "__builtins__": builtins.__dict__,
            "sys": sys,
            "importlib": importlib,
            "ModuleType": ModuleType,
        }
        exec(code, module_globals)

        assert "durus" in sys.modules
        assert hasattr(sys.modules["durus"], "__path__")
    finally:
        builtins.any = original_any
        sys.meta_path[:] = original_meta_path
        if original_durus is not None:
            sys.modules["durus"] = original_durus
        else:
            sys.modules.pop("durus", None)
