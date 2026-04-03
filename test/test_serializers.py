"""Tests for serializer implementations.

Tests all serializer backends (msgspec, pickle, dill) to ensure they
correctly implement the Serializer interface and handle various data types.
"""

import pytest

from dhara.core.persistent import Persistent
from dhara.serialize import (
    Serializer,
    MsgspecSerializer,
    PickleSerializer,
    DillSerializer,
    create_serializer,
)


class SimplePersistent(Persistent):
    """Simple persistent object for testing."""

    def __init__(self, value: int = 0):
        self.value = value


class ComplexPersistent(Persistent):
    """Persistent object with nested data."""

    def __init__(self, data: dict | None = None):
        self.data = data or {}


class TestPickleSerializer:
    """Test PickleSerializer implementation."""

    def test_serialize_deserialize_simple_types(self):
        """Test serialization of simple Python types."""
        serializer = PickleSerializer()

        test_cases = [
            42,
            "hello",
            [1, 2, 3],
            {"key": "value"},
            (1, 2, 3),
            {1, 2, 3},
            True,
            None,
        ]

        for obj in test_cases:
            data = serializer.serialize(obj)
            result = serializer.deserialize(data)
            assert result == obj

    def test_serialize_deserialize_persistent(self):
        """Test serialization of Persistent objects."""
        serializer = PickleSerializer()
        obj = SimplePersistent(42)

        state = serializer.get_state(obj)
        assert isinstance(state, dict)
        assert "value" in state
        assert state["value"] == 42

    def test_protocol_parameter(self):
        """Test that protocol parameter is respected."""
        serializer = PickleSerializer(protocol=4)
        assert serializer.protocol == 4


class TestMsgspecSerializer:
    """Test MsgspecSerializer implementation."""

    def test_serialize_deserialize_simple_types(self):
        """Test serialization of simple Python types."""
        serializer = MsgspecSerializer()

        test_cases = [
            42,
            "hello",
            [1, 2, 3],
            {"key": "value"},
            True,
            None,
        ]

        for obj in test_cases:
            data = serializer.serialize(obj)
            result = serializer.deserialize(data)
            assert result == obj

    def test_serialize_deserialize_persistent(self):
        """Test serialization of Persistent objects."""
        serializer = MsgspecSerializer()
        obj = SimplePersistent(42)

        state = serializer.get_state(obj)
        assert isinstance(state, dict)
        assert "value" in state
        assert state["value"] == 42

    def test_msgpack_format(self):
        """Test MessagePack format."""
        serializer = MsgspecSerializer(format="msgpack")
        assert serializer.format == "msgpack"

    def test_json_format(self):
        """Test JSON format."""
        serializer = MsgspecSerializer(format="json")
        assert serializer.format == "json"

    def test_use_builtins_flag(self):
        """Test use_builtins parameter."""
        serializer = MsgspecSerializer(use_builtins=True)
        assert serializer.use_builtins is True


class TestDillSerializer:
    """Test DillSerializer implementation."""

    def test_serialize_deserialize_simple_types(self):
        """Test serialization of simple Python types."""
        try:
            serializer = DillSerializer()
        except ImportError:
            pytest.skip("dill not installed")

        test_cases = [
            42,
            "hello",
            [1, 2, 3],
            {"key": "value"},
            (1, 2, 3),
            {1, 2, 3},
            True,
            None,
        ]

        for obj in test_cases:
            data = serializer.serialize(obj)
            result = serializer.deserialize(data)
            assert result == obj

    def test_serialize_deserialize_persistent(self):
        """Test serialization of Persistent objects."""
        try:
            serializer = DillSerializer()
        except ImportError:
            pytest.skip("dill not installed")

        obj = SimplePersistent(42)
        state = serializer.get_state(obj)
        assert isinstance(state, dict)
        assert "value" in state
        assert state["value"] == 42


class TestSerializerFactory:
    """Test serializer factory function."""

    def test_create_pickle_serializer(self):
        """Test creating pickle serializer via factory."""
        serializer = create_serializer("pickle")
        assert isinstance(serializer, PickleSerializer)

    def test_create_msgspec_serializer(self):
        """Test creating msgspec serializer via factory."""
        serializer = create_serializer("msgspec")
        assert isinstance(serializer, MsgspecSerializer)

    def test_create_dill_serializer(self):
        """Test creating dill serializer via factory."""
        try:
            serializer = create_serializer("dill")
            assert isinstance(serializer, DillSerializer)
        except ImportError:
            pytest.skip("dill not installed")

    def test_create_with_kwargs(self):
        """Test creating serializers with custom arguments."""
        pickle_ser = create_serializer("pickle", protocol=4)
        assert pickle_ser.protocol == 4

        msgspec_ser = create_serializer("msgspec", format="json")
        assert msgspec_ser.format == "json"

    def test_invalid_backend_raises(self):
        """Test that invalid backend name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown serializer"):
            create_serializer("invalid_backend")

    def test_invalid_kwargs_raises(self):
        """Test that invalid kwargs raise TypeError."""
        with pytest.raises(TypeError):
            create_serializer("pickle", invalid_arg=123)


class TestSerializerInterface:
    """Test that all serializers implement the Serializer interface correctly."""

    def test_all_serializers_implement_interface(self):
        """Test that all serializers implement required methods."""
        serializers = [
            PickleSerializer(),
            MsgspecSerializer(),
        ]

        try:
            serializers.append(DillSerializer())
        except ImportError:
            pass

        for serializer in serializers:
            assert hasattr(serializer, "serialize")
            assert callable(serializer.serialize)
            assert hasattr(serializer, "deserialize")
            assert callable(serializer.deserialize)
            assert hasattr(serializer, "get_state")
            assert callable(serializer.get_state)

            test_obj = {"test": 42}
            data = serializer.serialize(test_obj)
            assert isinstance(data, bytes)
            result = serializer.deserialize(data)
            assert isinstance(result, dict)


class TestSerializerComparison:
    """Compare serializers for performance and characteristics."""

    def test_serialized_size_comparison(self):
        """Compare serialized size between pickle and msgspec."""
        pickle_ser = PickleSerializer()
        msgspec_ser = MsgspecSerializer()

        test_data = {"key": "value", "list": [1, 2, 3, 4, 5]}

        pickle_size = len(pickle_ser.serialize(test_data))
        msgspec_size = len(msgspec_ser.serialize(test_data))

        print(f"Pickle size: {pickle_size}, Msgspec size: {msgspec_size}")

    def test_nested_data_serialization(self):
        """Test serialization of nested data structures."""
        serializer = MsgspecSerializer()

        nested = {
            "level1": {
                "level2": {
                    "level3": [1, 2, 3]
                }
            },
            "list_of_dicts": [
                {"a": 1},
                {"b": 2},
            ]
        }

        data = serializer.serialize(nested)
        result = serializer.deserialize(data)
        assert result == nested
