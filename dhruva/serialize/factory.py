"""Factory for creating serializers.

Allows easy instantiation of different serializer backends with
proper error handling and validation.
"""

from typing import Any, Literal

from dhruva.serialize.base import Serializer
from dhruva.serialize.dill import DillSerializer
from dhruva.serialize.msgspec import MsgspecSerializer
from dhruva.serialize.pickle import PickleSerializer


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

    Examples:
        >>> # Create default msgspec serializer (safe, fast)
        >>> ser = create_serializer()  # Uses msgspec by default
        >>>
        >>> # Create msgspec serializer with JSON format
        >>> ser = create_serializer("msgspec", format="json", use_builtins=True)
        >>>
        >>> # Create fallback serializer with whitelist
        >>> ser = create_serializer("fallback", pickle_whitelist={"numpy.ndarray"})
        >>>
        >>> # Create pickle serializer (WARNING: use only with trusted data)
        >>> ser = create_serializer("pickle", protocol=2)
        >>>
        >>> # Create dill serializer (WARNING: use only with trusted data)
        >>> ser = create_serializer("dill", protocol=4)

    Backend-specific arguments:

        msgspec (default, safe):
            format (str): "msgpack" or "json" (default: "msgpack")
            use_builtins (bool): Convert to built-in types (default: True)
            RECOMMENDED: Safe for untrusted data, fast, and type-safe

        fallback (safe with whitelist):
            pickle_whitelist (set): Types allowed to use pickle (e.g., {"numpy.ndarray"})
            allow_dill (bool): Allow dill as final fallback (default: False)
            msgspec_kwargs (dict): Arguments for msgspec serializer
            pickle_kwargs (dict): Arguments for pickle serializer
            dill_kwargs (dict): Arguments for dill serializer
            ⚠️ SECURITY: Only pickle/dill whitelisted types. Safe fallback.

        pickle (unsafe):
            protocol (int): Pickle protocol version (default: 2)
            ⚠️ SECURITY WARNING: Pickle can execute arbitrary code
            Only use with trusted data. Use msgspec for untrusted data.

        dill (unsafe):
            protocol (int): Pickle protocol version (default: dill.DEFAULT_PROTOCOL)
            ⚠️ SECURITY WARNING: dill can execute arbitrary code
            Only use with trusted data. Use msgspec for untrusted data.
    """
    from dhruva.serialize.fallback import FallbackSerializer

    serializers: dict[str, type[Serializer]] = {
        "pickle": PickleSerializer,
        "msgspec": MsgspecSerializer,
        "dill": DillSerializer,
        "fallback": FallbackSerializer,
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
