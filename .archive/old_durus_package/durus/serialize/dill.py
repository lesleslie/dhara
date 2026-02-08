"""dill-based serializer for Durus.

dill can serialize more Python objects than pickle:
- Lambdas and nested functions
- Interactive interpreter objects
- More complex object graphs

SECURITY WARNING: Like pickle, dill can execute arbitrary code when
deserializing untrusted data. Only use with trusted data sources.
"""

from dhruva.serialize.base import Serializer, DEFAULT_MAX_SIZE
from typing import Any

try:
    import dill
    DILL_AVAILABLE = True
except ImportError:
    DILL_AVAILABLE = False
    # Create a dummy dill module for type hints
    class DummyDill:
        DEFAULT_PROTOCOL = 2

        def dumps(self, obj, protocol=None):
            raise ImportError(
                "dill is not installed. Install it with: pip install dill"
            )

        def loads(self, data):
            raise ImportError(
                "dill is not installed. Install it with: pip install dill"
            )

    dill = DummyDill()  # type: ignore


class DillSerializer(Serializer):
    """dill-based serializer.

    Advantages over pickle:
    - Can serialize lambdas and functions
    - Better support for interactive sessions
    - Handles more edge cases

    Trade-offs:
    - Slower than msgspec
    - Larger serialized size
    - Still has security concerns (unpickling untrusted data)
    - Optional dependency (must install dill separately)

    WARNING: Only deserialize trusted data! dill can execute arbitrary code.

    NOTE: dill must be installed to use this serializer:
        pip install dill
    """

    def __init__(self, protocol: int | None = None):
        """Initialize dill serializer.

        Args:
            protocol: Pickle protocol (uses dill default if None)

        Raises:
            ImportError: If dill is not installed
        """
        if not DILL_AVAILABLE:
            raise ImportError(
                "dill is required for DillSerializer. "
                "Install it with: pip install dill"
            )

        self.protocol = protocol or dill.DEFAULT_PROTOCOL

    def serialize(self, obj: Any) -> bytes:
        """Serialize object to bytes.

        Args:
            obj: Object to serialize

        Returns:
            Serialized bytes
        """
        return dill.dumps(obj, protocol=self.protocol)  # type: ignore

    def deserialize(self, data: bytes, max_size: int = DEFAULT_MAX_SIZE) -> Any:
        """Deserialize bytes to object.

        WARNING: Only deserialize trusted data! dill can execute
        arbitrary code when deserializing untrusted data.

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
        return dill.loads(data)  # type: ignore

    def get_state(self, obj: Any) -> dict:
        """Extract serializable state from object.

        Args:
            obj: Object to extract state from

        Returns:
            Dictionary representing object state
        """
        # Try __getstate__ method first
        if hasattr(obj, '__getstate__'):
            state = obj.__getstate__()
            if isinstance(state, dict):
                return state

        # Fall back to __dict__ if available
        if hasattr(obj, '__dict__'):
            return obj.__dict__

        # Last resort: return empty dict
        return {}
