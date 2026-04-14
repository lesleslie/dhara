"""Factory for creating serializers.

Allows easy instantiation of different serializer backends with
proper error handling and validation.
"""

from typing import Any, Literal

from dhara.serialize.base import Serializer


def create_serializer(
    backend: Literal["pickle", "msgspec", "dill", "fallback"] = "msgspec",
    **kwargs: Any,
) -> Serializer:
    """Create a serializer instance.

    Args:
        backend: Serializer backend to use
        **kwargs: Backend-specific arguments

    Returns:
        Serializer instance

    Raises:
        ValueError: If backend is unknown
        ImportError: If backend requires optional dependencies
    """
    if backend == "pickle":
        from dhara.serialize.pickle import PickleSerializer

        serializer_class: type[Serializer] = PickleSerializer
    elif backend == "msgspec":
        from dhara.serialize.msgspec import MsgspecSerializer

        serializer_class = MsgspecSerializer
    elif backend == "dill":
        from dhara.serialize.dill import DillSerializer

        serializer_class = DillSerializer
    elif backend == "fallback":
        from dhara.serialize.fallback import FallbackSerializer

        serializer_class = FallbackSerializer
    else:
        raise ValueError(
            f"Unknown serializer: {backend}. "
            "Choose from: pickle, msgspec, dill, fallback"
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
