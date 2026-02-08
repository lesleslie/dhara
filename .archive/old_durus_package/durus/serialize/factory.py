"""Factory for creating serializers.

Allows easy instantiation of different serializer backends with
proper error handling and validation.
"""

from dhruva.serialize.base import Serializer
from dhruva.serialize.pickle import PickleSerializer
from dhruva.serialize.msgspec import MsgspecSerializer
from dhruva.serialize.dill import DillSerializer
from typing import Literal, Any


def create_serializer(
    backend: Literal["pickle", "msgspec", "dill"] = "pickle",
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

    Examples:
        >>> # Create default pickle serializer
        >>> ser = create_serializer("pickle")
        >>>
        >>> # Create msgspec serializer with JSON format
        >>> ser = create_serializer("msgspec", format="json", use_builtins=True)
        >>>
        >>> # Create dill serializer with protocol 4
        >>> ser = create_serializer("dill", protocol=4)

    Backend-specific arguments:

        pickle:
            protocol (int): Pickle protocol version (default: 2)
            WARNING: Pickle can execute arbitrary code - use with caution

        msgspec:
            format (str): "msgpack" or "json" (default: "msgpack")
            use_builtins (bool): Convert to built-in types (default: True)

        dill:
            protocol (int): Pickle protocol version (default: dill.DEFAULT_PROTOCOL)
            WARNING: dill can execute arbitrary code - use with caution
    """
    serializers: dict[str, type[Serializer]] = {
        "pickle": PickleSerializer,
        "msgspec": MsgspecSerializer,
        "dill": DillSerializer,
    }

    serializer_class = serializers.get(backend)
    if serializer_class is None:
        raise ValueError(
            f"Unknown serializer: {backend}. "
            f"Choose from: {', '.join(serializers.keys())}"
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
