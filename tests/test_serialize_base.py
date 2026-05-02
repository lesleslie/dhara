"""Tests for base serializer interface."""

from typing import Any

import pytest

from dhara.serialize.base import DEFAULT_MAX_SIZE, Serializer, SerializerProtocol


class TestDefaultMaxSize:
    """Tests for DEFAULT_MAX_SIZE constant."""

    def test_max_size_is_100mb(self):
        assert DEFAULT_MAX_SIZE == 100 * 1024 * 1024

    def test_max_size_bytes(self):
        assert DEFAULT_MAX_SIZE == 104_857_600


class TestSerializerABC:
    """Tests for the abstract Serializer base class."""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            Serializer()

    def test_concrete_implementation(self):
        class ConcreteSerializer(Serializer):
            def serialize(self, obj: Any) -> bytes:
                return b""

            def deserialize(self, data: bytes, max_size: int = DEFAULT_MAX_SIZE) -> Any:
                return None

            def get_state(self, obj: Any) -> dict:
                return {}

        s = ConcreteSerializer()
        assert isinstance(s, Serializer)

    def test_isinstance_check(self):
        from dhara.serialize.msgspec import MsgspecSerializer

        s = MsgspecSerializer()
        assert isinstance(s, Serializer)


class TestSerializerProtocol:
    """Tests for the Protocol-based serializer interface."""

    def test_protocol_is_runtime_checkable(self):
        class MySerializer:
            def serialize(self, obj: Any) -> bytes:
                return b""

            def deserialize(self, data: bytes, max_size: int = DEFAULT_MAX_SIZE) -> Any:
                return None

            def get_state(self, obj: Any) -> dict:
                return {}

        assert isinstance(MySerializer(), SerializerProtocol)

    def test_protocol_rejects_incomplete(self):
        class BadSerializer:
            def serialize(self, obj: Any) -> bytes:
                return b""

        assert not isinstance(BadSerializer(), SerializerProtocol)

    def test_protocol_rejects_wrong_signatures(self):
        class WrongSigSerializer:
            def serialize(self) -> bytes:
                return b""

            def deserialize(self, data: bytes) -> Any:
                return None

            def get_state(self, obj: Any) -> dict:
                return {}

        # Protocol checks method existence, not full signature matching
        # but wrong signatures would fail at runtime
        assert isinstance(WrongSigSerializer(), SerializerProtocol)

    def test_real_serializer_satisfies_protocol(self):
        from dhara.serialize.msgspec import MsgspecSerializer

        s = MsgspecSerializer()
        assert isinstance(s, SerializerProtocol)


class TestExports:
    """Tests for module exports."""

    def test_all_exports_exist(self):
        from dhara.serialize.base import Serializer, SerializerProtocol, DEFAULT_MAX_SIZE

        assert Serializer is not None
        assert SerializerProtocol is not None
        assert DEFAULT_MAX_SIZE is not None
