"""
Backward compatibility aliases for Durus 4.x.

This module provides aliases to support loading old Durus 4.x databases
that contain references to the old 'durus' package name.
"""

# Alias old Durus 4.x class names to new dhruva classes

# Create a fake 'durus' module for backward compatibility
import sys
from types import ModuleType


class _DurusCompatModule:
    """Fake durus module for backward compatibility."""

    def __init__(self):
        self._modules = {}

    def __getattr__(self, name):
        if name not in self._modules:
            # Create submodules on demand
            if name == "persistent":
                from dhruva.core import persistent

                self._modules[name] = persistent
            elif name == "persistent_dict":
                from dhruva.collections import dict as persistent_dict

                self._modules[name] = persistent_dict
            elif name == "persistent_list":
                from dhruva.collections import list as persistent_list

                self._modules[name] = persistent_list
            elif name == "persistent_set":
                from dhruva.collections import set as persistent_set

                self._modules[name] = persistent_set
            else:
                # Create empty module
                self._modules[name] = ModuleType(f"durus.{name}")

        return self._modules[name]


# Inject fake durus module into sys.modules for backward compatibility
if "durus" not in sys.modules:
    sys.modules["durus"] = _DurusCompatModule()

# Add specific submodules
sys.modules["durus.persistent"] = sys.modules["dhruva.core.persistent"]
sys.modules["durus.persistent_dict"] = sys.modules["dhruva.collections.dict"]
sys.modules["durus.persistent_list"] = sys.modules["dhruva.collections.list"]
sys.modules["durus.persistent_set"] = sys.modules["dhruva.collections.set"]
