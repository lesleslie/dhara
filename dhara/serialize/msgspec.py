"""msgspec-based serializer for Dhara.

from __future__ import annotations
msgspec is a fast and safe serialization library that supports:
- MessagePack format (binary, compact)
- JSON format (text, interoperable)
- Very fast (faster than pickle)
- Safer (no arbitrary code execution)
"""

import logging
from typing import Any, Literal, cast

from msgspec import json as msgspec_json
from msgspec import msgpack as msgspec_msgpack
from msgspec import to_builtins

from dhara.core.persistent import Persistent, PersistentObject, _setattribute
from dhara.serialize.base import DEFAULT_MAX_SIZE, Serializer

logger = logging.getLogger(__name__)

# Default whitelist of safe modules for class deserialization
# This prevents arbitrary code execution via __import__
DEFAULT_ALLOWED_MODULES: set[str] = {
    # dhara core modules
    "dhara",
    "dhara.collections",
    "dhara.collections.dict",
    "dhara.collections.list",
    "dhara.collections.set",
    "dhara.collections.btree",
    "dhara.core",
    "dhara.core.persistent",
    "dhara.core.connection",
    # Standard library collections (safe)
    "collections",
    "collections.abc",
    # Built-in types (no module needed)
    "__builtin__",
    "builtins",
}


def _persistent_enc_hook(obj: Any) -> Any:
    """msgspec ``enc_hook``: convert any ``Persistent`` instance to its wire-format dict.

    msgspec calls this whenever ``to_builtins`` recursion encounters a type
    it does not natively support. Returning the standard
    ``{"__class__", "__state__"}`` dict lets PersistentDict, PersistentList,
    PersistentSet, and any future Persistent subclass be encoded
    transparently at any depth in the object graph.

    This is the single source of truth for the wire format on the encode
    side; the inverse path lives in :meth:`MsgspecSerializer.deserialize`
    and :func:`dhara.serialize.record.deserialize_state`.

    Uses ``__name__`` (not ``__qualname__``) to match the existing wire
    format produced at ``record.py:99`` and preserve backward compatibility
    with previously written storage records.

    Args:
        obj: A non-builtin object encountered during ``to_builtins`` recursion.

    Returns:
        A dict ``{"__class__": "module.ClassName", "__state__": obj.__getstate__()}``
        if ``obj`` is a :class:`Persistent` instance.

    Raises:
        NotImplementedError: If ``obj`` is not a Persistent instance. msgspec
            re-raises this with the standard "Encoding objects of type X is
            unsupported" message, which is the desired behavior for genuinely
            unsupported types.
    """
    if isinstance(obj, PersistentObject):
        klass = type(obj)
        state = obj.__getstate__()
        # Normalize ``__state__`` from ``None`` to ``{}`` so the wire
        # format is uniform regardless of the source's ``__getstate__``
        # return value. Mirrors :func:`dhara.serialize.record.deserialize_state`
        # which performs the same coercion on the inverse path.
        if state is None:
            state = {}
        return {
            "__class__": f"{klass.__module__}.{klass.__name__}",
            "__state__": state,
        }
    raise NotImplementedError(f"Cannot encode object of type {type(obj).__name__}")


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
        # Default: a copy of the safe whitelist. Per-instance copies
        # prevent one serializer's mutation from leaking to siblings
        # (the "is_copy_not_reference" test enforces this). The
        # internal record layer (dhara.serialize.record) does not need
        # a permissive mode because it only calls ``decode_raw`` and
        # ``serialize`` on its private ``_DEFAULT_MSGSPEC`` — both of
        # which bypass the whitelist (decode_raw does no class
        # reconstruction; serialize only outputs bytes).
        if allowed_modules is None:
            self.allowed_modules = DEFAULT_ALLOWED_MODULES.copy()
        else:
            self.allowed_modules = set(allowed_modules)

        if format == "msgpack":
            self._encode = msgspec_msgpack.encode  # type: ignore[assignment]
            self._decode = msgspec_msgpack.decode  # type: ignore[assignment]
        else:
            self._encode = msgspec_json.encode  # type: ignore[assignment]
            self._decode = msgspec_json.decode  # type: ignore[assignment]

    def serialize(self, obj: Any) -> bytes:
        """Serialize object to bytes.

        Persistent subclasses (PersistentDict, PersistentList, PersistentSet,
        user-defined subclasses) are encoded as
        ``{"__class__": "module.ClassName", "__state__": obj.__getstate__()}``
        at any depth in the object graph, via the msgspec ``enc_hook`` callback.

        Args:
            obj: Object to serialize

        Returns:
            Serialized bytes
        """
        if self.use_builtins:
            # _persistent_enc_hook handles Persistent instances at any
            # nesting depth (replaces the previous top-level isinstance guard,
            # which only fired for the outermost object and missed nested
            # Persistents in __getstate__() results).
            obj = to_builtins(obj, str_keys=True, enc_hook=_persistent_enc_hook)

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

                # SECURITY: Validate module against the instance whitelist
                # before importing. ``self.allowed_modules`` is always a
                # set (never ``None``) — the constructor default is
                # ``set(DEFAULT_ALLOWED_MODULES)`` — so every module is
                # checked against the safe whitelist.
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

                # Use ``klass.__new__`` (not ``object.__new__``) so that
                # ``PersistentBase.__new__`` runs and initializes the four
                # required slots (``_p_status``, ``_p_serial``,
                # ``_p_connection``, ``_p_oid``). Skipping ``__new__``
                # leaves those slots unset, which causes ``AttributeError``
                # on the first ``__getattribute__`` access (e.g. inside
                # the test's ``result.value`` lookup).
                instance = klass.__new__(klass)  # type: ignore[arg-type,call-arg]
                # Directly set __dict__ without triggering change tracking.
                # The state is normalized to ``{}`` to match the enc_hook
                # and ``deserialize_state`` conventions.
                state = obj["__state__"]
                if state is None:
                    state = {}
                _setattribute(instance, "__dict__", state)
                return instance

        return obj

    def decode_raw(self, data, max_size=DEFAULT_MAX_SIZE):
        """Decode bytes to a Python object without class reconstruction.

        Bypasses the Persistent-object reconstruction that ``deserialize``
        does as a side effect. Used by the internal record layer
        (``dhara.serialize.record``) to extract the
        ``{"__class__", "__state__"}`` dict without instantiating the
        class — class instantiation is the caller's responsibility
        (gated by the connection-level ``allowed_modules`` whitelist).
        """
        if len(data) > max_size:
            raise ValueError(f"Data too large: {len(data)} > {max_size}")
        return self._decode(data)

    def get_state(self, obj: Persistent) -> dict:
        """Extract serializable state from object.

        Args:
            obj: Persistent object to extract state from

        Returns:
            Dictionary representing object state
        """
        state = obj.__getstate__()

        if self.use_builtins:
            # Convert to built-in types recursively; the enc_hook handles
            # any nested Persistent instances in the state tree.
            return cast(
                dict, to_builtins(state, str_keys=True, enc_hook=_persistent_enc_hook)
            )

        return state
