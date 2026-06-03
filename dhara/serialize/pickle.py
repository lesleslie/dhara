"""Serializer for Durus with backward-compatible class names.

This module re-exports a msgspec-backed serializer under the historical
``PickleSerializer`` name. The class preserves the public API of the
original pickle-based implementation (constructor signature, ``serialize``,
``deserialize``, ``get_state``) so existing call sites, factory dispatch,
and tests continue to work, but the wire format is now msgpack (via
``MsgspecSerializer``), which removes the CWE-502 deserialization risk
flagged by semgrep.

NOTE: Durus 4.x pickle-format databases are not compatible with this
implementation. This is an intentional trade-off — the security win of
removing the pickle sink takes priority over format migration support.
"""

from typing import Any

from dhara.serialize.base import DEFAULT_MAX_SIZE, Serializer
from dhara.serialize.msgspec import MsgspecSerializer


class PickleSerializer(Serializer):
    """Backwards-compatible wrapper around MsgspecSerializer.

    Retains the ``PickleSerializer`` name and ``(protocol=)`` constructor
    signature for API compatibility with the historical pickle-based
    implementation, but the underlying format is msgpack. Use
    ``MsgspecSerializer`` directly in new code.

    The ``protocol`` argument is accepted for signature compatibility only
    and has no effect on the wire format.
    """

    def __init__(self, protocol: int = 2):
        """Initialize serializer.

        Args:
            protocol: Accepted for backward compatibility; ignored.
        """
        self.protocol = protocol
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
        which has no arbitrary-code-execution surface (no pickle).

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
