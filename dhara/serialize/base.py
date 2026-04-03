"""Base serializer interface for Durus.

Provides abstract interface for all serializer implementations.
"""

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

DEFAULT_MAX_SIZE = 100 * 1024 * 1024  # 100MB

__all__ = ["Serializer", "SerializerProtocol", "DEFAULT_MAX_SIZE"]


class Serializer(ABC):
    """Abstract serializer interface.

    All Durus serializers must implement this interface.

    This is defined as an ABC for backwards compatibility.
    For structural typing, use SerializerProtocol instead.
    """

    @abstractmethod
    def serialize(self, obj: Any) -> bytes:
        """Serialize object to bytes.

        Args:
            obj: Object to serialize

        Returns:
            Serialized bytes
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    def get_state(self, obj: Any) -> dict:
        """Extract serializable state from object.

        Args:
            obj: Object to extract state from

        Returns:
            Dictionary representing object state
        """
        pass


@runtime_checkable
class SerializerProtocol(Protocol):
    """Protocol-based serializer interface for structural typing.

    This allows any object with the correct methods to be used as a serializer,
    without needing to inherit from Serializer ABC.

    Example:
        class MySerializer:
            def serialize(self, obj: Any) -> bytes: ...
            def deserialize(self, data: bytes, max_size: int = DEFAULT_MAX_SIZE) -> Any: ...
            def get_state(self, obj: Any) -> dict: ...

        # This will pass type checking
        def use_serializer(serializer: SerializerProtocol):
            ...
    """

    def serialize(self, obj: Any) -> bytes:
        """Serialize object to bytes."""
        ...

    def deserialize(self, data: bytes, max_size: int = DEFAULT_MAX_SIZE) -> Any:
        """Deserialize bytes to object."""
        ...

    def get_state(self, obj: Any) -> dict:
        """Extract serializable state from object."""
        ...
