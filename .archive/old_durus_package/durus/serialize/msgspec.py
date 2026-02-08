"""msgspec-based serializer for Durus.

msgspec is a fast and safe serialization library that supports:
- MessagePack format (binary, compact)
- JSON format (text, interoperable)
- Very fast (faster than pickle)
- Safer (no arbitrary code execution)
"""

from msgspec import msgpack, json, to_builtins
from dhruva.serialize.base import Serializer, DEFAULT_MAX_SIZE
from typing import Any, Literal
from dhruva.core.persistent import Persistent, _getattribute, _setattribute


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
    ):
        """Initialize msgspec serializer.

        Args:
            format: Serialization format (msgpack or json)
            use_builtins: Convert to built-in types for compatibility
        """
        self.format = format
        self.use_builtins = use_builtins

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
                    "__class__": obj.__class__.__module__ + "." + obj.__class__.__name__,
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
                # Import the class
                mod = __import__(module, fromlist=[classname])
                klass = getattr(mod, classname)
                # Create instance using PersistentBase.__new__ which properly initializes
                instance = klass.__new__(klass)
                # Directly set __dict__ without triggering change tracking
                _setattribute(instance, '__dict__', obj["__state__"])
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
