"""Extended coverage tests for ``dhara.serialize.msgpack`` and
``dhara.serialize.msgspec``.

These two modules share the same coverage target (>=95%) and the same
``Serializer`` base class, so they're paired into a single file.

Baseline (before this file):
    dhara/serialize/msgpack.py   21 stmts  48%
    dhara/serialize/msgspec.py   69 stmts  43%

After this file each module must reach >=95%.

Production code is frozen, so these tests only exercise existing
behavior — they don't add new assertions about product contracts.
"""

from __future__ import annotations

import datetime
from typing import Any

import pytest

from dhara.core.persistent import Persistent, PersistentObject, _setattribute
from dhara.serialize.base import DEFAULT_MAX_SIZE, Serializer
from dhara.serialize.msgpack import MsgpackSerializer
from dhara.serialize.msgspec import (
    DEFAULT_ALLOWED_MODULES,
    MsgspecSerializer,
    _persistent_enc_hook,
)


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


class _LocalPersistent(Persistent):
    """Persistent subclass living in this test module.

    ``_setattribute`` (not ``self.attr = ...``) bypasses the
    change-tracking ``__setattr__`` so the test setup doesn't need a
    real Connection. The class inherits ``__module__`` from this test
    module automatically (we deliberately do NOT pin ``__module__`` to a
    fully-qualified package path — the wire format then uses the same
    module name pytest reports as ``__name__``, so the whitelist can
    include ``{__name__}``).
    """

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            _setattribute(self, k, v)


@pytest.fixture
def persistent_factory() -> Any:
    """Return a factory for ``_LocalPersistent`` instances seeded with ``kwargs``."""

    def _make(**kwargs: Any) -> _LocalPersistent:
        inst = _LocalPersistent.__new__(_LocalPersistent)
        # PersistentBase.__new__ already populated _p_status/_p_serial/
        # _p_connection/_p_oid; just fill the user-visible slots via
        # the bypass path so we don't need a real Connection.
        for k, v in kwargs.items():
            _setattribute(inst, k, v)
        return inst

    return _make


# ---------------------------------------------------------------------------
# MsgpackSerializer
# ---------------------------------------------------------------------------


class TestMsgpackSerializerInit:
    """Constructor invariants."""

    def test_no_args_constructs(self) -> None:
        s = MsgpackSerializer()
        assert isinstance(s, Serializer)

    def test_underlying_msgspec_uses_msgpack_format(self) -> None:
        s = MsgpackSerializer()
        assert s._msgspec.format == "msgpack"

    def test_underlying_msgspec_uses_builtins(self) -> None:
        s = MsgpackSerializer()
        assert s._msgspec.use_builtins is True


class TestMsgpackSerializerSerialize:
    """``serialize`` produces msgpack-formatted bytes."""

    def test_returns_bytes(self) -> None:
        s = MsgpackSerializer()
        out = s.serialize({"a": 1})
        assert isinstance(out, bytes)

    def test_round_trip_dict(self) -> None:
        s = MsgpackSerializer()
        payload = {"a": 1, "b": [2, 3, 4], "c": "hello"}
        assert s.deserialize(s.serialize(payload)) == payload

    def test_round_trip_nested(self) -> None:
        s = MsgpackSerializer()
        payload = {"users": [{"name": "alice"}, {"name": "bob"}]}
        assert s.deserialize(s.serialize(payload)) == payload

    def test_round_trip_unicode(self) -> None:
        s = MsgpackSerializer()
        payload = {"emoji": "✅", "chinese": "你好"}
        assert s.deserialize(s.serialize(payload)) == payload


class TestMsgpackSerializerDeserialize:
    """``deserialize`` recovers the original object."""

    def test_round_trip_list(self) -> None:
        s = MsgpackSerializer()
        assert s.deserialize(s.serialize([1, 2, 3])) == [1, 2, 3]

    def test_round_trip_primitive(self) -> None:
        s = MsgpackSerializer()
        assert s.deserialize(s.serialize(42)) == 42

    def test_round_trip_none(self) -> None:
        s = MsgpackSerializer()
        assert s.deserialize(s.serialize(None)) is None

    def test_size_limit_enforced(self) -> None:
        """Data larger than ``max_size`` triggers ``ValueError`` (line 51)."""
        s = MsgpackSerializer()
        small_payload = b"\x00" * 8
        with pytest.raises(ValueError, match="Data too large"):
            s.deserialize(small_payload, max_size=4)

    def test_size_limit_at_boundary_passes(self) -> None:
        """Equal to max_size is allowed; only strictly greater raises."""
        s = MsgpackSerializer()
        payload = {"x": 1}
        data = s.serialize(payload)
        # Data must be <= max_size (don't know exact length, so pick a
        # generous bound that's known to be >= len(data)).
        s.deserialize(data, max_size=len(data))
        s.deserialize(data, max_size=len(data) + 1)

    def test_default_max_size(self) -> None:
        """Default ``max_size`` is the base class default (100MB)."""
        import inspect

        sig = inspect.signature(MsgpackSerializer.deserialize)
        assert sig.parameters["max_size"].default == DEFAULT_MAX_SIZE


class TestMsgpackSerializerGetState:
    """``get_state`` branches (lines 64-74)."""

    def test_uses_getstate_when_returns_dict(
        self, persistent_factory: Any
    ) -> None:
        s = MsgpackSerializer()
        obj = persistent_factory(value=42, name="alice")
        state = s.get_state(obj)
        assert state == {"value": 42, "name": "alice"}

    def test_falls_back_to_getstate_returning_non_dict(
        self, persistent_factory: Any
    ) -> None:
        """If ``__getstate__`` returns a non-dict, the code falls through
        to ``__dict__``."""
        s = MsgpackSerializer()

        class _Obj:
            def __getstate__(self) -> str:  # type: ignore[override]
                return "not a dict"

            def __init__(self) -> None:
                self.alpha = 1

        assert s.get_state(_Obj()) == {"alpha": 1}

    def test_falls_back_to_dict_when_no_getstate(self) -> None:
        """Object without ``__getstate__`` falls through to ``__dict__``."""
        s = MsgpackSerializer()

        class _Obj:
            def __init__(self) -> None:
                self.alpha = 1
                self.beta = "two"

        assert s.get_state(_Obj()) == {"alpha": 1, "beta": "two"}

    def test_returns_empty_dict_when_neither_available(self) -> None:
        """Object with neither ``__getstate__`` nor ``__dict__`` -> {}."""
        s = MsgpackSerializer()

        class _Slotted:
            __slots__ = ["v"]

            def __init__(self) -> None:
                # Bypass ``__setattr__`` on the class — but our class has
                # no __setattr__ override, so plain assignment is fine.
                self.v = 1

        # ``_Slotted`` has __slots__=["v"] and no __dict__, no __getstate__.
        # Its only attributes are reachable via slots, not via __dict__.
        # The serializer's fallback path returns {} in that case.
        assert s.get_state(_Slotted()) == {}


# ---------------------------------------------------------------------------
# MsgspecSerializer
# ---------------------------------------------------------------------------


@pytest.fixture
def msgspec_serializer() -> MsgspecSerializer:
    """Default MsgspecSerializer (msgpack format, use_builtins=True)."""
    return MsgspecSerializer()


class TestMsgspecSerializerInit:
    """Constructor variants."""

    def test_default_format_is_msgpack(self) -> None:
        s = MsgspecSerializer()
        assert s.format == "msgpack"

    def test_json_format(self) -> None:
        s = MsgspecSerializer(format="json")
        assert s.format == "json"

    def test_use_builtins_default_true(self) -> None:
        s = MsgspecSerializer()
        assert s.use_builtins is True

    def test_use_builtins_false(self) -> None:
        s = MsgspecSerializer(use_builtins=False)
        assert s.use_builtins is False

    def test_default_allowed_modules_is_copy_not_reference(self) -> None:
        """Two default serializers must own independent sets."""
        a = MsgspecSerializer()
        b = MsgspecSerializer()
        a.allowed_modules.add("evil.injected")
        assert "evil.injected" not in b.allowed_modules

    def test_custom_allowed_modules_used(self) -> None:
        custom = {"dhara", "collections"}
        s = MsgspecSerializer(allowed_modules=custom)
        assert s.allowed_modules == custom

    def test_custom_allowed_modules_takes_set_copy(self) -> None:
        """Passing a set in yields a set (not the original reference)."""
        custom = {"dhara"}
        s = MsgspecSerializer(allowed_modules=custom)
        # Mutating the original must not affect the serializer.
        custom.add("foo")
        assert "foo" not in s.allowed_modules

    def test_default_allowed_modules_contains_core(self) -> None:
        s = MsgspecSerializer()
        # DEFAULT_ALLOWED_MODULES is what the constructor copies from.
        assert "dhara.core.persistent" in s.allowed_modules
        assert "dhara.collections.dict" in s.allowed_modules
        assert "collections" in s.allowed_modules


class TestMsgspecSerializerEncodeDecodeRoundTrip:
    """Format-specific round-trips."""

    def test_msgpack_round_trip_dict(self, msgspec_serializer: MsgspecSerializer) -> None:
        payload = {"a": 1, "b": [2, 3]}
        data = msgspec_serializer.serialize(payload)
        assert isinstance(data, bytes)
        assert msgspec_serializer.deserialize(data) == payload

    def test_msgpack_round_trip_unicode(
        self, msgspec_serializer: MsgspecSerializer
    ) -> None:
        payload = {"emoji": "✅", "ja": "こんにちは"}
        assert msgspec_serializer.deserialize(msgspec_serializer.serialize(payload)) == payload

    def test_json_format_round_trip(self) -> None:
        s = MsgspecSerializer(format="json")
        payload = {"x": [1, 2, 3], "y": "hello"}
        data = s.serialize(payload)
        assert isinstance(data, bytes)
        assert s.deserialize(data) == payload

    def test_json_format_use_builtins_off(self) -> None:
        s = MsgspecSerializer(format="json", use_builtins=False)
        payload = {"a": 1, "b": [2, 3]}
        assert s.deserialize(s.serialize(payload)) == payload

    def test_msgpack_format_use_builtins_off(self) -> None:
        s = MsgspecSerializer(format="msgpack", use_builtins=False)
        payload = {"a": 1, "b": [2, 3]}
        assert s.deserialize(s.serialize(payload)) == payload

    def test_datetime_round_trip(self) -> None:
        """Datetime is a built-in msgspec type — survives the wire."""
        s = MsgspecSerializer()
        dt = datetime.datetime(2024, 1, 2, 3, 4, 5)
        out = s.deserialize(s.serialize(dt))
        # msgspec normalises datetime to ISO-8601 string; both branches
        # (use_builtins=True and =False) produce the same wire format
        # for native built-in types like datetime.
        assert out == "2024-01-02T03:04:05"


class TestMsgspecSerializerSerializeBranches:
    """``serialize`` dispatch table."""

    def test_use_builtins_false_skips_to_builtins(
        self, msgspec_serializer: MsgspecSerializer
    ) -> None:
        """When ``use_builtins=False``, the path bypasses ``to_builtins``
        entirely (covers the ``156->163`` branch)."""
        # Patch to_builtins to confirm it is NOT called.
        from unittest.mock import patch

        from dhara.serialize import msgspec as msgspec_mod

        with patch.object(msgspec_mod, "to_builtins") as mocked:
            s = MsgspecSerializer(use_builtins=False)
            s.serialize({"a": 1})
        assert not mocked.called

    def test_use_builtins_true_calls_to_builtins(
        self, msgspec_serializer: MsgspecSerializer
    ) -> None:
        from unittest.mock import patch

        from dhara.serialize import msgspec as msgspec_mod

        with patch.object(msgspec_mod, "to_builtins", wraps=msgspec_mod.to_builtins) as mocked:
            s = MsgspecSerializer()
            s.serialize({"a": 1})
        assert mocked.called


class TestPersistentEncHook:
    """The ``enc_hook`` callback (lines 75-88)."""

    def test_persistent_object_returns_wire_dict(
        self, persistent_factory: Any
    ) -> None:
        p = persistent_factory(value=42)
        out = _persistent_enc_hook(p)
        assert out == {
            "__class__": f"{_LocalPersistent.__module__}._LocalPersistent",
            "__state__": {"value": 42},
        }

    def test_persistent_object_with_none_state_normalized_to_empty_dict(
        self,
    ) -> None:
        """``__getstate__()`` returning ``None`` becomes ``{}`` on the wire."""

        class _GhostPersistent(PersistentObject):
            # No explicit __module__ — inherits this test module's name.
            def __getstate__(self) -> dict[str, Any] | None:  # type: ignore[override]
                return None

        obj = _GhostPersistent.__new__(_GhostPersistent)
        out = _persistent_enc_hook(obj)
        assert out["__state__"] == {}

    def test_non_persistent_raises_not_implemented(self) -> None:
        """The ``else`` branch of the hook raises ``NotImplementedError``."""
        with pytest.raises(NotImplementedError):
            _persistent_enc_hook(object())

    def test_uses_dunder_name_not_qualname(
        self, persistent_factory: Any
    ) -> None:
        """The wire format uses ``__name__`` (so nested-class qualnames
        like ``Outer.Inner`` would NOT appear)."""

        def _factory() -> Any:
            class _Inner(Persistent):
                pass

            return _Inner

        nested_cls = _factory()
        # Sanity-check that __name__ and __qualname__ differ.
        assert nested_cls.__name__ == "_Inner"
        assert "." in nested_cls.__qualname__

        inst = nested_cls.__new__(nested_cls)
        out = _persistent_enc_hook(inst)
        # The encoded __class__ ends with "._Inner" (using __name__).
        assert out["__class__"].endswith("._Inner")
        # And the full qualname (which would include the outer scope)
        # is NOT in the encoded value.
        assert nested_cls.__qualname__ not in out["__class__"]


class TestMsgspecSerializerSerializePersistent:
    """``serialize`` walks through Persistent instances at any depth."""

    def test_top_level_persistent_round_trip(
        self, persistent_factory: Any
    ) -> None:
        s = MsgspecSerializer(
            allowed_modules=DEFAULT_ALLOWED_MODULES | {_LocalPersistent.__module__}
        )
        p = persistent_factory(value=42, label="hello")
        data = s.serialize(p)
        out = s.deserialize(data)
        assert isinstance(out, _LocalPersistent)
        assert out.value == 42
        assert out.label == "hello"

    def test_nested_persistent_in_dict(self, persistent_factory: Any) -> None:
        """The enc_hook fires for Persistent instances nested inside
        larger structures (not only at the top level).

        Note: the current ``deserialize`` only reconstructs the TOP-level
        object. Nested Persistents are left as their wire-format dict
        (``{"__class__", "__state__"}``) by design — confirming the
        enc_hook ran on every Persistent, not just the outermost one."""
        s = MsgspecSerializer(
            allowed_modules=DEFAULT_ALLOWED_MODULES | {_LocalPersistent.__module__}
        )
        outer = {"inner": persistent_factory(value=7), "scalar": "x"}
        data = s.serialize(outer)
        out = s.deserialize(data)
        assert out["scalar"] == "x"
        # The nested Persistent was encoded via the enc_hook (see wire
        # dict shape), but the top-level-only deserializer leaves it as a
        # plain dict rather than re-instantiating it.
        assert out["inner"] == {
            "__class__": f"{_LocalPersistent.__module__}._LocalPersistent",
            "__state__": {"value": 7},
        }
        assert not isinstance(out["inner"], _LocalPersistent)

    def test_nested_persistent_in_list(self, persistent_factory: Any) -> None:
        """Same wire-format observation for list nesting."""
        s = MsgspecSerializer(
            allowed_modules=DEFAULT_ALLOWED_MODULES | {_LocalPersistent.__module__}
        )
        payload = [persistent_factory(value=1), persistent_factory(value=2)]
        data = s.serialize(payload)
        out = s.deserialize(data)
        # Both entries left as plain dicts (top-level-only deserializer).
        assert out[0] == {
            "__class__": f"{_LocalPersistent.__module__}._LocalPersistent",
            "__state__": {"value": 1},
        }
        assert out[1] == {
            "__class__": f"{_LocalPersistent.__module__}._LocalPersistent",
            "__state__": {"value": 2},
        }


class TestMsgspecSerializerDeserializeBranches:
    """``deserialize`` control flow."""

    def test_size_limit_enforced(self) -> None:
        s = MsgspecSerializer()
        # Anything larger than max_size should raise.
        with pytest.raises(ValueError, match="Data too large"):
            s.deserialize(b"\x00" * 8, max_size=4)

    def test_dict_without_class_field_passes_through(self) -> None:
        """A regular dict (no ``__class__``) round-trips as a plain dict."""
        s = MsgspecSerializer()
        payload = {"a": 1, "b": "two"}
        assert s.deserialize(s.serialize(payload)) == payload

    def test_dict_with_class_but_no_state_passes_through(self) -> None:
        """``__class__`` present, ``__state__`` missing -> no reconstruction."""
        s = MsgspecSerializer()
        raw = s.serialize({"__class__": "anything", "x": 1})
        out = s.deserialize(raw)
        assert out == {"__class__": "anything", "x": 1}

    def test_class_without_dot_passes_through(self) -> None:
        """``__class__`` without a dot can't be split into module/name."""
        s = MsgspecSerializer()
        raw = s.serialize({"__class__": "no_dot_class", "__state__": {"x": 1}})
        out = s.deserialize(raw)
        assert out == {"__class__": "no_dot_class", "__state__": {"x": 1}}

    def test_module_not_in_whitelist_rejected(self) -> None:
        """Disallowed module -> ``ValueError``."""
        s = MsgspecSerializer(allowed_modules=set())  # nothing allowed
        raw = s.serialize(
            {"__class__": "collections.OrderedDict", "__state__": {}}
        )
        with pytest.raises(ValueError, match="not allowed"):
            s.deserialize(raw)

    def test_module_not_in_whitelist_logs_error(self) -> None:
        """The error path uses ``logger.error`` (covered by the previous
        test; this one checks the error message includes 'whitelist')."""
        s = MsgspecSerializer(allowed_modules={"dhara"})
        raw = s.serialize(
            {"__class__": "collections.OrderedDict", "__state__": {}}
        )
        with pytest.raises(ValueError) as excinfo:
            s.deserialize(raw)
        assert "whitelist" in str(excinfo.value).lower()

    def test_unknown_class_in_whitelisted_module_raises(self) -> None:
        """Module is allowed, but the class doesn't exist there."""
        s = MsgspecSerializer()
        raw = s.serialize(
            {"__class__": "collections.NotARealClass", "__state__": {}}
        )
        with pytest.raises(ValueError, match="Failed to import class"):
            s.deserialize(raw)

    def test_import_error_chain_preserved(self) -> None:
        """The ValueError chains to the original ImportError/AttributeError."""
        s = MsgspecSerializer()
        raw = s.serialize(
            {"__class__": "collections.NotARealClass", "__state__": {}}
        )
        with pytest.raises(ValueError) as excinfo:
            s.deserialize(raw)
        assert excinfo.value.__cause__ is not None

    def test_class_not_persistent_subclass_rejected(self) -> None:
        """Module is allowed, class resolves, but it's not Persistent-derived."""
        s = MsgspecSerializer()
        raw = s.serialize(
            {"__class__": "collections.OrderedDict", "__state__": {}}
        )
        with pytest.raises(ValueError, match="not a Persistent subclass"):
            s.deserialize(raw)

    def test_class_not_persistent_chains_log_error(self) -> None:
        s = MsgspecSerializer()
        raw = s.serialize(
            {"__class__": "collections.OrderedDict", "__state__": {}}
        )
        with pytest.raises(ValueError) as excinfo:
            s.deserialize(raw)
        assert "Persistent" in str(excinfo.value)

    def test_state_none_coerced_to_empty_dict(
        self, persistent_factory: Any
    ) -> None:
        """``__state__`` is ``None`` -> coerced to ``{}`` on the wire, and
        the reconstructed instance has empty ``__dict__``."""
        s = MsgspecSerializer(
            allowed_modules=DEFAULT_ALLOWED_MODULES | {_LocalPersistent.__module__}
        )
        # Persistent.__getstate__ returns __dict__, which is empty by
        # default — so encode a payload with __state__=None directly.
        # Use ``_LocalPersistent.__module__`` so the whitelist matches
        # regardless of pytest's import-mode for the test module.
        raw = s.serialize(
            {
                "__class__": f"{_LocalPersistent.__module__}._LocalPersistent",
                "__state__": None,
            }
        )
        out = s.deserialize(raw)
        assert isinstance(out, _LocalPersistent)
        # Reconstruction set __dict__ to {}; no user attributes present.
        assert out.__dict__ == {}


class TestMsgspecSerializerDecodeRaw:
    """``decode_raw`` (lines 243-255)."""

    def test_returns_decoded_object(self, msgspec_serializer: MsgspecSerializer) -> None:
        data = msgspec_serializer.serialize({"a": 1, "b": [2, 3]})
        out = msgspec_serializer.decode_raw(data)
        assert out == {"a": 1, "b": [2, 3]}

    def test_does_not_reconstruct_persistent(
        self, msgspec_serializer: MsgspecSerializer
    ) -> None:
        """``decode_raw`` must NOT instantiate the class — that is the
        caller's responsibility (gated by ``allowed_modules``)."""
        raw = msgspec_serializer.serialize(
            {"__class__": "collections.OrderedDict", "__state__": {"a": 1}}
        )
        # Use a serializer whose allowed_modules would otherwise reject
        # ``collections`` — decode_raw must bypass that check entirely.
        restrictive = MsgspecSerializer(allowed_modules={"dhara"})
        out = restrictive.decode_raw(raw)
        assert out == {"__class__": "collections.OrderedDict", "__state__": {"a": 1}}

    def test_size_limit_enforced(self, msgspec_serializer: MsgspecSerializer) -> None:
        with pytest.raises(ValueError, match="Data too large"):
            msgspec_serializer.decode_raw(b"\x00" * 8, max_size=4)

    def test_default_max_size_is_100mb(self, msgspec_serializer: MsgspecSerializer) -> None:
        import inspect

        sig = inspect.signature(msgspec_serializer.decode_raw)
        assert sig.parameters["max_size"].default == DEFAULT_MAX_SIZE


class TestMsgspecSerializerGetState:
    """``get_state`` (lines 257-275)."""

    def test_with_use_builtins_true_returns_builtin_dict(
        self, persistent_factory: Any
    ) -> None:
        s = MsgspecSerializer()
        p = persistent_factory(value=42, label="hello")
        state = s.get_state(p)
        # ``to_builtins`` is called with str_keys=True, so all keys are
        # strings (which is already the case here).
        assert state == {"value": 42, "label": "hello"}

    def test_with_use_builtins_false_returns_raw_state(
        self, persistent_factory: Any
    ) -> None:
        s = MsgspecSerializer(use_builtins=False)
        p = persistent_factory(value=42, label="hello")
        state = s.get_state(p)
        assert state == {"value": 42, "label": "hello"}

    def test_use_builtins_true_does_not_use_enc_hook_to_builtins(
        self, persistent_factory: Any
    ) -> None:
        """``get_state`` calls ``to_builtins`` internally; verify it passes."""
        from unittest.mock import patch

        from dhara.serialize import msgspec as msgspec_mod

        s = MsgspecSerializer()
        p = persistent_factory(value=42)
        with patch.object(
            msgspec_mod, "to_builtins", wraps=msgspec_mod.to_builtins
        ) as mocked:
            s.get_state(p)
        assert mocked.called

    def test_use_builtins_false_skips_to_builtins(
        self, persistent_factory: Any
    ) -> None:
        from unittest.mock import patch

        from dhara.serialize import msgspec as msgspec_mod

        s = MsgspecSerializer(use_builtins=False)
        p = persistent_factory(value=42)
        with patch.object(msgspec_mod, "to_builtins") as mocked:
            s.get_state(p)
        assert not mocked.called

    def test_get_state_with_none_state_returns_none_or_empty(
        self,
    ) -> None:
        """A Persistent subclass whose ``__getstate__`` returns ``None``
        (e.g. ``ComputedAttribute``) flows through both branches."""
        from dhara.core.persistent import ComputedAttribute

        s = MsgspecSerializer()
        ca = ComputedAttribute.__new__(ComputedAttribute)
        # ComputedAttribute.__getstate__ returns None.
        state = s.get_state(ca)
        # With use_builtins=True, None flows through to_builtins.
        assert state is None
