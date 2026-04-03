"""Pickle-based serializer for Durus.

Provides backward compatibility with existing Durus databases.

SECURITY WARNING: Pickle can execute arbitrary code when deserializing
untrusted data. Only use for trusted data or migration purposes.
For new databases, use MsgspecSerializer instead.
"""

import pickle
from typing import Any

from dhara.serialize.base import DEFAULT_MAX_SIZE, Serializer


class PickleSerializer(Serializer):
    """Pickle-based serializer.

    WARNING: Pickle can execute arbitrary code when deserializing untrusted data.
    Only use for trusted data or migration purposes.
    For new databases, use MsgspecSerializer instead.

    Retained for:
    - Backward compatibility with Durus 4.x databases
    - Migration from pickle to msgspec
    - Handling objects that msgspec cannot serialize
    """

    def __init__(self, protocol: int = 2):
        """Initialize pickle serializer.

        Args:
            protocol: Pickle protocol version (2 is Durus 4.x default)
                Use protocol 4-5 for better performance with new Python
        """
        self.protocol = protocol

    def serialize(self, obj: Any) -> bytes:
        """Serialize object to bytes.

        Args:
            obj: Object to serialize

        Returns:
            Serialized bytes (pickle format)
        """
        return pickle.dumps(obj, protocol=self.protocol)

    def deserialize(self, data: bytes, max_size: int = DEFAULT_MAX_SIZE) -> Any:
        """Deserialize bytes to object.

        WARNING: Only deserialize trusted data!

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
        return pickle.loads(data)

    def get_state(self, obj: Any) -> dict:
        """Extract serializable state from object.

        Args:
            obj: Object to extract state from

        Returns:
            Dictionary representing object state
        """
        # Try __getstate__ method first
        if hasattr(obj, "__getstate__"):
            state = obj.__getstate__()
            if isinstance(state, dict):
                return state

        # Fall back to __dict__ if available
        if hasattr(obj, "__dict__"):
            return obj.__dict__

        # Last resort: return empty dict
        return {}
