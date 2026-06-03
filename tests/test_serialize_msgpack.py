"""Tests for msgpack-based serializer.

Tests the MsgpackSerializer which is part of Dhara's serialization layer.
The serializer is msgspec-backed (no pickle).
"""

from typing import Any

import pytest

from dhara.serialize.base import DEFAULT_MAX_SIZE
from dhara.serialize.msgpack import MsgpackSerializer


# ============================================================================
# Roundtrip serialization
# ============================================================================


class TestMsgpackRoundtrip:
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
        s = MsgpackSerializer()
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result == obj

    def test_roundtrip_preserves_types(self):
        s = MsgpackSerializer()
        obj = {"int": 42, "float": 3.14, "bool": True, "none": None}
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert type(result["int"]) is int
        assert type(result["float"]) is float
        assert type(result["bool"]) is bool
        assert result["none"] is None

    def test_roundtrip_set_normalizes_to_list(self):
        """Sets normalize to lists in the msgspec wire format.

        This is a known semantic characteristic of the msgspec wire format.
        Set membership is preserved but set type is not.
        """
        s = MsgpackSerializer()
        obj = {1, 2, 3}
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert sorted(result) == sorted(obj)
        assert isinstance(result, list)

    def test_roundtrip_tuple_normalizes_to_list(self):
        """Tuples normalize to lists in the msgspec wire format."""
        s = MsgpackSerializer()
        obj = (1, "two", 3.0)
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert list(result) == list(obj)
        assert isinstance(result, list)

    def test_roundtrip_complex_nesting(self):
        """Inner tuple/set normalize to lists (see msgspec format)."""
        s = MsgpackSerializer()
        obj = {"list": [{"dict": {"key": (1, 2, 3)}}], "set": {4, 5, 6}}
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert isinstance(result["list"], list)
        assert sorted(result["set"]) == sorted(obj["set"])
        assert result["list"][0]["dict"]["key"] == [1, 2, 3]

    def test_large_data_roundtrip(self):
        s = MsgpackSerializer()
        obj = {f"key_{i}": f"value_{i}" * 100 for i in range(1000)}
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result == obj

    def test_serialize_returns_bytes(self):
        s = MsgpackSerializer()
        data = s.serialize(42)
        assert isinstance(data, bytes)


# ============================================================================
# Size validation
# ============================================================================


class TestMsgpackSizeValidation:
    """Tests for max_size enforcement."""

    def test_deserialize_respects_max_size(self):
        s = MsgpackSerializer()
        obj = {"key": "x" * 1000}
        data = s.serialize(obj)
        with pytest.raises(ValueError, match="too large"):
            s.deserialize(data, max_size=10)

    def test_deserialize_at_exact_size_ok(self):
        s = MsgpackSerializer()
        obj = {"key": "value"}
        data = s.serialize(obj)
        result = s.deserialize(data, max_size=len(data))
        assert result == obj

    def test_deserialize_default_max_size(self):
        s = MsgpackSerializer()
        obj = {"key": "x" * 100}
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result == obj


# ============================================================================
# get_state
# ============================================================================


class TestMsgpackGetState:
    """Tests for get_state method."""

    def test_get_state_simple_object(self):
        class SimpleObj:
            def __init__(self, value):
                self.value = value

        s = MsgpackSerializer()
        obj = SimpleObj(42)
        state = s.get_state(obj)
        assert state == {"value": 42}

    def test_get_state_with_getstate(self):
        class CustomObj:
            def __getstate__(self):
                return {"custom": True, "data": 123}

        s = MsgpackSerializer()
        obj = CustomObj()
        state = s.get_state(obj)
        assert state == {"custom": True, "data": 123}

    def test_get_state_no_dict_returns_empty(self):
        s = MsgpackSerializer()
        state = s.get_state(42)
        assert state == {}

    def test_get_state_returns_dict_when_getstate_non_dict(self):
        class WeirdState:
            def __getstate__(self):
                return [1, 2, 3]

        s = MsgpackSerializer()
        obj = WeirdState()
        state = s.get_state(obj)
        # Falls back to __dict__ when __getstate__ returns non-dict
        assert isinstance(state, dict)


# ============================================================================
# Interface compliance
# ============================================================================


class TestMsgpackInterface:
    """Tests for Serializer interface compliance."""

    def test_is_serializer(self):
        from dhara.serialize.base import Serializer

        s = MsgpackSerializer()
        assert isinstance(s, Serializer)

    def test_satisfies_protocol(self):
        from dhara.serialize.base import SerializerProtocol

        s = MsgpackSerializer()
        assert isinstance(s, SerializerProtocol)

    def test_no_constructor_args(self):
        """MsgpackSerializer has no constructor arguments (protocol shim removed)."""
        s = MsgpackSerializer()
        # Should be constructible with no args (no protocol= kwarg).
        assert s is not None
