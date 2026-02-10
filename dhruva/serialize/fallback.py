"""Whitelist-based fallback serializer with automatic serialization method selection.

This serializer provides a safe fallback mechanism:
1. Try msgspec first (fast, safe)
2. If msgspec fails, check if type is whitelisted for pickle/dill
3. Store which serializer was used for safe deserialization
4. Never auto-detect on deserialization (prevents RCE vulnerabilities)

Security Model:
- msgspec is tried first (safe, fast)
- Pickle/dill fallback only for whitelisted types
- Deserialization uses stored method (no detection/guessing)
- Clear audit log of fallback usage
"""

import logging
import warnings
from typing import Any

from dhruva.serialize.base import DEFAULT_MAX_SIZE, Serializer
from dhruva.serialize.dill import DillSerializer
from dhruva.serialize.msgspec import MsgspecSerializer
from dhruva.serialize.pickle import PickleSerializer

logger = logging.getLogger(__name__)

# Serializer IDs for record format
SERIALIZER_MSGSPEC = 0
SERIALIZER_PICKLE = 1
SERIALIZER_DILL = 2

# Default whitelist of types allowed to use pickle/dill
# These are commonly used types that msgspec cannot serialize
DEFAULT_PICKLE_WHITELIST: set[str] = {
    # NumPy types (need pickle or custom encoder)
    "numpy.ndarray",
    "numpy.matrix",
    "numpy.dtype",
    "numpy.generic",
    # Pandas types
    "pandas.DataFrame",
    "pandas.Series",
    "pandas.Timestamp",
    "pandas.Timedelta",
    "pandas.Interval",
    "pandas.Period",
    "pandas.Categorical",
    # SciPy sparse matrices
    "scipy.sparse.csr_matrix",
    "scipy.sparse.csc_matrix",
    "scipy.sparse.coo_matrix",
    "scipy.sparse.bsr_matrix",
    "scipy.sparse.lil_matrix",
    "scipy.sparse.dok_matrix",
    "scipy.sparse.dia_matrix",
    # PIL/Pillow images
    "PIL.Image.Image",
    "PIL.Image.ImageFile",
    # DateTime extensions
    "dateutil.parser._parserparser",
    "dateutil.relativedelta.relativedelta",
    # Common data science types
    "matplotlib.figure.Figure",
    "matplotlib.axes.Axes",
    # Add more types as needed for your use case
}


class FallbackSerializer(Serializer):
    """Whitelist-based fallback serializer.

    Tries msgspec first for all objects. If msgspec fails and the object
    type is whitelisted, falls back to pickle. If also whitelisted for dill
    (more capable), can use dill as final fallback.

    Security:
    - msgspec is tried first (safe, no code execution)
    - Pickle/dill only for whitelisted types (audit trail)
    - Deserialization uses stored method (no auto-detect)
    - Clear warnings when fallback occurs

    Example:
        >>> serializer = FallbackSerializer()
        >>> # Regular Python objects use msgspec
        >>> data = serializer.serialize({"key": "value"})
        >>> # NumPy array falls back to pickle (if whitelisted)
        >>> import numpy as np
        >>> arr = serializer.serialize(np.array([1, 2, 3]))
        >>> # Deserialization uses correct method automatically
        >>> obj = serializer.deserialize(data)
    """

    def __init__(
        self,
        pickle_whitelist: set[str] | None = None,
        allow_dill: bool = False,
        msgspec_kwargs: dict | None = None,
        pickle_kwargs: dict | None = None,
        dill_kwargs: dict | None = None,
    ):
        """Initialize fallback serializer.

        Args:
            pickle_whitelist: Set of type names allowed to use pickle.
                             If None, uses DEFAULT_PICKLE_WHITELIST.
            allow_dill: Allow dill as final fallback (more capable, less safe).
                       Only use if you need to serialize lambdas/functions.
            msgspec_kwargs: Arguments to pass to MsgspecSerializer.
            pickle_kwargs: Arguments to pass to PickleSerializer.
            dill_kwargs: Arguments to pass to DillSerializer.

        Security Note:
            Be conservative with the whitelist. Only add types that you
            trust and cannot be made msgspec-compatible. Each type in the
            whitelist is a potential attack vector if pickle data is tainted.
        """
        self.pickle_whitelist = pickle_whitelist or DEFAULT_PICKLE_WHITELIST.copy()
        self.allow_dill = allow_dill

        # Initialize underlying serializers
        msgspec_kwargs = msgspec_kwargs or {}
        pickle_kwargs = pickle_kwargs or {}
        dill_kwargs = dill_kwargs or {}

        self._msgspec = MsgspecSerializer(**msgspec_kwargs)
        self._pickle = PickleSerializer(**pickle_kwargs)
        self._dill = DillSerializer(**dill_kwargs) if allow_dill else None

        # Statistics for monitoring
        self._stats = {
            "msgspec_count": 0,
            "pickle_fallback_count": 0,
            "dill_fallback_count": 0,
            "failed_count": 0,
        }

    def serialize(self, obj: Any) -> bytes:
        """Serialize object, trying msgspec first, then whitelist-based fallback.

        Args:
            obj: Object to serialize

        Returns:
            Serialized bytes with serializer prefix

        Raises:
            TypeError: If object cannot be serialized by any method
            ValueError: If type is not in pickle whitelist and msgspec fails
        """
        # Try msgspec first (fast, safe)
        try:
            data = self._msgspec.serialize(obj)
            self._stats["msgspec_count"] += 1
            return bytes([SERIALIZER_MSGSPEC]) + data
        except (TypeError, AttributeError, ValueError) as e:
            # msgspec failed, check whitelist for fallback
            type_name = self._get_type_name(obj)

            if type_name in self.pickle_whitelist:
                # Whitelisted for pickle
                warnings.warn(
                    f"Falling back to pickle for whitelisted type: {type_name}. "
                    f"This is slower and less safe than msgspec. "
                    f"Consider adding a msgspec encoder for this type.",
                    UserWarning,
                    stacklevel=2,
                )

                try:
                    data = self._pickle.serialize(obj)
                    self._stats["pickle_fallback_count"] += 1
                    logger.info(
                        f"Serialized {type_name} using pickle (whitelisted fallback)"
                    )
                    return bytes([SERIALIZER_PICKLE]) + data
                except Exception as pickle_error:
                    # Pickle also failed, try dill if allowed
                    if self._dill is not None:
                        warnings.warn(
                            f"Pickle failed for {type_name}, trying dill. "
                            f"Dill can execute arbitrary code - ensure data is trusted.",
                            UserWarning,
                            stacklevel=2,
                        )

                        try:
                            data = self._dill.serialize(obj)
                            self._stats["dill_fallback_count"] += 1
                            logger.warning(
                                f"Serialized {type_name} using dill (last resort)"
                            )
                            return bytes([SERIALIZER_DILL]) + data
                        except Exception as dill_error:
                            self._stats["failed_count"] += 1
                            raise TypeError(
                                f"Failed to serialize {type_name} with msgspec, pickle, or dill. "
                                f"msgspec: {e}, pickle: {pickle_error}, dill: {dill_error}"
                            ) from dill_error
                    else:
                        self._stats["failed_count"] += 1
                        raise TypeError(
                            f"Failed to serialize {type_name} with msgspec or pickle. "
                            f"msgspec: {e}, pickle: {pickle_error}"
                        ) from pickle_error

            # Type not in whitelist
            self._stats["failed_count"] += 1
            raise ValueError(
                f"Cannot serialize {type_name} with msgspec. "
                f"Type is not in pickle whitelist. "
                f"Either:\\n"
                f"  1. Add a custom msgspec encoder for this type\\n"
                f"  2. Add '{type_name}' to pickle_whitelist if you trust this type\\n"
                f"  3. Enable dill with allow_dill=True (less safe)\\n"
                f"Original error: {e}"
            ) from e

    def deserialize(self, data: bytes, max_size: int = DEFAULT_MAX_SIZE) -> Any:
        """Deserialize bytes using stored serializer method.

        CRITICAL: This does NOT auto-detect the serialization method.
        It reads the serializer ID from the first byte of the record.
        This prevents attackers from specifying which serializer to use.

        Args:
            data: Serialized bytes with serializer prefix
            max_size: Maximum allowed size (default: 100MB)

        Returns:
            Deserialized object

        Raises:
            ValueError: If serializer ID is invalid or data exceeds max_size
        """
        if len(data) == 0:
            raise ValueError("Cannot deserialize empty data")

        # Read serializer ID from first byte
        serializer_id = data[0]
        payload = data[1:]

        # Check max_size
        if len(payload) > max_size:
            raise ValueError(
                f"Data too large: {len(payload)} > {max_size}. "
                f"This may be a denial of service attempt."
            )

        # Dispatch to correct serializer
        if serializer_id == SERIALIZER_MSGSPEC:
            return self._msgspec.deserialize(payload, max_size)
        elif serializer_id == SERIALIZER_PICKLE:
            logger.debug("Deserializing pickle data (whitelisted type)")
            return self._pickle.deserialize(payload, max_size)
        elif serializer_id == SERIALIZER_DILL:
            logger.warning("Deserializing dill data (ensure data is trusted!)")
            return self._dill.deserialize(payload, max_size)
        else:
            raise ValueError(
                f"Invalid serializer ID: {serializer_id}. "
                f"This may indicate data corruption or an attack attempt."
            )

    def get_state(self, obj: Any) -> dict:
        """Extract serializable state from object.

        Args:
            obj: Object to extract state from

        Returns:
            Dictionary representing object state
        """
        # Try msgspec first
        try:
            return self._msgspec.get_state(obj)
        except Exception:
            # Fallback to pickle if whitelisted
            type_name = self._get_type_name(obj)
            if type_name in self.pickle_whitelist:
                return self._pickle.get_state(obj)
            else:
                raise ValueError(
                    f"Cannot extract state from {type_name}. "
                    f"Type not in msgspec compatibility list and not whitelisted for pickle."
                )

    def _get_type_name(self, obj: Any) -> str:
        """Get full type name for whitelist checking.

        Args:
            obj: Object to get type name from

        Returns:
            Full type name (e.g., "numpy.ndarray")
        """
        type_name = f"{obj.__class__.__module__}.{obj.__class__.__name__}"
        return type_name

    def get_stats(self) -> dict:
        """Get serialization statistics.

        Useful for monitoring and optimization:
        - High pickle_fallback_count: Consider adding msgspec encoders
        - High dill_fallback_count: Review what types need dill
        - failed_count: Types that need attention

        Returns:
            Dictionary with serialization counts
        """
        return self._stats.copy()

    def add_to_whitelist(self, type_name: str) -> None:
        """Add a type to the pickle whitelist.

        Use this cautiously. Only add types that:
        1. Cannot be made msgspec-compatible
        2. Come from trusted sources
        3. You've reviewed for security issues

        Args:
            type_name: Full type name (e.g., "numpy.ndarray")
        """
        warnings.warn(
            f"Adding {type_name} to pickle whitelist. "
            f"This allows pickle serialization for this type. "
            f"Ensure you understand the security implications.",
            UserWarning,
            stacklevel=2,
        )
        self.pickle_whitelist.add(type_name)
        logger.info(f"Added {type_name} to pickle whitelist")

    def remove_from_whitelist(self, type_name: str) -> None:
        """Remove a type from the pickle whitelist.

        Args:
            type_name: Full type name to remove
        """
        if type_name in self.pickle_whitelist:
            self.pickle_whitelist.remove(type_name)
            logger.info(f"Removed {type_name} from pickle whitelist")
        else:
            logger.warning(f"Type {type_name} not in whitelist")
