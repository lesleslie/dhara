"""
Tests for dhara.core.persistent covering previously uncovered lines.

Targeted uncovered lines:
  35, 150, 166, 169, 176, 178, 179, 191-192, 219, 226, 229,
  242-245, 264, 268, 275-276, 285-290
"""

from unittest.mock import MagicMock, patch

import pytest

from dhara.core.persistent import (
    GHOST,
    SAVED,
    UNSAVED,
    ComputedAttribute,
    ConnectionBase,
    Persistent,
    PersistentObject,
    PersistentBase,
    call_if_persistent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _MinimalPersistent(PersistentObject):
    """A concrete PersistentObject subclass for testing __getstate__/__setstate__."""
    __slots__ = ["extra_slot"]

    def __init__(self, extra=None):
        self.extra_slot = extra


class _PersistentWithDict(PersistentObject):
    """A PersistentObject subclass that has __dict__ (via __dict__ in slots)."""
    __slots__ = ["extra_slot", "__dict__"]

    def __init__(self, extra=None):
        self.extra_slot = extra


class _MinimalPersistentWithDict(Persistent):
    """A concrete Persistent (dict-based) subclass."""
    pass


class _MinimalComputed(ComputedAttribute):
    """A concrete ComputedAttribute subclass for testing."""
    pass


# ---------------------------------------------------------------------------
# ConnectionBase
# ---------------------------------------------------------------------------

class TestConnectionBase:

    def test_new_sets_transaction_serial(self):
        conn = ConnectionBase()
        assert conn.transaction_serial == 1

    def test_new_accepts_arbitrary_args(self):
        conn = ConnectionBase("arg1", key="val")
        assert conn.transaction_serial == 1


# ---------------------------------------------------------------------------
# PersistentBase  (pure-Python fallback path)
# ---------------------------------------------------------------------------

class TestPersistentBase:

    def test_new_instance_is_unsaved(self):
        obj = _MinimalPersistent()
        assert obj._p_status == UNSAVED
        assert obj._p_serial == 0
        assert obj._p_connection is None
        assert obj._p_oid is None

    def test_getattr_triggers_load_on_ghost(self):
        """Line 122: __getattribute__ calls _p_load_state when GHOST."""
        obj = _MinimalPersistent()
        obj._p_status = GHOST
        obj._p_connection = MagicMock()
        obj._p_connection.transaction_serial = 1

        # Can't patch on instance (slots), so mock on the class method and
        # track calls via the connection mock side-effect.
        load_called = False
        original_load_state = _MinimalPersistent._p_load_state

        def tracking_load(self_inner):
            nonlocal load_called
            load_called = True
            # Simulate what connection.load_state does: set status to SAVED
            object.__setattr__(self_inner, "_p_status", SAVED)
            object.__setattr__(self_inner, "_p_serial", 1)

        with patch.object(_MinimalPersistent, "_p_load_state", tracking_load):
            obj.extra_slot  # noqa: B018  (intentional access for side effect)
            assert load_called

    def test_getattr_notes_access_on_serial_mismatch(self):
        """Lines 124-128: __getattribute__ calls connection.note_access on mismatch."""
        obj = _MinimalPersistent()
        obj._p_status = SAVED
        obj._p_serial = 0
        obj._p_connection = MagicMock()
        obj._p_connection.transaction_serial = 5

        obj.extra_slot  # noqa: B018
        obj._p_connection.note_access.assert_called_once_with(obj)

    def test_getattr_no_note_access_when_serials_match(self):
        obj = _MinimalPersistent()
        obj._p_status = SAVED
        obj._p_serial = 5
        obj._p_connection = MagicMock()
        obj._p_connection.transaction_serial = 5

        obj.extra_slot  # noqa: B018
        obj._p_connection.note_access.assert_not_called()

    def test_getattr_no_note_access_when_no_connection(self):
        obj = _MinimalPersistent()
        obj._p_status = SAVED
        obj._p_connection = None
        # Should not raise
        obj.extra_slot  # noqa: B018

    def test_setattr_on_non_p_attribute_notes_change(self):
        """Lines 132-134: __setattr__ calls _p_note_change for non-_p_ attrs."""
        note_change_called = False
        original_note_change = _MinimalPersistent._p_note_change

        def tracking_note(self_inner):
            nonlocal note_change_called
            note_change_called = True
            object.__setattr__(self_inner, "_p_status", UNSAVED)
            conn = object.__getattribute__(self_inner, "_p_connection")
            if conn is not None:
                conn.note_change(self_inner)

        obj = _MinimalPersistent()
        obj._p_status = SAVED
        obj._p_connection = MagicMock()

        with patch.object(_MinimalPersistent, "_p_note_change", tracking_note):
            obj.extra_slot = "newval"
            assert note_change_called
        assert obj.extra_slot == "newval"

    def test_setattr_on_p_attribute_skips_note_change(self):
        obj = _MinimalPersistent()
        obj._p_connection = MagicMock()
        obj._p_status = SAVED
        obj._p_serial = 99
        obj._p_oid = "abc"
        obj._p_connection.note_change.assert_not_called()

    def test_setattr_on_ghost_safe_attribute_skips_note_change(self):
        obj = _MinimalPersistent()
        obj._p_connection = MagicMock()
        obj._p_status = SAVED
        # __repr__ and __class__ are in _GHOST_SAFE_ATTRIBUTES
        obj.__class__  # noqa: B018
        obj._p_connection.note_change.assert_not_called()


# ---------------------------------------------------------------------------
# PersistentObject
# ---------------------------------------------------------------------------

class TestPersistentObject:

    # -- __getstate__  (lines 164-172) ----------------------------------

    def test_getstate_on_ghost_calls_load(self):
        """Line 166: __getstate__ calls _p_load_state when GHOST."""
        obj = _MinimalPersistent()
        obj._p_status = GHOST
        obj._p_connection = MagicMock()
        obj._p_connection.transaction_serial = 1

        load_called = False

        def tracking_load(self_inner):
            nonlocal load_called
            load_called = True
            object.__setattr__(self_inner, "_p_status", SAVED)
            object.__setattr__(self_inner, "_p_serial", 1)

        with patch.object(_MinimalPersistent, "_p_load_state", tracking_load):
            obj.__getstate__()
            assert load_called

    def test_getstate_includes_dict_when_present(self):
        """Line 169: __getstate__ updates state from __dict__."""
        obj = _MinimalPersistentWithDict()
        obj.foo = "bar"
        obj._p_status = SAVED
        state = obj.__getstate__()
        assert state["foo"] == "bar"

    def test_getstate_on_ghost_with_dict_calls_load_and_includes_dict(self):
        """Lines 166, 169: __getstate__ on GHOST loads state and includes __dict__."""
        obj = _PersistentWithDict(extra="slot_data")
        obj.foo = "bar"
        obj._p_status = GHOST
        conn = MagicMock()
        conn.transaction_serial = 1

        def fake_load_state(self_inner):
            object.__setattr__(self_inner, "_p_status", SAVED)
            object.__setattr__(self_inner, "_p_serial", 1)

        with patch.object(_PersistentWithDict, "_p_load_state", fake_load_state):
            state = obj.__getstate__()
        # Should include __dict__ contents (line 169)
        assert "foo" in state
        assert state["foo"] == "bar"
        # Should include data slots
        assert state["extra_slot"] == "slot_data"

    def test_getstate_includes_data_slots(self):
        obj = _MinimalPersistent(extra="data")
        obj._p_status = SAVED
        state = obj.__getstate__()
        assert state["extra_slot"] == "data"

    def test_getstate_omits_weakref_and_dict_slots(self):
        """__weakref__ and __dict__ should not appear in state keys from slots."""
        obj = _MinimalPersistent(extra=42)
        obj._p_status = SAVED
        state = obj.__getstate__()
        assert "__weakref__" not in state
        assert "__dict__" not in state

    # -- __setstate__  (lines 174-181) ----------------------------------

    def test_setstate_clears_dict(self):
        """Line 176: __setstate__ clears __dict__."""
        obj = _MinimalPersistentWithDict()
        obj.foo = "bar"
        obj._p_status = SAVED
        obj.__setstate__({"baz": 42})
        assert obj.baz == 42
        # 'foo' should be gone since dict was cleared then updated
        assert "foo" not in obj.__dict__

    def test_setstate_clears_data_slots(self):
        """Lines 177-178: __setstate__ deletes existing data slots then sets new."""
        obj = _MinimalPersistent(extra="old")
        obj._p_status = SAVED
        obj.__setstate__({"extra_slot": "new_val"})
        assert obj.extra_slot == "new_val"

    def test_setstate_with_none_clears_everything(self):
        """Lines 179-181: __setstate__(None) clears but doesn't set new values."""
        obj = _MinimalPersistentWithDict()
        obj.foo = "bar"
        obj._p_status = SAVED
        obj.__setstate__(None)
        assert not hasattr(obj, "foo")

    def test_setstate_with_dict_sets_values(self):
        obj = _MinimalPersistentWithDict()
        obj._p_status = SAVED
        obj.__setstate__({"a": 1, "b": 2})
        assert obj.a == 1
        assert obj.b == 2

    # -- __repr__  (lines 183-188) --------------------------------------

    def test_repr_with_no_oid(self):
        obj = _MinimalPersistent()
        r = repr(obj)
        assert "MinimalPersistent @" in r

    def test_repr_with_oid(self):
        obj = _MinimalPersistent()
        obj._p_oid = b"\x00" * 8
        r = repr(obj)
        assert "MinimalPersistent" in r
        assert "@" not in r  # should use _p_format_oid, not id

    # -- __delattr__  (lines 190-192) -----------------------------------

    def test_delattr_notes_change(self):
        """Lines 191-192: __delattr__ calls _p_note_change then _delattribute."""
        obj = _MinimalPersistentWithDict()
        obj._p_status = SAVED
        obj._p_connection = MagicMock()
        obj.foo = "bar"

        obj.__delattr__("foo")
        obj._p_connection.note_change.assert_called_once()
        assert not hasattr(obj, "foo")

    # -- _p_set_status_unsaved from GHOST  (line 219) -------------------

    def test_set_status_unsaved_from_ghost_loads_state(self):
        """Line 219: _p_set_status_unsaved calls _p_load_state when GHOST."""
        obj = _MinimalPersistent()
        obj._p_status = GHOST
        obj._p_connection = MagicMock()
        obj._p_connection.transaction_serial = 1

        load_called = False

        def tracking_load(self_inner):
            nonlocal load_called
            load_called = True
            object.__setattr__(self_inner, "_p_status", SAVED)
            object.__setattr__(self_inner, "_p_serial", 1)

        with patch.object(_MinimalPersistent, "_p_load_state", tracking_load):
            obj._p_set_status_unsaved()
            assert load_called
        assert obj._p_status == UNSAVED

    def test_set_status_unsaved_from_saved_no_load(self):
        obj = _MinimalPersistent()
        obj._p_status = SAVED
        obj._p_set_status_unsaved()
        assert obj._p_status == UNSAVED

    def test_set_status_unsaved_from_unsaved_no_load(self):
        obj = _MinimalPersistent()
        obj._p_status = UNSAVED
        obj._p_set_status_unsaved()
        assert obj._p_status == UNSAVED

    # -- status checkers  (lines 225-229) --------------------------------

    def test_p_is_unsaved(self):
        """Line 226: _p_is_unsaved returns True when UNSAVED."""
        obj = _MinimalPersistent()
        assert obj._p_is_unsaved() is True
        obj._p_status = SAVED
        assert obj._p_is_unsaved() is False
        obj._p_status = GHOST
        assert obj._p_is_unsaved() is False

    def test_p_is_saved(self):
        """Line 229: _p_is_saved returns True when SAVED."""
        obj = _MinimalPersistent()
        assert obj._p_is_saved() is False
        obj._p_status = SAVED
        assert obj._p_is_saved() is True
        obj._p_status = GHOST
        assert obj._p_is_saved() is False

    def test_p_is_ghost(self):
        """Line 223: _p_is_ghost returns True when GHOST."""
        obj = _MinimalPersistent()
        assert obj._p_is_ghost() is False
        obj._p_status = GHOST
        assert obj._p_is_ghost() is True
        obj._p_status = SAVED
        assert obj._p_is_ghost() is False
        obj._p_status = UNSAVED
        assert obj._p_is_ghost() is False

    # -- _p_format_oid ---------------------------------------------------

    def test_p_format_oid_with_oid(self):
        obj = _MinimalPersistent()
        obj._p_oid = b"\x00" * 8
        result = obj._p_format_oid()
        assert result == "0"

    def test_p_format_oid_with_bytes_oid(self):
        obj = _MinimalPersistent()
        obj._p_oid = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        from dhara.utils import str_to_int8

        result = obj._p_format_oid()
        assert result == str(str_to_int8(obj._p_oid))

    def test_p_format_oid_with_empty_bytes_oid(self):
        """Empty bytes is falsy, so `oid and ...` short-circuits to b'' then str(b'')."""
        obj = _MinimalPersistent()
        obj._p_oid = b""
        result = obj._p_format_oid()
        # b"" is falsy => `oid and ...` returns b"" => str(b"") == "b''"
        assert result == "b''"

    # -- _p_set_status_ghost ---------------------------------------------

    def test_p_set_status_ghost(self):
        obj = _MinimalPersistentWithDict()
        obj.foo = "bar"
        obj._p_status = SAVED
        obj._p_set_status_ghost()
        assert obj._p_status == GHOST
        # State should be cleared - check via __dict__ directly to avoid
        # triggering __getattribute__ which would try _p_load_state on GHOST
        assert "foo" not in object.__getattribute__(obj, "__dict__")

    # -- _p_note_change --------------------------------------------------

    def test_p_note_change_from_saved(self):
        obj = _MinimalPersistent()
        obj._p_status = SAVED
        obj._p_connection = MagicMock()
        obj._p_note_change()
        assert obj._p_status == UNSAVED
        obj._p_connection.note_change.assert_called_once_with(obj)

    def test_p_note_change_from_unsaved(self):
        obj = _MinimalPersistent()
        obj._p_status = UNSAVED
        obj._p_connection = MagicMock()
        obj._p_note_change()
        assert obj._p_status == UNSAVED
        obj._p_connection.note_change.assert_not_called()

    # -- _p_load_state ---------------------------------------------------

    def test_p_load_state(self):
        obj = _MinimalPersistent()
        obj._p_status = GHOST
        conn = MagicMock()
        obj._p_connection = conn
        obj._p_load_state()
        conn.load_state.assert_called_once_with(obj)
        assert obj._p_status == SAVED


# ---------------------------------------------------------------------------
# Persistent  (dict-based, lines 232-245)
# ---------------------------------------------------------------------------

class TestPersistent:

    def test_getstate_returns_dict(self):
        obj = _MinimalPersistentWithDict()
        obj.foo = "bar"
        obj._p_status = SAVED
        state = obj.__getstate__()
        assert isinstance(state, dict)
        assert state["foo"] == "bar"

    def test_setstate_clears_and_updates(self):
        """Lines 242-245: Persistent.__setstate__ clears dict then updates."""
        obj = _MinimalPersistentWithDict()
        obj.old_key = "old_val"
        obj._p_status = SAVED
        obj.__setstate__({"new_key": "new_val"})
        assert obj.new_key == "new_val"
        assert not hasattr(obj, "old_key")

    def test_setstate_with_none(self):
        """Lines 244-245: Persistent.__setstate__(None) clears dict."""
        obj = _MinimalPersistentWithDict()
        obj.foo = "bar"
        obj._p_status = SAVED
        obj.__setstate__(None)
        assert not hasattr(obj, "foo")


# ---------------------------------------------------------------------------
# ComputedAttribute  (lines 248-290)
# ---------------------------------------------------------------------------

class TestComputedAttribute:

    def test_getstate_returns_none(self):
        """Line 264: ComputedAttribute.__getstate__ returns None."""
        obj = _MinimalComputed()
        result = obj.__getstate__()
        assert result is None

    def test_p_load_state_sets_saved_without_connection_call(self):
        """Line 268: ComputedAttribute._p_load_state just sets SAVED."""
        obj = _MinimalComputed()
        obj._p_status = GHOST
        # No connection needed
        obj._p_connection = None
        obj._p_load_state()
        assert obj._p_status == SAVED

    def test_invalidate(self):
        """Lines 275-276: invalidate calls __setstate__(None) and _p_note_change."""
        obj = _MinimalComputed()
        obj._p_status = SAVED
        obj._p_connection = MagicMock()
        # Give it a value first
        _setattribute = object.__setattr__
        _setattribute(obj, "value", 42)

        obj.invalidate()
        assert obj._p_status == UNSAVED
        obj._p_connection.note_change.assert_called_once_with(obj)

    def test_get_without_existing_value(self):
        """Lines 285-290: get() computes and caches value when not present."""
        obj = _MinimalComputed()
        compute_fn = MagicMock(return_value=99)
        result = obj.get(compute_fn)
        assert result == 99
        compute_fn.assert_called_once()
        # Second call should use cached value
        compute_fn.reset_mock()
        result2 = obj.get(compute_fn)
        assert result2 == 99
        compute_fn.assert_not_called()

    def test_get_with_existing_value(self):
        """Line 286: get() returns cached value without calling compute."""
        obj = _MinimalComputed()
        _setattribute = object.__setattr__
        _setattribute(obj, "value", 77)
        compute_fn = MagicMock()
        result = obj.get(compute_fn)
        assert result == 77
        compute_fn.assert_not_called()


# ---------------------------------------------------------------------------
# call_if_persistent  (line 136-140)
# ---------------------------------------------------------------------------

class TestCallIfPersistent:

    def test_calls_function_on_persistent_object(self):
        f = MagicMock()
        obj = _MinimalPersistent()
        call_if_persistent(f, obj)
        f.assert_called_once_with(obj)

    def test_returns_none_for_non_persistent(self):
        f = MagicMock()
        result = call_if_persistent(f, "not_persistent")
        assert result is None
        f.assert_not_called()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:

    def test_constant_values(self):
        assert UNSAVED == 1
        assert SAVED == 0
        assert GHOST == -1
