"""Msgpack-backed serializer for Dhara.

This module provides :class:`MsgpackSerializer`, a thin wrapper around
:class:`~dhara.serialize.msgspec.MsgspecSerializer` that produces msgpack
output. The class is the historical replacement for ``PickleSerializer``
(which used to be pickle-based) — the wire format has been msgpack
since the CWE-502 migration.

Use :class:`~dhara.serialize.msgspec.MsgspecSerializer` directly in new
code; this alias exists for backward-compatible imports.
"""

from typing import Any

from dhara.serialize.base import DEFAULT_MAX_SIZE, Serializer
from dhara.serialize.msgspec import MsgspecSerializer


class MsgpackSerializer(Serializer):
    """Msgpack-backed serializer.

    Uses :class:`MsgspecSerializer` with ``format="msgpack"`` and
    ``use_builtins=True`` under the hood. Safe against untrusted data:
    no pickle, no arbitrary code execution on deserialize.
    """

    def __init__(self) -> None:
        """Initialize serializer. No arguments."""
        self._msgspec = MsgspecSerializer(format="msgpack", use_builtins=True)

    def serialize(self, obj: Any) -> bytes:
        """Serialize object to bytes (msgpack format)."""
        return self._msgspec.serialize(obj)

    def deserialize(self, data: bytes, max_size: int = DEFAULT_MAX_SIZE) -> Any:
        """Deserialize bytes to object.

        Safe against untrusted data (msgspec has no pickle-style surface).

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


__all__ = ["MsgpackSerializer"]
