"""Tests for whitelist-based fallback serializer.

Tests the FallbackSerializer which provides safe automatic method selection:
msgspec (safe) -> pickle (whitelisted) -> dill (last resort).

Note: The FallbackSerializer internally delegates to pickle/dill for
whitelisted types. These tests exercise the routing logic and security
boundaries, not the underlying serialization format.
"""

import warnings
from unittest.mock import patch

import pytest

from dhara.serialize.base import DEFAULT_MAX_SIZE
from dhara.serialize.fallback import (
    DEFAULT_PICKLE_WHITELIST,
    SERIALIZER_DILL,
    SERIALIZER_MSGSPEC,
    SERIALIZER_PICKLE,
    FallbackSerializer,
)


def _qualname(cls):
    """Get the module-qualified type name of a class."""
    return f"{cls.__module__}.{cls.__name__}"


# Module-level test classes needed for pickle roundtrip (pickle can't
# serialize classes defined inside test methods since it needs to find
# them via their module-qualified name).


class _TestObj:
    def __init__(self, value=42):
        self.value = value


class _WarnObj:
    pass


class _NotWhitelisted:
    pass


# ============================================================================
# Constructor
# ============================================================================


class TestFallbackConstructor:
    """Tests for FallbackSerializer initialization."""

    def test_default_whitelist(self):
        s = FallbackSerializer()
        assert "numpy.ndarray" in s.pickle_whitelist
        assert "pandas.DataFrame" in s.pickle_whitelist

    def test_custom_whitelist(self):
        custom = {"my.Type"}
        s = FallbackSerializer(pickle_whitelist=custom)
        assert s.pickle_whitelist == custom

    def test_default_allow_dill_false(self):
        s = FallbackSerializer()
        assert s.allow_dill is False

    def test_allow_dill_true(self):
        try:
            import dill  # noqa: F401
        except ImportError:
            pytest.skip("dill not installed")
        s = FallbackSerializer(allow_dill=True)
        assert s.allow_dill is True
        assert s._dill is not None

    def test_stats_initialized(self):
        s = FallbackSerializer()
        stats = s.get_stats()
        assert stats["msgspec_count"] == 0
        assert stats["pickle_fallback_count"] == 0
        assert stats["dill_fallback_count"] == 0
        assert stats["failed_count"] == 0

    def test_underlying_serializers_created(self):
        s = FallbackSerializer()
        assert s._msgspec is not None
        assert s._pickle is not None

    def test_whitelist_is_copy(self):
        """Modifying DEFAULT_PICKLE_WHITELIST should not affect new instances."""
        s1 = FallbackSerializer()
        s2 = FallbackSerializer()
        s1.pickle_whitelist.add("new.type")
        assert "new.type" not in s2.pickle_whitelist


# ============================================================================
# Msgspec path (happy path)
# ============================================================================


class TestFallbackMsgspecPath:
    """Tests for the normal msgspec serialization path."""

    def test_primitive_uses_msgspec(self):
        s = FallbackSerializer()
        data = s.serialize({"key": "value"})
        assert data[0] == SERIALIZER_MSGSPEC

    def test_roundtrip_primitive(self):
        s = FallbackSerializer()
        obj = {"int": 42, "str": "hello", "list": [1, 2, 3]}
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result == obj

    def test_msgspec_stats_incremented(self):
        s = FallbackSerializer()
        s.serialize({"key": "value"})
        stats = s.get_stats()
        assert stats["msgspec_count"] == 1
        assert stats["pickle_fallback_count"] == 0

    @pytest.mark.parametrize(
        "obj",
        [None, True, False, 42, 3.14, "text", [], [1, 2], {}, {"a": "b"}],
    )
    def test_various_types_use_msgspec(self, obj):
        s = FallbackSerializer()
        data = s.serialize(obj)
        assert data[0] == SERIALIZER_MSGSPEC
        result = s.deserialize(data)
        assert result == obj


# ============================================================================
# Pickle fallback path
# ============================================================================


class TestFallbackPicklePath:
    """Tests for the pickle fallback when msgspec fails."""

    def test_whitelisted_type_uses_pickle_prefix(self):
        """Objects that fail msgspec and are whitelisted use pickle."""
        s = FallbackSerializer(pickle_whitelist={_qualname(_TestObj)})
        obj = _TestObj()
        data = s.serialize(obj)
        assert data[0] == SERIALIZER_PICKLE

    def test_whitelisted_type_roundtrip(self):
        s = FallbackSerializer(pickle_whitelist={_qualname(_TestObj)})
        obj = _TestObj()
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result.value == 42

    def test_pickle_stats_incremented(self):
        s = FallbackSerializer(pickle_whitelist={_qualname(_TestObj)})
        s.serialize(_TestObj())
        stats = s.get_stats()
        assert stats["pickle_fallback_count"] == 1

    def test_pickle_fallback_emits_warning(self):
        s = FallbackSerializer(pickle_whitelist={_qualname(_WarnObj)})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            s.serialize(_WarnObj())
            assert any("pickle" in str(warning.message).lower() for warning in w)


# ============================================================================
# Rejection of non-whitelisted types
# ============================================================================


class TestFallbackRejection:
    """Tests for rejection of non-whitelisted types."""

    def test_non_whitelisted_type_raises_value_error(self):
        s = FallbackSerializer(pickle_whitelist=set())
        with pytest.raises(ValueError, match="not in pickle whitelist"):
            s.serialize(_NotWhitelisted())

    def test_failed_stats_incremented_on_rejection(self):
        s = FallbackSerializer(pickle_whitelist=set())
        try:
            s.serialize(_NotWhitelisted())
        except ValueError:
            pass

        stats = s.get_stats()
        assert stats["failed_count"] == 1


# ============================================================================
# Deserialization
# ============================================================================


class TestFallbackDeserialization:
    """Tests for deserialization with prefix byte dispatch."""

    def test_empty_data_raises_value_error(self):
        s = FallbackSerializer()
        with pytest.raises(ValueError, match="empty data"):
            s.deserialize(b"")

    def test_invalid_serializer_id_raises(self):
        s = FallbackSerializer()
        with pytest.raises(ValueError, match="Invalid serializer ID"):
            s.deserialize(bytes([99]))

    def test_max_size_enforced(self):
        s = FallbackSerializer()
        payload = b"x" * 1000
        data = bytes([SERIALIZER_MSGSPEC]) + payload
        with pytest.raises(ValueError, match="too large"):
            s.deserialize(data, max_size=10)

    def test_max_size_checks_payload_not_prefix(self):
        s = FallbackSerializer()
        obj = {"key": "value"}
        data = s.serialize(obj)
        result = s.deserialize(data, max_size=len(data))
        assert result == obj


# ============================================================================
# Whitelist management
# ============================================================================


class TestWhitelistManagement:
    """Tests for dynamic whitelist management."""

    def test_add_to_whitelist(self):
        s = FallbackSerializer()
        s.add_to_whitelist("custom.Type")
        assert "custom.Type" in s.pickle_whitelist

    def test_add_to_whitelist_emits_warning(self):
        s = FallbackSerializer()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            s.add_to_whitelist("custom.Type")
            assert any("whitelist" in str(warning.message).lower() for warning in w)

    def test_remove_from_whitelist(self):
        s = FallbackSerializer()
        s.pickle_whitelist.add("temp.Type")
        s.remove_from_whitelist("temp.Type")
        assert "temp.Type" not in s.pickle_whitelist

    def test_remove_nonexistent_warns(self):
        s = FallbackSerializer()
        # Should not raise, just log a warning
        s.remove_from_whitelist("nonexistent.Type")

    def test_remove_idempotent(self):
        s = FallbackSerializer()
        s.pickle_whitelist.add("temp.Type")
        s.remove_from_whitelist("temp.Type")
        s.remove_from_whitelist("temp.Type")  # second call is fine


# ============================================================================
# Stats
# ============================================================================


class TestFallbackStats:
    """Tests for serialization statistics."""

    def test_get_stats_returns_copy(self):
        s = FallbackSerializer()
        stats1 = s.get_stats()
        s.serialize({"test": True})
        stats2 = s.get_stats()
        assert stats1["msgspec_count"] == 0
        assert stats2["msgspec_count"] == 1

    def test_stats_accumulate(self):
        s = FallbackSerializer()
        for _ in range(5):
            s.serialize({"key": "value"})
        stats = s.get_stats()
        assert stats["msgspec_count"] == 5


# ============================================================================
# Dill path
# ============================================================================


class TestFallbackDillPath:
    """Tests for the dill fallback path."""

    def test_dill_serializer_created_when_allowed(self):
        try:
            import dill  # noqa: F401
        except ImportError:
            pytest.skip("dill not installed")
        s = FallbackSerializer(allow_dill=True)
        assert s._dill is not None

    def test_dill_serializer_none_when_disallowed(self):
        s = FallbackSerializer(allow_dill=False)
        assert s._dill is None


# ============================================================================
# _get_type_name
# ============================================================================


class TestGetType:
    """Tests for _get_type_name helper."""

    def test_type_name_format(self):
        s = FallbackSerializer()
        name = s._get_type_name(42)
        assert "int" in name
        assert "builtins" in name

    def test_custom_type_name(self):
        s = FallbackSerializer()

        class MyType:
            pass

        name = s._get_type_name(MyType())
        assert "MyType" in name


# ============================================================================
# Interface compliance
# ============================================================================


class TestFallbackInterface:
    """Tests for Serializer interface compliance."""

    def test_is_serializer(self):
        from dhara.serialize.base import Serializer

        s = FallbackSerializer()
        assert isinstance(s, Serializer)

    def test_satisfies_protocol(self):
        from dhara.serialize.base import SerializerProtocol

        s = FallbackSerializer()
        assert isinstance(s, SerializerProtocol)


# ============================================================================
# DEFAULT_PICKLE_WHITELIST contents
# ============================================================================


class TestDefaultWhitelist:
    """Tests for the default whitelist contents."""

    def test_includes_numpy(self):
        assert "numpy.ndarray" in DEFAULT_PICKLE_WHITELIST
        assert "numpy.dtype" in DEFAULT_PICKLE_WHITELIST

    def test_includes_pandas(self):
        assert "pandas.DataFrame" in DEFAULT_PICKLE_WHITELIST
        assert "pandas.Series" in DEFAULT_PICKLE_WHITELIST

    def test_includes_scipy(self):
        assert "scipy.sparse.csr_matrix" in DEFAULT_PICKLE_WHITELIST

    def test_includes_pil(self):
        assert "PIL.Image.Image" in DEFAULT_PICKLE_WHITELIST


# ============================================================================
# Pickle failure fallback paths (lines 176-201)
# ============================================================================


class _BrokenReduce:
    """Object that msgspec cannot handle AND pickle cannot serialize.

    Its __reduce__ raises RuntimeError, so pickle.dumps() will fail.
    msgspec will also fail because it is a custom object.
    """

    def __reduce__(self):
        raise RuntimeError("intentional pickle failure for testing")


class _BrokenReduceDillable:
    """Object that msgspec cannot handle.

    Used with _pickle.serialize mocked to raise, so the fallback
    path exercises dill.  dill can serialize this directly.
    """

    def __init__(self, value=99):
        self.value = value


class TestPickleFailurePaths:
    """Tests for when msgspec fails AND pickle also fails (lines 176-201)."""

    def test_pickle_fail_no_dill_raises_typeerror(self):
        """When pickle fails and dill is not allowed, raise TypeError (lines 199-204)."""
        s = FallbackSerializer(
            pickle_whitelist={_qualname(_BrokenReduce)},
            allow_dill=False,
        )
        obj = _BrokenReduce()
        with pytest.raises(TypeError, match="Failed to serialize"):
            s.serialize(obj)

    def test_pickle_fail_no_dill_increments_failed_count(self):
        """Failed count is incremented when both msgspec and pickle fail."""
        s = FallbackSerializer(
            pickle_whitelist={_qualname(_BrokenReduce)},
            allow_dill=False,
        )
        try:
            s.serialize(_BrokenReduce())
        except TypeError:
            pass
        stats = s.get_stats()
        assert stats["failed_count"] == 1

    def test_pickle_fail_dill_allowed_raises_typeerror_when_dill_also_fails(self):
        """When pickle and dill both fail, raise TypeError (lines 193-198)."""
        try:
            import dill  # noqa: F401
        except ImportError:
            pytest.skip("dill not installed")

        s = FallbackSerializer(
            pickle_whitelist={_qualname(_BrokenReduce)},
            allow_dill=True,
        )
        obj = _BrokenReduce()
        with pytest.raises(TypeError, match="msgspec, pickle, or dill"):
            s.serialize(obj)

    def test_pickle_fail_dill_allowed_increments_failed_count(self):
        """Failed count when all three serializers fail."""
        try:
            import dill  # noqa: F401
        except ImportError:
            pytest.skip("dill not installed")

        s = FallbackSerializer(
            pickle_whitelist={_qualname(_BrokenReduce)},
            allow_dill=True,
        )
        try:
            s.serialize(_BrokenReduce())
        except TypeError:
            pass
        stats = s.get_stats()
        assert stats["failed_count"] == 1

    def test_pickle_fail_dill_succeeds_uses_dill_prefix(self):
        """When pickle fails but dill succeeds, data uses SERIALIZER_DILL prefix."""
        try:
            import dill  # noqa: F401
        except ImportError:
            pytest.skip("dill not installed")

        s = FallbackSerializer(
            pickle_whitelist={_qualname(_BrokenReduceDillable)},
            allow_dill=True,
        )
        obj = _BrokenReduceDillable()
        with patch.object(s._pickle, "serialize", side_effect=RuntimeError("pickle fail")):
            data = s.serialize(obj)
            assert data[0] == SERIALIZER_DILL

    def test_pickle_fail_dill_succeeds_roundtrip(self):
        """Roundtrip through dill after pickle failure."""
        try:
            import dill  # noqa: F401
        except ImportError:
            pytest.skip("dill not installed")

        s = FallbackSerializer(
            pickle_whitelist={_qualname(_BrokenReduceDillable)},
            allow_dill=True,
        )
        obj = _BrokenReduceDillable(value=42)
        with patch.object(s._pickle, "serialize", side_effect=RuntimeError("pickle fail")):
            data = s.serialize(obj)
            result = s.deserialize(data)
            assert result.value == 42

    def test_pickle_fail_dill_succeeds_increments_dill_stats(self):
        """Dill fallback count is incremented on successful dill serialization."""
        try:
            import dill  # noqa: F401
        except ImportError:
            pytest.skip("dill not installed")

        s = FallbackSerializer(
            pickle_whitelist={_qualname(_BrokenReduceDillable)},
            allow_dill=True,
        )
        obj = _BrokenReduceDillable()
        with patch.object(s._pickle, "serialize", side_effect=RuntimeError("pickle fail")):
            s.serialize(obj)
            stats = s.get_stats()
            assert stats["dill_fallback_count"] == 1

    def test_pickle_fail_emits_dill_warning(self):
        """Warning is emitted when falling back to dill after pickle failure."""
        try:
            import dill  # noqa: F401
        except ImportError:
            pytest.skip("dill not installed")

        s = FallbackSerializer(
            pickle_whitelist={_qualname(_BrokenReduceDillable)},
            allow_dill=True,
        )
        obj = _BrokenReduceDillable()
        with patch.object(s._pickle, "serialize", side_effect=RuntimeError("pickle fail")):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                s.serialize(obj)
                assert any(
                    "dill" in str(warning.message).lower() for warning in w
                )


# ============================================================================
# Dill deserialization path (lines 256-257)
# ============================================================================


class TestDillDeserialization:
    """Tests for the SERIALIZER_DILL branch in deserialize (lines 256-257)."""

    def test_deserialize_dill_data(self):
        """Deserializing data with SERIALIZER_DILL prefix uses dill."""
        try:
            import dill  # noqa: F401
        except ImportError:
            pytest.skip("dill not installed")

        s = FallbackSerializer(
            pickle_whitelist={_qualname(_BrokenReduceDillable)},
            allow_dill=True,
        )
        obj = _BrokenReduceDillable(value=7)
        with patch.object(s._pickle, "serialize", side_effect=RuntimeError("pickle fail")):
            data = s.serialize(obj)
            assert data[0] == SERIALIZER_DILL
            result = s.deserialize(data)
            assert result.value == 7

    def test_deserialize_dill_max_size_enforced(self):
        """Dill deserialize path also enforces max_size."""
        try:
            import dill  # noqa: F401
        except ImportError:
            pytest.skip("dill not installed")

        s = FallbackSerializer(allow_dill=True)
        payload = b"x" * 1000
        data = bytes([SERIALIZER_DILL]) + payload
        with pytest.raises(ValueError, match="too large"):
            s.deserialize(data, max_size=10)


# ============================================================================
# get_state method (lines 274-282)
# ============================================================================


class _StatefulObj:
    """Object with __dict__ that msgspec.get_state can handle via __getstate__."""

    def __init__(self, x=1):
        self.x = x


class _BrokenGetState:
    """Object whose __getstate__ returns a non-dict value.

    msgspec.get_state calls to_builtins on the result, which fails for
    non-serializable types.  PickleSerializer.get_state sees the result
    is not a dict and falls through to obj.__dict__.
    """

    def __init__(self, x=5):
        self.x = x

    def __getstate__(self):
        # Return a non-dict, non-builtin value that to_builtins cannot handle
        return lambda: "not serializable"


class TestGetState:
    """Tests for FallbackSerializer.get_state (lines 274-282)."""

    def test_get_state_msgspec_path(self):
        """get_state works via msgspec for msgspec-compatible objects."""
        from dhara.core.persistent import Persistent

        class MyPersistent(Persistent):
            def __init__(self, val=10):
                self.val = val

        s = FallbackSerializer()
        obj = MyPersistent()
        state = s.get_state(obj)
        assert isinstance(state, dict)

    def test_get_state_pickle_fallback_for_whitelisted(self):
        """get_state falls back to pickle for whitelisted types (lines 278-280)."""
        s = FallbackSerializer(pickle_whitelist={_qualname(_BrokenGetState)})
        obj = _BrokenGetState(x=42)
        state = s.get_state(obj)
        assert isinstance(state, dict)
        assert state["x"] == 42

    def test_get_state_pickle_fallback_returns_obj_dict(self):
        """Pickle fallback in get_state returns the object's __dict__."""
        s = FallbackSerializer(pickle_whitelist={_qualname(_BrokenGetState)})
        obj = _BrokenGetState(x=99)
        state = s.get_state(obj)
        # PickleSerializer.get_state falls through to __dict__ since
        # __getstate__ returns a non-dict (a lambda)
        assert state["x"] == 99

    def test_get_state_non_whitelisted_raises_value_error(self):
        """get_state raises ValueError for non-whitelisted types (lines 282-285)."""
        s = FallbackSerializer(pickle_whitelist=set())
        obj = _BrokenGetState()
        with pytest.raises(ValueError, match="Cannot extract state"):
            s.get_state(obj)

    def test_get_state_non_whitelisted_mentions_type(self):
        """Error message includes the type name."""
        s = FallbackSerializer(pickle_whitelist=set())
        obj = _BrokenGetState()
        with pytest.raises(ValueError, match="BrokenGetState"):
            s.get_state(obj)
