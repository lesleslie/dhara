"""Tests for FallbackSerializer with whitelist-based fallback."""

import pickle
import warnings

import pytest

from dhara.serialize import FallbackSerializer
from dhara.serialize.base import DEFAULT_MAX_SIZE


# Define test classes at module level so they can be pickled
class SimpleClass:
    """A simple class that requires pickle."""
    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return isinstance(other, SimpleClass) and self.value == other.value


class NeedsPickle:
    """Another class that requires pickle."""
    def __init__(self, x):
        self.x = x

    def __eq__(self, other):
        return isinstance(other, NeedsPickle) and self.x == other.x


class TestFallbackSerializerBasics:
    """Test basic fallback serializer functionality."""

    def test_serialize_dict_with_msgspec(self):
        """Regular dicts should use msgspec."""
        serializer = FallbackSerializer()
        data = {"key": "value", "number": 42}

        serialized = serializer.serialize(data)
        assert serialized[0] == 0  # SERIALIZER_MSGSPEC

        deserialized = serializer.deserialize(serialized)
        assert deserialized == data

        stats = serializer.get_stats()
        assert stats["msgspec_count"] == 1
        assert stats["pickle_fallback_count"] == 0

    def test_serialize_list_with_msgspec(self):
        """Regular lists should use msgspec."""
        serializer = FallbackSerializer()
        data = [1, 2, 3, "four", {"five": 5}]

        serialized = serializer.serialize(data)
        assert serialized[0] == 0  # SERIALIZER_MSGSPEC

        deserialized = serializer.deserialize(serialized)
        assert deserialized == data

    def test_empty_data_fails(self):
        """Empty data should raise ValueError."""
        serializer = FallbackSerializer()
        with pytest.raises(ValueError, match="Cannot deserialize empty data"):
            serializer.deserialize(b"")

    def test_invalid_serializer_id(self):
        """Invalid serializer ID should raise ValueError."""
        serializer = FallbackSerializer()
        invalid_data = bytes([99]) + b"some data"
        with pytest.raises(ValueError, match="Invalid serializer ID"):
            serializer.deserialize(invalid_data)

    def test_max_size_enforcement(self):
        """Data exceeding max_size should raise ValueError."""
        serializer = FallbackSerializer()
        large_data = bytes([0]) + b"x" * (DEFAULT_MAX_SIZE + 1)

        with pytest.raises(ValueError, match="Data too large"):
            serializer.deserialize(large_data)


class TestWhitelistFunctionality:
    """Test whitelist-based fallback behavior."""

    def test_non_whitelisted_type_fails(self):
        """Types not in whitelist should fail with helpful error."""
        serializer = FallbackSerializer(pickle_whitelist=set())

        # Use SimpleClass which requires pickle
        obj = SimpleClass(42)

        with pytest.raises(ValueError, match="Type is not in pickle whitelist"):
            serializer.serialize(obj)

    def test_whitelisted_type_uses_pickle(self):
        """Whitelisted types should fall back to pickle."""
        type_name = f"{SimpleClass.__module__}.{SimpleClass.__name__}"
        serializer = FallbackSerializer(pickle_whitelist={type_name})

        obj = SimpleClass(42)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            serialized = serializer.serialize(obj)

            # Should have warned about pickle fallback
            assert len(w) == 1
            assert "Falling back to pickle" in str(w[0].message)

        assert serialized[0] == 1  # SERIALIZER_PICKLE

        deserialized = serializer.deserialize(serialized)
        assert deserialized.value == 42

        stats = serializer.get_stats()
        assert stats["pickle_fallback_count"] == 1

    def test_whitelist_management(self):
        """Test adding and removing from whitelist."""
        serializer = FallbackSerializer()

        initial_size = len(serializer.pickle_whitelist)

        # Add to whitelist
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            serializer.add_to_whitelist("test.Type")

        assert len(serializer.pickle_whitelist) == initial_size + 1
        assert "test.Type" in serializer.pickle_whitelist

        # Remove from whitelist
        serializer.remove_from_whitelist("test.Type")
        assert len(serializer.pickle_whitelist) == initial_size
        assert "test.Type" not in serializer.pickle_whitelist

        # Remove non-existent type should warn but not error
        serializer.remove_from_whitelist("nonexistent.Type")


class TestStatisticsAndMonitoring:
    """Test statistics collection for monitoring."""

    def test_statistics_tracking(self):
        """Serializer should track usage statistics."""
        serializer = FallbackSerializer()

        # Serialize some items with msgspec
        for i in range(5):
            serializer.serialize({"item": i})

        stats = serializer.get_stats()
        assert stats["msgspec_count"] == 5
        assert stats["pickle_fallback_count"] == 0
        assert stats["dill_fallback_count"] == 0
        assert stats["failed_count"] == 0

    def test_stats_returns_copy(self):
        """get_stats should return a copy, not the internal dict."""
        serializer = FallbackSerializer()
        stats1 = serializer.get_stats()
        stats2 = serializer.get_stats()

        # Modifying returned stats shouldn't affect internal stats
        stats1["msgspec_count"] = 999
        assert stats2["msgspec_count"] != 999


class TestDillFallback:
    """Test dill as final fallback."""

    def test_dill_disabled_by_default(self):
        """Dill should be disabled unless explicitly enabled."""
        serializer = FallbackSerializer(allow_dill=False)
        assert serializer._dill is None

    def test_dill_enabled_when_requested(self):
        """Dill should be available when allow_dill=True and dill is installed."""
        try:
            import dill
            # dill is installed, test should work
            serializer = FallbackSerializer(allow_dill=True)
            assert serializer._dill is not None
        except ImportError:
            # dill is not installed, skip this test
            pytest.skip("dill is not installed")


class TestRoundTrip:
    """Test serialization/deserialization round trips."""

    def test_msgspec_round_trip(self):
        """Msgspec objects should round-trip correctly."""
        serializer = FallbackSerializer()
        original = {
            "string": "hello",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "none": None,
            "list": [1, 2, 3],
            "nested": {"a": {"b": "c"}},
        }

        serialized = serializer.serialize(original)
        deserialized = serializer.deserialize(serialized)

        assert deserialized == original

    def test_multiple_types_mixed(self):
        """Mix of msgspec and whitelisted types should work."""
        type_name = f"{NeedsPickle.__module__}.{NeedsPickle.__name__}"

        serializer = FallbackSerializer(pickle_whitelist={type_name})

        # Msgspec-compatible
        msgspec_obj = {"regular": "data", "count": 5}

        # Needs pickle
        pickle_obj = NeedsPickle(42)

        # Both should round-trip
        with warnings.catch_warnings():
            warnings.simplefilter("always")
            serialized1 = serializer.serialize(msgspec_obj)
            serialized2 = serializer.serialize(pickle_obj)

        assert serialized1[0] == 0  # msgspec
        assert serialized2[0] == 1  # pickle

        assert serializer.deserialize(serialized1) == msgspec_obj
        assert serializer.deserialize(serialized2).x == 42


class TestDefaultWhitelist:
    """Test default whitelist behavior."""

    def test_default_whitelist_includes_common_types(self):
        """Default whitelist should include common data science types."""
        serializer = FallbackSerializer()

        # Check for common numpy types
        assert "numpy.ndarray" in serializer.pickle_whitelist
        assert "numpy.matrix" in serializer.pickle_whitelist

        # Check for pandas types
        assert "pandas.DataFrame" in serializer.pickle_whitelist
        assert "pandas.Series" in serializer.pickle_whitelist

        # Check for scipy types
        assert "scipy.sparse.csr_matrix" in serializer.pickle_whitelist

    def test_empty_whitelist_works(self):
        """Empty whitelist should still work for msgspec types."""
        serializer = FallbackSerializer(pickle_whitelist=set())
        data = {"key": "value", "number": [1, 2, 3]}

        serialized = serializer.serialize(data)
        deserialized = serializer.deserialize(serialized)

        assert deserialized == data
        assert serializer.get_stats()["msgspec_count"] == 1
