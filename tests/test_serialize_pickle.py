"""Tests for pickle-based serializer.

Tests the existing PickleSerializer which is part of Dhara's backward
compatibility layer. The serializer under test already exists in the
codebase - these tests verify its behavior.
"""

from typing import Any

import pytest

from dhara.serialize.base import DEFAULT_MAX_SIZE
from dhara.serialize.pickle import PickleSerializer


# ============================================================================
# Constructor
# ============================================================================


class TestPickleConstructor:
    """Tests for PickleSerializer initialization."""

    def test_default_protocol(self):
        s = PickleSerializer()
        assert s.protocol == 2

    def test_custom_protocol(self):
        s = PickleSerializer(protocol=5)
        assert s.protocol == 5

    @pytest.mark.parametrize("protocol", [0, 1, 2, 3, 4, 5])
    def test_all_protocols_accepted(self, protocol):
        s = PickleSerializer(protocol=protocol)
        assert s.protocol == protocol


# ============================================================================
# Roundtrip serialization
# ============================================================================


class TestPickleRoundtrip:
    """Tests for serialize/deserialize roundtrip."""

    @pytest.mark.parametrize(
        "obj",
        [
            None,
            True,
            False,
            42,
            -100,
            3.14,
            "hello",
            [],
            [1, 2, 3],
            {},
            {"key": "value"},
            {"nested": {"a": [1, 2, 3]}},
        ],
    )
    def test_roundtrip_primitives(self, obj):
        s = PickleSerializer()
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result == obj

    def test_roundtrip_preserves_types(self):
        s = PickleSerializer()
        obj = {"int": 42, "float": 3.14, "bool": True, "none": None}
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert type(result["int"]) is int
        assert type(result["float"]) is float
        assert type(result["bool"]) is bool
        assert result["none"] is None

    def test_roundtrip_set(self):
        s = PickleSerializer()
        obj = {1, 2, 3}
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result == obj

    def test_roundtrip_tuple(self):
        s = PickleSerializer()
        obj = (1, "two", 3.0)
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result == obj

    def test_roundtrip_complex_nesting(self):
        s = PickleSerializer()
        obj = {"list": [{"dict": {"key": (1, 2, 3)}}], "set": {4, 5, 6}}
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result == obj

    def test_large_data_roundtrip(self):
        s = PickleSerializer()
        obj = {f"key_{i}": f"value_{i}" * 100 for i in range(1000)}
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result == obj

    def test_serialize_returns_bytes(self):
        s = PickleSerializer()
        data = s.serialize(42)
        assert isinstance(data, bytes)


# ============================================================================
# Size validation
# ============================================================================


class TestPickleSizeValidation:
    """Tests for max_size enforcement."""

    def test_deserialize_respects_max_size(self):
        s = PickleSerializer()
        obj = {"key": "x" * 1000}
        data = s.serialize(obj)
        with pytest.raises(ValueError, match="too large"):
            s.deserialize(data, max_size=10)

    def test_deserialize_at_exact_size_ok(self):
        s = PickleSerializer()
        obj = {"key": "value"}
        data = s.serialize(obj)
        result = s.deserialize(data, max_size=len(data))
        assert result == obj

    def test_deserialize_default_max_size(self):
        s = PickleSerializer()
        obj = {"key": "x" * 100}
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result == obj


# ============================================================================
# get_state
# ============================================================================


class TestPickleGetState:
    """Tests for get_state method."""

    def test_get_state_simple_object(self):
        class SimpleObj:
            def __init__(self, value):
                self.value = value

        s = PickleSerializer()
        obj = SimpleObj(42)
        state = s.get_state(obj)
        assert state == {"value": 42}

    def test_get_state_with_getstate(self):
        class CustomObj:
            def __getstate__(self):
                return {"custom": True, "data": 123}

        s = PickleSerializer()
        obj = CustomObj()
        state = s.get_state(obj)
        assert state == {"custom": True, "data": 123}

    def test_get_state_no_dict_returns_empty(self):
        s = PickleSerializer()
        state = s.get_state(42)
        assert state == {}

    def test_get_state_returns_dict_when_getstate_non_dict(self):
        class WeirdState:
            def __getstate__(self):
                return [1, 2, 3]

        s = PickleSerializer()
        obj = WeirdState()
        state = s.get_state(obj)
        # Falls back to __dict__ when __getstate__ returns non-dict
        assert isinstance(state, dict)


# ============================================================================
# Interface compliance
# ============================================================================


class TestPickleInterface:
    """Tests for Serializer interface compliance."""

    def test_is_serializer(self):
        from dhara.serialize.base import Serializer

        s = PickleSerializer()
        assert isinstance(s, Serializer)

    def test_satisfies_protocol(self):
        from dhara.serialize.base import SerializerProtocol

        s = PickleSerializer()
        assert isinstance(s, SerializerProtocol)
