"""Tests for msgspec-based serializer."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from dhara.core.persistent import Persistent, _setattribute
from dhara.serialize.base import DEFAULT_MAX_SIZE, Serializer, SerializerProtocol
from dhara.serialize.msgspec import DEFAULT_ALLOWED_MODULES, MsgspecSerializer


# Module-level Persistent subclass for use in tests.
# Must be at module level so deserialization can find it by qualified name.


class _TestPersistent(Persistent):
    """Minimal Persistent subclass for testing serialization."""

    def __init__(self, value=0):
        self.value = value

    def __getstate__(self):
        return {"value": self.value}

    def __setstate__(self, state):
        self.value = state.get("value", 0)


# A non-Persistent class used to test rejection during deserialization.
class _NonPersistentClass:
    pass


# Dangerous module names used in security tests (strings only, never called).
_DANGEROUS_MODULE = "subprocess.check_output"
_DANGEROUS_MODULE_2 = "os.system"


# ============================================================================
# Constructor
# ============================================================================


class TestMsgspecConstructor:
    """Tests for MsgspecSerializer initialization."""

    def test_default_format_is_msgpack(self):
        s = MsgspecSerializer()
        assert s.format == "msgpack"

    def test_json_format(self):
        s = MsgspecSerializer(format="json")
        assert s.format == "json"

    def test_use_builtins_default_true(self):
        s = MsgspecSerializer()
        assert s.use_builtins is True

    def test_use_builtins_false(self):
        s = MsgspecSerializer(use_builtins=False)
        assert s.use_builtins is False

    def test_default_allowed_modules(self):
        s = MsgspecSerializer()
        assert "dhara" in s.allowed_modules
        assert "builtins" in s.allowed_modules
        assert "collections" in s.allowed_modules

    def test_custom_allowed_modules(self):
        custom = {"myapp", "builtins"}
        s = MsgspecSerializer(allowed_modules=custom)
        assert s.allowed_modules == custom

    def test_allowed_modules_is_copy_not_reference(self):
        s1 = MsgspecSerializer()
        s2 = MsgspecSerializer()
        s1.allowed_modules.add("custom_module")
        assert "custom_module" not in s2.allowed_modules

    def test_msgpack_uses_msgpack_encode_decode(self):
        s = MsgspecSerializer(format="msgpack")
        assert callable(s._encode)
        assert callable(s._decode)

    def test_json_uses_json_encode_decode(self):
        s = MsgspecSerializer(format="json")
        assert callable(s._encode)
        assert callable(s._decode)

    def test_msgpack_and_json_have_different_encoders(self):
        s_mp = MsgspecSerializer(format="msgpack")
        s_js = MsgspecSerializer(format="json")
        assert s_mp._encode is not s_js._encode
        assert s_mp._decode is not s_js._decode


# ============================================================================
# Serialize - basic types
# ============================================================================


class TestMsgspecSerializeBasic:
    """Tests for serializing basic Python types."""

    @pytest.mark.parametrize(
        "obj",
        [
            None,
            True,
            False,
            42,
            -100,
            0,
            3.14,
            -0.001,
            "",
            "hello world",
        ],
        ids=[
            "none", "true", "false", "int_pos", "int_neg", "int_zero",
            "float_pos", "float_neg", "empty_str", "str_ascii",
        ],
    )
    def test_serialize_basic_types(self, obj):
        s = MsgspecSerializer()
        data = s.serialize(obj)
        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_serialize_dict(self):
        s = MsgspecSerializer()
        data = s.serialize({"key": "value"})
        assert isinstance(data, bytes)

    def test_serialize_list(self):
        s = MsgspecSerializer()
        data = s.serialize([1, 2, 3])
        assert isinstance(data, bytes)

    def test_serialize_empty_dict(self):
        s = MsgspecSerializer()
        data = s.serialize({})
        assert isinstance(data, bytes)

    def test_serialize_empty_list(self):
        s = MsgspecSerializer()
        data = s.serialize([])
        assert isinstance(data, bytes)

    def test_serialize_nested_structures(self):
        s = MsgspecSerializer()
        obj = {
            "level1": {
                "level2": {
                    "level3": [1, 2, {"deep": "value"}]
                }
            }
        }
        data = s.serialize(obj)
        assert isinstance(data, bytes)
        result = s.deserialize(data)
        assert result == obj


# ============================================================================
# Serialize - Persistent objects
# ============================================================================


class TestMsgspecSerializePersistent:
    """Tests for serializing Persistent objects with use_builtins.

    These tests verify the serialized *format* (dict with __class__ and __state__).
    They use raw msgpack decode to inspect the bytes without triggering
    Persistent object reconstruction (which requires the test module in allowed_modules).
    """

    def _raw_decode(self, s, data):
        """Decode serialized bytes using the raw decoder (no Persistent reconstruction)."""
        return s._decode(data)

    def test_persistent_converts_to_class_dict(self):
        """Persistent object is converted to {__class__: ..., __state__: ...} dict."""
        s = MsgspecSerializer(use_builtins=True)
        obj = _TestPersistent(value=42)
        data = s.serialize(obj)

        result = self._raw_decode(s, data)
        assert isinstance(result, dict)
        assert "__class__" in result
        assert "__state__" in result
        assert result["__state__"] == {"value": 42}

    def test_persistent_class_name_format(self):
        """__class__ field uses module.class format."""
        s = MsgspecSerializer(use_builtins=True)
        obj = _TestPersistent(value=99)
        data = s.serialize(obj)
        result = self._raw_decode(s, data)

        class_name = result["__class__"]
        assert class_name.endswith("_TestPersistent")
        assert "." in class_name

    def test_persistent_uses_getstate(self):
        """Persistent serialization uses __getstate__ for the state."""
        s = MsgspecSerializer(use_builtins=True)
        obj = _TestPersistent(value=7)
        data = s.serialize(obj)
        result = self._raw_decode(s, data)
        assert result["__state__"] == {"value": 7}

    def test_persistent_with_to_builtins(self):
        """State is converted through to_builtins when use_builtins=True."""
        s = MsgspecSerializer(use_builtins=True)
        obj = _TestPersistent(value=42)
        data = s.serialize(obj)
        result = self._raw_decode(s, data)
        assert isinstance(result, dict)
        assert result["__state__"] == {"value": 42}


# ============================================================================
# Serialize without use_builtins
# ============================================================================


class TestMsgspecSerializeNoBuiltins:
    """Tests for serializing with use_builtins=False."""

    def test_raw_encoding_basic_types(self):
        """Without use_builtins, basic types still serialize correctly."""
        s = MsgspecSerializer(use_builtins=False)
        obj = {"key": "value", "number": 42}
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result == obj

    def test_raw_encoding_does_not_convert_persistent(self):
        """Without use_builtins, Persistent objects fail to serialize."""
        s = MsgspecSerializer(use_builtins=False)
        obj = _TestPersistent(value=42)
        with pytest.raises((TypeError, AttributeError)):
            s.serialize(obj)


# ============================================================================
# Roundtrip serialization
# ============================================================================


class TestMsgspecRoundtrip:
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
            "",
            "hello world",
            [],
            [1, 2, 3],
            {},
            {"key": "value"},
            {"nested": {"a": 1, "b": [2, 3]}},
            [None, True, 42, "mixed", {"dict": "in_list"}],
        ],
        ids=[
            "none", "true", "false", "int", "neg_int",
            "float", "empty_str", "str", "empty_list",
            "list_ints", "empty_dict", "dict", "nested",
            "mixed_list",
        ],
    )
    def test_roundtrip_primitives(self, obj):
        s = MsgspecSerializer()
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result == obj

    def test_large_dict_roundtrip(self):
        s = MsgspecSerializer()
        obj = {f"key_{i}": f"value_{i}" for i in range(1000)}
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result == obj

    def test_unicode_roundtrip(self):
        s = MsgspecSerializer()
        obj = {"unicode_test": "test string"}
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result == obj

    def test_empty_bytes_serialize(self):
        s = MsgspecSerializer()
        data = s.serialize({})
        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_roundtrip_preserves_types(self):
        s = MsgspecSerializer()
        obj = {"int": 42, "float": 3.14, "bool": True, "none": None}
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert type(result["int"]) is int
        assert type(result["float"]) is float
        assert type(result["bool"]) is bool
        assert result["none"] is None

    def test_roundtrip_deeply_nested(self):
        s = MsgspecSerializer()
        obj = {"a": {"b": {"c": {"d": [1, 2, {"e": "deep"}]}}}}
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result == obj

    def test_roundtrip_list_of_dicts(self):
        s = MsgspecSerializer()
        obj = [{"name": "a", "val": 1}, {"name": "b", "val": 2}]
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result == obj


# ============================================================================
# Deserialize - size limit check
# ============================================================================


class TestMsgspecSizeValidation:
    """Tests for max_size enforcement."""

    def test_deserialize_respects_max_size(self):
        s = MsgspecSerializer()
        obj = {"key": "value"}
        data = s.serialize(obj)
        with pytest.raises(ValueError, match="too large"):
            s.deserialize(data, max_size=1)

    def test_deserialize_at_exact_size_ok(self):
        s = MsgspecSerializer()
        obj = {"key": "value"}
        data = s.serialize(obj)
        result = s.deserialize(data, max_size=len(data))
        assert result == obj

    def test_deserialize_default_max_size(self):
        s = MsgspecSerializer()
        obj = {"key": "x" * 100}
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result == obj

    def test_deserialize_uses_default_max_size_constant(self):
        """DEFAULT_MAX_SIZE from base is 100MB."""
        assert DEFAULT_MAX_SIZE == 100 * 1024 * 1024

    def test_deserialize_zero_max_size_rejects_nonempty(self):
        s = MsgspecSerializer()
        data = s.serialize({"a": 1})
        with pytest.raises(ValueError, match="too large"):
            s.deserialize(data, max_size=0)


# ============================================================================
# Deserialize - Persistent object reconstruction
# ============================================================================


class TestMsgspecDeserializePersistent:
    """Tests for deserializing Persistent objects from __class__ dict format."""

    def test_reconstructs_persistent_object(self):
        """Deserialize reconstructs a Persistent object from __class__ dict."""
        s = MsgspecSerializer(
            allowed_modules=DEFAULT_ALLOWED_MODULES | {__name__}
        )
        obj = _TestPersistent(value=42)
        data = s.serialize(obj)
        result = s.deserialize(data)

        assert isinstance(result, _TestPersistent)
        assert result.value == 42

    def test_reconstructed_object_is_persistent_subclass(self):
        """Reconstructed object is a Persistent subclass."""
        s = MsgspecSerializer(
            allowed_modules=DEFAULT_ALLOWED_MODULES | {__name__}
        )
        obj = _TestPersistent(value=10)
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert isinstance(result, Persistent)

    def test_uses_setattribute_for_dict(self):
        """Reconstruction uses _setattribute to set __dict__."""
        s = MsgspecSerializer(
            allowed_modules=DEFAULT_ALLOWED_MODULES | {__name__}
        )
        obj = _TestPersistent(value=55)
        data = s.serialize(obj)

        with patch("dhara.serialize.msgspec._setattribute") as mock_setattr:
            mock_setattr.side_effect = lambda inst, name, val: object.__setattr__(inst, name, val)
            result = s.deserialize(data)
            mock_setattr.assert_called_once()
            call_args = mock_setattr.call_args
            assert call_args[0][1] == "__dict__"
            assert call_args[0][2] == {"value": 55}

    def test_reconstructs_with_different_values(self):
        """Multiple Persistent objects with different values deserialize correctly."""
        s = MsgspecSerializer(
            allowed_modules=DEFAULT_ALLOWED_MODULES | {__name__}
        )
        for val in [0, 1, -1, 999, "string", [1, 2, 3], {"nested": True}]:
            obj = _TestPersistent(value=val)
            data = s.serialize(obj)
            result = s.deserialize(data)
            assert result.value == val

    def test_reconstructs_persistent_with_json_format(self):
        """Persistent reconstruction works with JSON format too."""
        s = MsgspecSerializer(
            format="json",
            allowed_modules=DEFAULT_ALLOWED_MODULES | {__name__}
        )
        obj = _TestPersistent(value=77)
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert isinstance(result, _TestPersistent)
        assert result.value == 77


# ============================================================================
# Deserialize - module whitelist validation
# ============================================================================


class TestMsgspecModuleValidation:
    """Tests for module whitelist enforcement during deserialization."""

    def test_blocked_module_rejected(self):
        """Deserialization of non-whitelisted module is rejected."""
        s = MsgspecSerializer(allowed_modules={"builtins"})
        malicious_data = {
            "__class__": _DANGEROUS_MODULE,
            "__state__": {"args": ["echo", "test"]},
        }
        from msgspec import msgpack

        data = msgpack.encode(malicious_data)
        with pytest.raises(ValueError, match="not allowed"):
            s.deserialize(data)

    def test_disallowed_module_raises_value_error(self):
        """Explicit test: disallowed module raises ValueError."""
        s = MsgspecSerializer(allowed_modules={"builtins"})
        payload = {"__class__": _DANGEROUS_MODULE_2, "__state__": {}}
        from msgspec import msgpack

        data = msgpack.encode(payload)
        with pytest.raises(ValueError, match="not allowed"):
            s.deserialize(data)

    def test_allowed_module_accepts(self):
        """Allowed module does not raise ValueError."""
        s = MsgspecSerializer(
            allowed_modules=DEFAULT_ALLOWED_MODULES | {__name__}
        )
        obj = _TestPersistent(value=1)
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert isinstance(result, _TestPersistent)

    def test_empty_data_allowed(self):
        s = MsgspecSerializer()
        data = s.serialize({})
        result = s.deserialize(data)
        assert result == {}

    def test_builtin_module_allowed(self):
        """builtins module is always allowed."""
        s = MsgspecSerializer()
        assert "builtins" in s.allowed_modules


# ============================================================================
# Deserialize - non-Persistent class validation
# ============================================================================


class TestMsgspecNonPersistentValidation:
    """Tests that non-Persistent classes are rejected during deserialization."""

    def test_non_persistent_class_raises_value_error(self):
        """A class that is not a Persistent subclass is rejected."""
        s = MsgspecSerializer(
            allowed_modules=DEFAULT_ALLOWED_MODULES | {__name__}
        )
        payload = {
            "__class__": f"{__name__}._NonPersistentClass",
            "__state__": {"data": "test"},
        }
        from msgspec import msgpack

        data = msgpack.encode(payload)
        with pytest.raises(ValueError, match="not a Persistent subclass"):
            s.deserialize(data)

    def test_import_failure_raises_value_error(self):
        """If module import fails, ValueError is raised."""
        s = MsgspecSerializer(allowed_modules={"nonexistent_module_xyz"})

        payload = {
            "__class__": "nonexistent_module_xyz.SomeClass",
            "__state__": {},
        }
        from msgspec import msgpack

        data = msgpack.encode(payload)
        with pytest.raises(ValueError, match="Failed to import"):
            s.deserialize(data)

    def test_attribute_error_on_class_raises_value_error(self):
        """If class doesn't exist in module, ValueError is raised."""
        s = MsgspecSerializer(allowed_modules={"builtins"})

        payload = {
            "__class__": "builtins.NonexistentClass",
            "__state__": {},
        }
        from msgspec import msgpack

        data = msgpack.encode(payload)
        with pytest.raises(ValueError, match="Failed to import"):
            s.deserialize(data)

    def test_mock_import_failure(self):
        """Mock __import__ to simulate import failures."""
        s = MsgspecSerializer(allowed_modules={"test_module"})

        payload = {
            "__class__": "test_module.TestClass",
            "__state__": {},
        }
        from msgspec import msgpack

        data = msgpack.encode(payload)

        with patch("builtins.__import__", side_effect=ImportError("mocked")):
            with pytest.raises(ValueError, match="Failed to import"):
                s.deserialize(data)


# ============================================================================
# get_state
# ============================================================================


class TestMsgspecGetState:
    """Tests for get_state method."""

    def test_get_state_returns_dict(self):
        s = MsgspecSerializer()
        obj = _TestPersistent(value=42)
        state = s.get_state(obj)
        assert isinstance(state, dict)
        assert state["value"] == 42

    def test_get_state_extracts_getstate(self):
        """get_state calls __getstate__ on the Persistent object."""
        s = MsgspecSerializer()
        obj = _TestPersistent(value=99)
        state = s.get_state(obj)
        assert state == {"value": 99}

    def test_get_state_with_use_builtins_converts(self):
        """With use_builtins=True, state is converted through to_builtins."""
        s = MsgspecSerializer(use_builtins=True)
        obj = _TestPersistent(value=42)
        state = s.get_state(obj)
        assert isinstance(state, dict)
        assert state == {"value": 42}

    def test_get_state_without_use_builtins_raw(self):
        """With use_builtins=False, state is returned as-is from __getstate__."""
        s = MsgspecSerializer(use_builtins=False)
        obj = _TestPersistent(value=42)
        state = s.get_state(obj)
        assert state == {"value": 42}

    def test_get_state_with_complex_state(self):
        """get_state handles complex state dicts."""
        s = MsgspecSerializer(use_builtins=True)

        class ComplexPersistent(Persistent):
            def __init__(self):
                self.nested = {"a": [1, 2, 3], "b": {"c": "d"}}
                self.items = [True, None, 42]

            def __getstate__(self):
                return {"nested": self.nested, "items": self.items}

            def __setstate__(self, state):
                self.nested = state.get("nested", {})
                self.items = state.get("items", [])

        obj = ComplexPersistent()
        state = s.get_state(obj)
        assert state["nested"] == {"a": [1, 2, 3], "b": {"c": "d"}}
        assert state["items"] == [True, None, 42]


# ============================================================================
# JSON format roundtrip
# ============================================================================


class TestMsgspecJSONFormat:
    """Tests for JSON serialization format."""

    def test_json_format_roundtrip(self):
        s = MsgspecSerializer(format="json")
        obj = {"key": "value", "number": 42}
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result == obj

    def test_json_format_size_validation(self):
        s = MsgspecSerializer(format="json")
        obj = {"key": "value"}
        data = s.serialize(obj)
        with pytest.raises(ValueError, match="too large"):
            s.deserialize(data, max_size=1)

    def test_json_vs_msgpack_both_roundtrip(self):
        """Both formats produce correct roundtrip for the same data."""
        obj = {"int": 42, "str": "hello", "list": [1, 2, 3], "bool": True, "none": None}

        s_mp = MsgspecSerializer(format="msgpack")
        s_js = MsgspecSerializer(format="json")

        data_mp = s_mp.serialize(obj)
        data_js = s_js.serialize(obj)

        assert s_mp.deserialize(data_mp) == obj
        assert s_js.deserialize(data_js) == obj

    def test_json_format_serializes_to_bytes(self):
        s = MsgspecSerializer(format="json")
        data = s.serialize({"key": "value"})
        assert isinstance(data, bytes)

    def test_json_format_different_from_msgpack(self):
        """JSON and msgpack produce different byte representations."""
        s_mp = MsgspecSerializer(format="msgpack")
        s_js = MsgspecSerializer(format="json")
        obj = {"key": "value"}

        data_mp = s_mp.serialize(obj)
        data_js = s_js.serialize(obj)

        assert data_mp != data_js


# ============================================================================
# DEFAULT_ALLOWED_MODULES contents
# ============================================================================


class TestDefaultAllowedModules:
    """Tests for DEFAULT_ALLOWED_MODULES constant."""

    def test_contains_dhara_core(self):
        assert "dhara" in DEFAULT_ALLOWED_MODULES
        assert "dhara.core" in DEFAULT_ALLOWED_MODULES
        assert "dhara.core.persistent" in DEFAULT_ALLOWED_MODULES

    def test_contains_dhara_collections(self):
        assert "dhara.collections" in DEFAULT_ALLOWED_MODULES
        assert "dhara.collections.dict" in DEFAULT_ALLOWED_MODULES
        assert "dhara.collections.list" in DEFAULT_ALLOWED_MODULES
        assert "dhara.collections.set" in DEFAULT_ALLOWED_MODULES
        assert "dhara.collections.btree" in DEFAULT_ALLOWED_MODULES

    def test_contains_standard_library(self):
        assert "collections" in DEFAULT_ALLOWED_MODULES
        assert "collections.abc" in DEFAULT_ALLOWED_MODULES
        assert "builtins" in DEFAULT_ALLOWED_MODULES
        assert "__builtin__" in DEFAULT_ALLOWED_MODULES

    def test_does_not_contain_dangerous_modules(self):
        assert "subprocess" not in DEFAULT_ALLOWED_MODULES
        assert "os" not in DEFAULT_ALLOWED_MODULES
        assert "sys" not in DEFAULT_ALLOWED_MODULES


# ============================================================================
# Interface compliance
# ============================================================================


class TestMsgspecInterface:
    """Tests for Serializer interface compliance."""

    def test_is_serializer(self):
        s = MsgspecSerializer()
        assert isinstance(s, Serializer)

    def test_satisfies_protocol(self):
        s = MsgspecSerializer()
        assert isinstance(s, SerializerProtocol)

    def test_has_required_methods(self):
        s = MsgspecSerializer()
        assert hasattr(s, "serialize")
        assert hasattr(s, "deserialize")
        assert hasattr(s, "get_state")


# ============================================================================
# Edge cases
# ============================================================================


class TestMsgspecEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_serialize_deserialize_large_int(self):
        s = MsgspecSerializer()
        obj = {"big": 2**63}
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result["big"] == 2**63

    def test_serialize_deserialize_negative_float(self):
        s = MsgspecSerializer()
        obj = {"neg": -3.14}
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result["neg"] == -3.14

    def test_serialize_empty_string(self):
        s = MsgspecSerializer()
        data = s.serialize("")
        result = s.deserialize(data)
        assert result == ""

    def test_serialize_zero(self):
        s = MsgspecSerializer()
        data = s.serialize(0)
        result = s.deserialize(data)
        assert result == 0

    def test_deserialize_dict_without_class_field(self):
        """A dict without __class__ is returned as a plain dict."""
        s = MsgspecSerializer()
        data = s.serialize({"normal": "dict"})
        result = s.deserialize(data)
        assert result == {"normal": "dict"}
        assert not isinstance(result, Persistent)

    def test_serialize_list_with_none_elements(self):
        s = MsgspecSerializer()
        obj = [None, None, None]
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result == [None, None, None]

    def test_serialize_dict_with_none_values(self):
        s = MsgspecSerializer()
        obj = {"a": None, "b": None}
        data = s.serialize(obj)
        result = s.deserialize(data)
        assert result == {"a": None, "b": None}
