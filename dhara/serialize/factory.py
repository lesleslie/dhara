"""Factory for creating serializers.

Allows easy instantiation of different serializer backends with
proper error handling and validation.
"""

from typing import Any, Literal

from dhara.serialize.base import Serializer


def create_serializer(
    backend: Literal["msgpack", "msgspec"] = "msgspec",
    **kwargs: Any,
) -> Serializer:
    """Create a serializer instance.

    Args:
        backend: Serializer backend to use. ``"msgpack"`` returns a
            :class:`~dhara.serialize.msgpack.MsgpackSerializer` (historical
            name; the wire format has been msgpack since the CWE-502
            migration). ``"msgspec"`` returns the lower-level
            :class:`~dhara.serialize.msgspec.MsgspecSerializer` directly.
        **kwargs: Backend-specific arguments

    Returns:
        Serializer instance

    Raises:
        ValueError: If backend is unknown
        ImportError: If backend requires optional dependencies
    """
    if backend == "msgpack":
        from dhara.serialize.msgpack import MsgpackSerializer

        serializer_class: type[Serializer] = MsgpackSerializer
    elif backend == "msgspec":
        from dhara.serialize.msgspec import MsgspecSerializer

        serializer_class = MsgspecSerializer
    else:
        raise ValueError(
            f"Unknown serializer: {backend}. "
            "Choose from: msgpack, msgspec"
        )

    try:
        return serializer_class(**kwargs)
    except ImportError as e:
        raise ImportError(
            f"Failed to create {backend} serializer: {e}. "
            f"Make sure required dependencies are installed."
        ) from e
    except TypeError as e:
        raise TypeError(
            f"Invalid arguments for {backend} serializer: {e}. "
            f"Check backend-specific arguments in docstring."
        ) from e
