"""Serializer for Durus with backward-compatible class names.

This module re-exports a msgspec-backed serializer under the historical
``DillSerializer`` name. The class preserves the public API of the
original dill-based implementation (constructor signature, ``serialize``,
``deserialize``, ``get_state``), but the wire format is now msgpack (via
``MsgspecSerializer``), which removes the CWE-502 deserialization risk
flagged by semgrep.

The ``dill`` import is retained at module top so ``DILL_AVAILABLE`` and
``DummyDill`` keep working for any code that imports them, but the
class itself no longer requires dill at runtime.
"""

from typing import Any

from dhara.serialize.base import DEFAULT_MAX_SIZE, Serializer
from dhara.serialize.msgspec import MsgspecSerializer

try:
    import dill  # pyright: ignore[reportUnusedImport]

    DILL_AVAILABLE = True  # type: ignore[no-redef]
except ImportError:
    DILL_AVAILABLE = False  # type: ignore[no-redef]

    # Create a dummy dill module for type hints
    class DummyDill:
        DEFAULT_PROTOCOL = 2

        def dumps(self, obj: object, protocol: int | None = None) -> bytes:
            raise ImportError(
                "dill is not installed. Install it with: pip install dill"
            )

        def loads(self, data: bytes) -> object:
            raise ImportError(
                "dill is not installed. Install it with: pip install dill"
            )

    dill = DummyDill()  # type: ignore


class DillSerializer(Serializer):
    """Backwards-compatible wrapper around MsgspecSerializer.

    Retains the ``DillSerializer`` name and ``(protocol=)`` constructor
    signature for API compatibility with the historical dill-based
    implementation, but the underlying format is msgpack. Use
    ``MsgspecSerializer`` directly in new code.

    The ``protocol`` argument is accepted for signature compatibility only
    and has no effect on the wire format. The ``dill`` package is no
    longer required to instantiate this class. Note: dill-specific
    capabilities (lambdas, nested functions) are not supported.
    """

    def __init__(self, protocol: int | None = None):
        """Initialize serializer.

        Args:
            protocol: Accepted for backward compatibility; ignored.
        """
        self.protocol = protocol if protocol is not None else 0
        self._msgspec = MsgspecSerializer(format="msgpack", use_builtins=True)

    def serialize(self, obj: Any) -> bytes:
        """Serialize object to bytes (msgpack format via MsgspecSerializer).

        Args:
            obj: Object to serialize

        Returns:
            Serialized bytes
        """
        return self._msgspec.serialize(obj)

    def deserialize(self, data: bytes, max_size: int = DEFAULT_MAX_SIZE) -> Any:
        """Deserialize bytes to object.

        Safe against untrusted data: uses MsgspecSerializer under the hood,
        which has no arbitrary-code-execution surface (no dill).

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
        return self._msgspec.deserialize(data, max_size=max_size)

    def get_state(self, obj: Any) -> dict[str, Any]:
        """Extract serializable state from object.

        Args:
            obj: Object to extract state from

        Returns:
            Dictionary representing object state
        """
        # Try __getstate__ method first
        if hasattr(obj, "__getstate__"):
            state: dict[str, Any] | None = obj.__getstate__()
            if isinstance(state, dict):
                return state

        # Fall back to __dict__ if available
        if hasattr(obj, "__dict__"):
            return dict(obj.__dict__)

        # Last resort: return empty dict
        return {}
