"""msgspec-based serializer for Durus.

msgspec is a fast and safe serialization library that supports:
- MessagePack format (binary, compact)
- JSON format (text, interoperable)
- Very fast (faster than pickle)
- Safer (no arbitrary code execution)
"""

import logging
from typing import Any, Literal

from msgspec import json, msgpack, to_builtins

from dhruva.core.persistent import Persistent, _setattribute
from dhruva.serialize.base import DEFAULT_MAX_SIZE, Serializer

logger = logging.getLogger(__name__)

# Default whitelist of safe modules for class deserialization
# This prevents arbitrary code execution via __import__
DEFAULT_ALLOWED_MODULES: set[str] = {
    # dhruva core modules
    "dhruva",
    "dhruva.collections",
    "dhruva.collections.dict",
    "dhruva.collections.list",
    "dhruva.collections.set",
    "dhruva.collections.btree",
    "dhruva.core",
    "dhruva.core.persistent",
    "dhruva.core.connection",
    # Standard library collections (safe)
    "collections",
    "collections.abc",
    # Built-in types (no module needed)
    "__builtin__",
    "builtins",
}


class MsgspecSerializer(Serializer):
    """msgspec-based serializer.

    Advantages over pickle:
    - 5-10x faster serialization
    - Safer (no code execution on deserialize)
    - Smaller serialized size
    - Schema validation support

    Trade-offs:
    - Cannot serialize all Python objects (need custom encoders)
    - Requires type hints for best performance
    - Newer library than pickle
    """

    def __init__(
        self,
        format: Literal["msgpack", "json"] = "msgpack",
        use_builtins: bool = True,
        allowed_modules: set[str] | None = None,
    ):
        """Initialize msgspec serializer.

        Args:
            format: Serialization format (msgpack or json)
            use_builtins: Convert to built-in types for compatibility
            allowed_modules: Optional whitelist of allowed modules for deserialization.
                           If None, uses DEFAULT_ALLOWED_MODULES.
        """
        self.format = format
        self.use_builtins = use_builtins
        self.allowed_modules = allowed_modules or DEFAULT_ALLOWED_MODULES.copy()

        if format == "msgpack":
            self._encode = msgpack.encode
            self._decode = msgpack.decode
        else:
            self._encode = json.encode
            self._decode = json.decode

    def serialize(self, obj: Any) -> bytes:
        """Serialize object to bytes.

        Args:
            obj: Object to serialize

        Returns:
            Serialized bytes
        """
        if self.use_builtins:
            # Convert Persistent objects to dict for serialization
            if isinstance(obj, Persistent):
                obj = {
                    "__class__": obj.__class__.__module__
                    + "."
                    + obj.__class__.__name__,
                    "__state__": obj.__getstate__(),
                }
            # Convert to built-in types recursively
            obj = to_builtins(obj, str_keys=True)

        return self._encode(obj)

    def deserialize(self, data: bytes, max_size: int = DEFAULT_MAX_SIZE) -> Any:
        """Deserialize bytes to object.

        Args:
            data: Serialized bytes
            max_size: Maximum allowed size (default: 100MB)

        Returns:
            Deserialized object

        Raises:
            ValueError: If data exceeds max_size
        """
        if len(data) > max_size:
            raise ValueError(f"Data too large: {len(data)} > {max_size}")

        obj = self._decode(data)

        # Handle Persistent objects serialized with __class__ field
        if isinstance(obj, dict) and "__class__" in obj and "__state__" in obj:
            # Reconstruct Persistent object
            module_class = obj["__class__"]
            parts = module_class.rsplit(".", 1)
            if len(parts) == 2:
                module, classname = parts

                # SECURITY: Validate module against whitelist before importing
                if module not in self.allowed_modules:
                    logger.error(
                        f"Blocked deserialization of disallowed module: {module}"
                    )
                    raise ValueError(
                        f"Deserialization of module '{module}' is not allowed. "
                        f"Module not in whitelist. This prevents arbitrary code execution."
                    )

                # Import the class (now safe due to whitelist check)
                try:
                    mod = __import__(module, fromlist=[classname])
                    klass = getattr(mod, classname)
                except (ImportError, AttributeError) as e:
                    logger.error(f"Failed to import {module}.{classname}: {e}")
                    raise ValueError(
                        f"Failed to import class '{module}.{classname}': {e}"
                    ) from e

                # Additional safety: ensure it's actually a Persistent subclass
                if not isinstance(klass, type) or not issubclass(klass, Persistent):
                    logger.error(
                        f"Class {module}.{classname} is not a Persistent subclass"
                    )
                    raise ValueError(
                        f"Class '{module}.{classname}' is not a Persistent subclass"
                    )

                # Create instance using PersistentBase.__new__ which properly initializes
                instance = klass.__new__(klass)
                # Directly set __dict__ without triggering change tracking
                _setattribute(instance, "__dict__", obj["__state__"])
                return instance

        return obj

    def get_state(self, obj: Persistent) -> dict:
        """Extract serializable state from object.

        Args:
            obj: Persistent object to extract state from

        Returns:
            Dictionary representing object state
        """
        state = obj.__getstate__()

        if self.use_builtins:
            # Convert to built-in types recursively
            return to_builtins(state, str_keys=True)

        return state
