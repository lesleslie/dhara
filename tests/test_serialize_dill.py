"""Tests for dhara.serialize.dill — DillSerializer, DILL_AVAILABLE, DummyDill.

NOTE: dill is a pickle-compatible serializer. Pickle/dill usage here is intentional
and necessary — we are testing the serialization infrastructure itself.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dhara.serialize.dill import DILL_AVAILABLE, DillSerializer
from dhara.serialize.base import DEFAULT_MAX_SIZE


# ===========================================================================
# DILL_AVAILABLE
# ===========================================================================


class TestDillAvailable:
    def test_is_bool(self):
        assert isinstance(DILL_AVAILABLE, bool)

    def test_reflects_install(self):
        assert DILL_AVAILABLE is True or DILL_AVAILABLE is False


# ===========================================================================
# DillSerializer
# ===========================================================================


class TestDillSerializerInit:
    def test_init_with_dill(self):
        if not DILL_AVAILABLE:
            pytest.skip("dill not installed")
        ds = DillSerializer()
        assert ds.protocol >= 2  # dill 0.3.x=2, 0.4.x=4

    def test_init_custom_protocol(self):
        if not DILL_AVAILABLE:
            pytest.skip("dill not installed")
        ds = DillSerializer(protocol=4)
        assert ds.protocol == 4

    def test_init_no_dill_raises(self):
        if DILL_AVAILABLE:
            pytest.skip("dill is installed, cannot test missing case")
        with pytest.raises(ImportError, match="dill is required"):
            DillSerializer()


class TestDillSerializerSerialize:
    def test_serialize_basic_types(self):
        if not DILL_AVAILABLE:
            pytest.skip("dill not installed")
        ds = DillSerializer()
        for obj in [42, "hello", [1, 2, 3], {"key": "value"}, None, True, 3.14]:
            data = ds.serialize(obj)
            assert isinstance(data, bytes)
            assert len(data) > 0

    def test_serialize_lambda(self):
        if not DILL_AVAILABLE:
            pytest.skip("dill not installed")
        ds = DillSerializer()
        data = ds.serialize(lambda x: x + 1)
        assert isinstance(data, bytes)


class TestDillSerializerDeserialize:
    def test_roundtrip_int(self):
        if not DILL_AVAILABLE:
            pytest.skip("dill not installed")
        ds = DillSerializer()
        data = ds.serialize(42)
        assert ds.deserialize(data) == 42

    def test_roundtrip_string(self):
        if not DILL_AVAILABLE:
            pytest.skip("dill not installed")
        ds = DillSerializer()
        data = ds.serialize("hello world")
        assert ds.deserialize(data) == "hello world"

    def test_roundtrip_list(self):
        if not DILL_AVAILABLE:
            pytest.skip("dill not installed")
        ds = DillSerializer()
        obj = [1, "two", 3.0, None]
        assert ds.deserialize(ds.serialize(obj)) == obj

    def test_roundtrip_dict(self):
        if not DILL_AVAILABLE:
            pytest.skip("dill not installed")
        ds = DillSerializer()
        obj = {"a": 1, "b": [2, 3]}
        assert ds.deserialize(ds.serialize(obj)) == obj

    def test_roundtrip_nested(self):
        if not DILL_AVAILABLE:
            pytest.skip("dill not installed")
        ds = DillSerializer()
        obj = {"key": [{"a": 1}, {"b": 2}]}
        assert ds.deserialize(ds.serialize(obj)) == obj

    def test_deserialize_too_large(self):
        if not DILL_AVAILABLE:
            pytest.skip("dill not installed")
        ds = DillSerializer()
        big_data = b"x" * (DEFAULT_MAX_SIZE + 1)
        with pytest.raises(ValueError, match="Data too large"):
            ds.deserialize(big_data)

    def test_deserialize_exact_max_size(self):
        if not DILL_AVAILABLE:
            pytest.skip("dill not installed")
        ds = DillSerializer()
        obj = "test"
        data = ds.serialize(obj)
        assert ds.deserialize(data, max_size=len(data)) == obj

    def test_deserialize_corrupt_data(self):
        if not DILL_AVAILABLE:
            pytest.skip("dill not installed")
        ds = DillSerializer()
        with pytest.raises(Exception):
            ds.deserialize(b"not valid serialized data")


class TestDillSerializerGetState:
    def test_getstate_with_getstate_method(self):
        if not DILL_AVAILABLE:
            pytest.skip("dill not installed")
        ds = DillSerializer()

        class HasGetState:
            def __getstate__(self):
                return {"value": 42}

        obj = HasGetState()
        state = ds.get_state(obj)
        assert state == {"value": 42}

    def test_getstate_with_dict_only(self):
        if not DILL_AVAILABLE:
            pytest.skip("dill not installed")
        ds = DillSerializer()

        class HasDict:
            def __init__(self):
                self.x = 1
                self.y = "hello"

        obj = HasDict()
        state = ds.get_state(obj)
        assert state == {"x": 1, "y": "hello"}

    def test_getstate_getstate_returns_non_dict(self):
        if not DILL_AVAILABLE:
            pytest.skip("dill not installed")
        ds = DillSerializer()

        class NonDictGetState:
            def __getstate__(self):
                return "not a dict"
            def __init__(self):
                self.x = 1

        obj = NonDictGetState()
        state = ds.get_state(obj)
        assert state == {"x": 1}

    def test_getstate_no_getstate_no_dict(self):
        if not DILL_AVAILABLE:
            pytest.skip("dill not installed")
        ds = DillSerializer()

        class Minimal:
            __slots__ = []

        obj = Minimal()
        state = ds.get_state(obj)
        assert state == {}


class TestDummyDillFallback:
    def test_dummy_dill_dumps_raises(self):
        if DILL_AVAILABLE:
            pytest.skip("dill is installed")
        from dhara.serialize.dill import dill
        with pytest.raises(ImportError):
            dill.dumps({})

    def test_dummy_dill_loads_raises(self):
        if DILL_AVAILABLE:
            pytest.skip("dill is installed")
        from dhara.serialize.dill import dill
        with pytest.raises(ImportError):
            dill.loads(b"data")

    def test_dummy_has_default_protocol(self):
        if DILL_AVAILABLE:
            pytest.skip("dill is installed")
        from dhara.serialize.dill import dill
        assert hasattr(dill, "DEFAULT_PROTOCOL")
