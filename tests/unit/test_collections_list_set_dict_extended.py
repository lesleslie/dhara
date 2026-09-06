"""Extended coverage tests for the PersistentList / PersistentSet / PersistentDict trio.

Scope rationale
---------------
Measured against the *whole* suite (``testpaths = ["test", "tests"]``) rather
than ``tests/unit/`` in isolation, the trio already sat at:

======================================  ======  ===============================
module                                  cover   missing
======================================  ======  ===============================
``dhara/collections/dict.py``             90%   142-145, 150-153
``dhara/collections/list.py``             91%   183-186, 191-194
``dhara/collections/set.py``             100%   --
======================================  ======  ===============================

Every one of those missing lines is the *connection-attached* half of the two
async persistence wrappers, ``commit_async`` and ``abort_async``.  The
pre-existing suites (``tests/test_async_persistent_list.py``,
``tests/test_async_persistent_dict.py``) only ever call them on a *detached*
object, so ``if self._p_connection is not None:`` was covered False-only and
the ``inspect.iscoroutine(...)`` branch inside it not at all.  Closing that
gap is what takes list and dict to 100%; ``set.py`` has no async wrappers and
needed nothing.

On top of the coverage gap this file pins two contracts that the pre-existing
suites are structurally unable to assert:

1. **Real change tracking.**  ``tests/test_collections_set.py`` attaches a
   ``MagicMock()`` as the connection and ``tests/test_collections.py`` patches
   ``_p_note_change`` out wholesale, so "mutating the collection marks it
   UNSAVED and enrolls it in the transaction" is never actually verified --- a
   mock absorbs the call and reports success either way.  The tests here drive
   the objects through a **real** ``Connection`` and assert both the status
   transition (``_p_is_unsaved()``) and the enrollment (``conn.changed``).
   ``tests/test_collections_dict.py`` does assert ``_p_note_change`` was
   *called*, via ``patch.object``; asserting the resulting *state* is new.

2. **The ``__getstate__`` / ``__setstate__`` slot contract.**  These three
   classes are ``__slots__``-based, so their persistent state flows through
   ``PersistentObject._p_gen_data_slots`` rather than a ``__dict__``.  The
   round-trip through that path is asserted here per class.

Deliberately out of scope: a cross-``Connection`` store-then-reload round trip.
Probing that showed the default serializer hands back the raw
``{"__class__": ..., "__state__": ...}`` envelope instead of rehydrating the
collection type, so a test built on it would either encode a possible bug as
expected behaviour or fail for reasons unrelated to these three modules.
Production code is frozen for this task, so the observation is recorded here
rather than acted on.
"""

from __future__ import annotations

from typing import Any

import pytest

from dhara.collections.dict import PersistentDict
from dhara.collections.list import PersistentList
from dhara.collections.set import PersistentSet

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OID = b"\x01" * 8


def _attach(obj: Any, conn: Any, oid: bytes = _OID) -> Any:
    """Attach ``conn`` to ``obj`` and park it in the SAVED state.

    Writes ``_p_connection`` / ``_p_oid`` through ``object.__setattr__`` so the
    attachment itself does not trip ``_p_note_change`` (which would leave the
    object already UNSAVED and make the change-tracking assertions vacuous).
    This mirrors the attachment style used by
    ``tests/test_async_persistent_list.py``.
    """
    object.__setattr__(obj, "_p_connection", conn)
    object.__setattr__(obj, "_p_oid", oid)
    obj._p_set_status_saved()
    return obj


class _SyncCallConnection:
    """Connection stand-in whose ``commit``/``abort`` are plain functions.

    Exercises the ``inspect.iscoroutine(...) is False`` arm of the async
    persistence wrappers: the wrapper must call straight through and must not
    attempt to await the ``None`` result.
    """

    transaction_serial = 1

    def __init__(self) -> None:
        self.commit_calls = 0
        self.abort_calls = 0

    def commit(self) -> None:
        self.commit_calls += 1

    def abort(self) -> None:
        self.abort_calls += 1

    def note_access(self, obj: Any) -> None:
        return None


class _CoroutineCallConnection:
    """Connection stand-in whose ``commit``/``abort`` are coroutine functions.

    Exercises the ``await`` arms.  The ``*_awaited`` flags are set *inside* the
    coroutine bodies, so they stay ``False`` unless the wrapper genuinely
    awaits the coroutine it received --- merely calling ``commit()`` and
    dropping the result would leave them ``False``.
    """

    transaction_serial = 1

    def __init__(self) -> None:
        self.commit_awaited = False
        self.abort_awaited = False

    async def commit(self) -> None:
        self.commit_awaited = True

    async def abort(self) -> None:
        self.abort_awaited = True

    def note_access(self, obj: Any) -> None:
        return None


# ---------------------------------------------------------------------------
# PersistentList
# ---------------------------------------------------------------------------


class TestPersistentListExtended:
    """Async persistence wrappers, real change tracking, and slot state."""

    # -- commit_async / abort_async: the actual coverage gap --------------

    async def test_commit_async_awaits_coroutine_connection(self) -> None:
        conn = _CoroutineCallConnection()
        pl = _attach(PersistentList([1, 2]), conn)

        await pl.commit_async()

        assert conn.commit_awaited is True

    async def test_abort_async_awaits_coroutine_connection(self) -> None:
        conn = _CoroutineCallConnection()
        pl = _attach(PersistentList([1, 2]), conn)

        await pl.abort_async()

        assert conn.abort_awaited is True

    async def test_commit_async_calls_through_sync_connection(self) -> None:
        """A non-coroutine ``commit()`` is called once and never awaited."""
        conn = _SyncCallConnection()
        pl = _attach(PersistentList([1, 2]), conn)

        await pl.commit_async()

        assert conn.commit_calls == 1

    async def test_abort_async_calls_through_sync_connection(self) -> None:
        conn = _SyncCallConnection()
        pl = _attach(PersistentList([1, 2]), conn)

        await pl.abort_async()

        assert conn.abort_calls == 1

    async def test_commit_async_with_real_async_connection(
        self, async_connection
    ) -> None:
        """Integration guard: the wrapper works against a real AsyncConnection."""
        pl = _attach(PersistentList([1, 2]), async_connection)

        await pl.commit_async()  # must not raise

    async def test_abort_async_with_real_async_connection(
        self, async_connection
    ) -> None:
        pl = _attach(PersistentList([1, 2]), async_connection)

        await pl.abort_async()  # must not raise

    async def test_commit_async_with_real_sync_connection(self, connection) -> None:
        """A sync ``Connection`` returns ``None`` from ``commit()``; tolerated."""
        pl = _attach(PersistentList([1, 2]), connection)

        await pl.commit_async()  # must not raise

    async def test_abort_async_with_real_sync_connection(self, connection) -> None:
        pl = _attach(PersistentList([1, 2]), connection)

        await pl.abort_async()  # must not raise

    # -- change tracking against a real Connection -----------------------

    @pytest.mark.parametrize(
        ("label", "mutate"),
        [
            ("append", lambda pl: pl.append(9)),
            ("insert", lambda pl: pl.insert(0, 9)),
            ("setitem", lambda pl: pl.__setitem__(0, 9)),
            ("delitem", lambda pl: pl.__delitem__(0)),
            ("pop", lambda pl: pl.pop()),
            ("remove", lambda pl: pl.remove(1)),
            ("reverse", lambda pl: pl.reverse()),
            ("sort", lambda pl: pl.sort()),
            ("extend", lambda pl: pl.extend([9])),
            ("iadd", lambda pl: pl.__iadd__([9])),
            ("imul", lambda pl: pl.__imul__(2)),
            ("setslice", lambda pl: pl.__setslice__(0, 1, [9])),
            ("delslice", lambda pl: pl.__delslice__(0, 1)),
        ],
    )
    def test_mutation_marks_unsaved_and_enrolls_in_transaction(
        self, connection, label, mutate
    ) -> None:
        pl = _attach(PersistentList([1, 2, 3]), connection)
        assert pl._p_is_saved(), "precondition: object starts SAVED"

        mutate(pl)

        assert pl._p_is_unsaved(), f"{label} did not mark the list UNSAVED"
        assert connection.changed.get(_OID) is pl, f"{label} did not enroll the list"

    @pytest.mark.parametrize(
        ("label", "read"),
        [
            ("len", len),
            ("contains", lambda pl: 1 in pl),
            ("getitem", lambda pl: pl[0]),
            ("count", lambda pl: pl.count(1)),
            ("index", lambda pl: pl.index(1)),
            ("iter", lambda pl: list(iter(pl))),
            ("add", lambda pl: pl + [4]),
            ("radd", lambda pl: [0] + pl),
            ("mul", lambda pl: pl * 2),
            ("getslice", lambda pl: pl.__getslice__(0, 2)),
        ],
    )
    def test_read_only_operations_leave_object_saved(
        self, connection, label, read
    ) -> None:
        """Reads must not enroll the list in the transaction."""
        pl = _attach(PersistentList([1, 2, 3]), connection)

        read(pl)

        assert pl._p_is_saved(), f"{label} spuriously marked the list UNSAVED"
        assert _OID not in connection.changed, f"{label} spuriously enrolled the list"

    # -- __getstate__ / __setstate__ slot contract -----------------------

    def test_getstate_exposes_the_data_slot(self) -> None:
        assert PersistentList([1, 2]).__getstate__() == {"data": [1, 2]}

    def test_setstate_restores_the_data_slot(self) -> None:
        pl = PersistentList()

        pl.__setstate__({"data": [7, 8]})

        assert pl.data == [7, 8]
        assert pl == [7, 8]

    def test_setstate_none_clears_the_data_slot(self) -> None:
        pl = PersistentList([1, 2])

        pl.__setstate__(None)

        with pytest.raises(AttributeError):
            _ = pl.data


# ---------------------------------------------------------------------------
# PersistentSet
# ---------------------------------------------------------------------------


class TestPersistentSetExtended:
    """Real change tracking and slot state for ``PersistentSet``.

    ``set.py`` is already at 100% statement + branch coverage from
    ``tests/test_collections_set.py``, so there is no coverage gap to close.
    What that suite cannot show is whether mutation actually drives the
    persistence machinery: it installs a ``MagicMock()`` connection, which
    absorbs ``note_change`` silently.  These tests use a real ``Connection``.
    """

    @pytest.mark.parametrize(
        ("label", "mutate"),
        [
            ("add", lambda ps: ps.add(9)),
            ("discard", lambda ps: ps.discard(1)),
            ("remove", lambda ps: ps.remove(1)),
            ("pop", lambda ps: ps.pop()),
            ("clear", lambda ps: ps.clear()),
            ("update", lambda ps: ps.update({9})),
            ("difference_update", lambda ps: ps.difference_update({1})),
            ("intersection_update", lambda ps: ps.intersection_update({1})),
            (
                "symmetric_difference_update",
                lambda ps: ps.symmetric_difference_update({9}),
            ),
            ("iand", lambda ps: ps.__iand__({1})),
            ("ior", lambda ps: ps.__ior__({9})),
            ("isub", lambda ps: ps.__isub__({1})),
            ("ixor", lambda ps: ps.__ixor__({9})),
        ],
    )
    def test_mutation_marks_unsaved_and_enrolls_in_transaction(
        self, connection, label, mutate
    ) -> None:
        ps = _attach(PersistentSet({1, 2, 3}), connection)
        assert ps._p_is_saved(), "precondition: object starts SAVED"

        mutate(ps)

        assert ps._p_is_unsaved(), f"{label} did not mark the set UNSAVED"
        assert connection.changed.get(_OID) is ps, f"{label} did not enroll the set"

    @pytest.mark.parametrize(
        ("label", "read"),
        [
            ("len", len),
            ("contains", lambda ps: 1 in ps),
            ("iter", lambda ps: sorted(ps)),
            ("copy", lambda ps: ps.copy()),
            ("union", lambda ps: ps.union({9})),
            ("intersection", lambda ps: ps.intersection({1})),
            ("difference", lambda ps: ps.difference({1})),
            ("symmetric_difference", lambda ps: ps.symmetric_difference({9})),
            ("issubset", lambda ps: ps.issubset({1, 2, 3})),
            ("issuperset", lambda ps: ps.issuperset({1})),
            ("and", lambda ps: ps & {1}),
            ("or", lambda ps: ps | {9}),
            ("sub", lambda ps: ps - {1}),
            ("xor", lambda ps: ps ^ {9}),
            ("repr", repr),
        ],
    )
    def test_read_only_operations_leave_object_saved(
        self, connection, label, read
    ) -> None:
        ps = _attach(PersistentSet({1, 2, 3}), connection)

        read(ps)

        assert ps._p_is_saved(), f"{label} spuriously marked the set UNSAVED"
        assert _OID not in connection.changed, f"{label} spuriously enrolled the set"

    def test_copy_is_detached_from_the_original(self, connection) -> None:
        """``copy()`` returns a fresh, unattached instance sharing no state."""
        ps = _attach(PersistentSet({1, 2}), connection)

        clone = ps.copy()
        clone.add(3)

        assert ps.s == {1, 2}, "mutating the copy leaked into the original"
        assert clone._p_oid is None
        assert clone._p_connection is None

    # -- __getstate__ / __setstate__ slot contract -----------------------

    def test_getstate_exposes_the_s_slot(self) -> None:
        assert PersistentSet({1, 2}).__getstate__() == {"s": {1, 2}}

    def test_setstate_restores_the_s_slot(self) -> None:
        ps = PersistentSet()

        ps.__setstate__({"s": {7, 8}})

        assert ps.s == {7, 8}

    def test_setstate_none_clears_the_s_slot(self) -> None:
        ps = PersistentSet({1, 2})

        ps.__setstate__(None)

        with pytest.raises(AttributeError):
            _ = ps.s

    def test_repr_uses_oid_once_assigned(self) -> None:
        """``__repr__`` switches from the ``@address`` form to the OID form."""
        detached = PersistentSet({1})
        assert repr(detached) == f"<PersistentSet @{id(detached):x} {{1}}>"

        attached = PersistentSet({1})
        object.__setattr__(attached, "_p_oid", b"\x00" * 8)
        assert repr(attached) == "<PersistentSet 0 {1}>"


# ---------------------------------------------------------------------------
# PersistentDict
# ---------------------------------------------------------------------------


class TestPersistentDictExtended:
    """Async persistence wrappers, real change tracking, and slot state."""

    # -- commit_async / abort_async: the actual coverage gap --------------

    async def test_commit_async_awaits_coroutine_connection(self) -> None:
        conn = _CoroutineCallConnection()
        pd = _attach(PersistentDict({"a": 1}), conn)

        await pd.commit_async()

        assert conn.commit_awaited is True

    async def test_abort_async_awaits_coroutine_connection(self) -> None:
        conn = _CoroutineCallConnection()
        pd = _attach(PersistentDict({"a": 1}), conn)

        await pd.abort_async()

        assert conn.abort_awaited is True

    async def test_commit_async_calls_through_sync_connection(self) -> None:
        conn = _SyncCallConnection()
        pd = _attach(PersistentDict({"a": 1}), conn)

        await pd.commit_async()

        assert conn.commit_calls == 1

    async def test_abort_async_calls_through_sync_connection(self) -> None:
        conn = _SyncCallConnection()
        pd = _attach(PersistentDict({"a": 1}), conn)

        await pd.abort_async()

        assert conn.abort_calls == 1

    async def test_commit_async_with_real_async_connection(
        self, async_connection
    ) -> None:
        pd = _attach(PersistentDict({"a": 1}), async_connection)

        await pd.commit_async()  # must not raise

    async def test_abort_async_with_real_async_connection(
        self, async_connection
    ) -> None:
        pd = _attach(PersistentDict({"a": 1}), async_connection)

        await pd.abort_async()  # must not raise

    async def test_commit_async_with_real_sync_connection(self, connection) -> None:
        pd = _attach(PersistentDict({"a": 1}), connection)

        await pd.commit_async()  # must not raise

    async def test_abort_async_with_real_sync_connection(self, connection) -> None:
        pd = _attach(PersistentDict({"a": 1}), connection)

        await pd.abort_async()  # must not raise

    # -- change tracking against a real Connection -----------------------

    @pytest.mark.parametrize(
        ("label", "mutate"),
        [
            ("setitem", lambda pd: pd.__setitem__("z", 9)),
            ("delitem", lambda pd: pd.__delitem__("a")),
            ("clear", lambda pd: pd.clear()),
            ("pop", lambda pd: pd.pop("a")),
            ("popitem", lambda pd: pd.popitem()),
            ("update_dict", lambda pd: pd.update({"z": 9})),
            ("update_kwargs", lambda pd: pd.update(z=9)),
            ("update_pairs", lambda pd: pd.update([("z", 9)])),
            ("update_persistentdict", lambda pd: pd.update(PersistentDict({"z": 9}))),
            ("setdefault_missing", lambda pd: pd.setdefault("z", 9)),
        ],
    )
    def test_mutation_marks_unsaved_and_enrolls_in_transaction(
        self, connection, label, mutate
    ) -> None:
        pd = _attach(PersistentDict({"a": 1, "b": 2}), connection)
        assert pd._p_is_saved(), "precondition: object starts SAVED"

        mutate(pd)

        assert pd._p_is_unsaved(), f"{label} did not mark the dict UNSAVED"
        assert connection.changed.get(_OID) is pd, f"{label} did not enroll the dict"

    def test_setdefault_on_existing_key_leaves_object_saved(self, connection) -> None:
        """The hit path of ``setdefault`` must not enroll the dict."""
        pd = _attach(PersistentDict({"a": 1}), connection)

        assert pd.setdefault("a", 99) == 1

        assert pd._p_is_saved()
        assert _OID not in connection.changed

    @pytest.mark.parametrize(
        ("label", "read"),
        [
            ("len", len),
            ("contains", lambda pd: "a" in pd),
            ("getitem", lambda pd: pd["a"]),
            ("get_hit", lambda pd: pd.get("a")),
            ("get_miss", lambda pd: pd.get("nope")),
            ("keys", lambda pd: pd.keys()),
            ("values", lambda pd: pd.values()),
            ("items", lambda pd: pd.items()),
            ("iteritems", lambda pd: list(pd.iteritems())),
            ("iterkeys", lambda pd: list(pd.iterkeys())),
            ("itervalues", lambda pd: list(pd.itervalues())),
            ("has_key", lambda pd: pd.has_key("a")),
            ("iter", lambda pd: list(iter(pd))),
            ("copy", lambda pd: pd.copy()),
        ],
    )
    def test_read_only_operations_leave_object_saved(
        self, connection, label, read
    ) -> None:
        pd = _attach(PersistentDict({"a": 1, "b": 2}), connection)

        read(pd)

        assert pd._p_is_saved(), f"{label} spuriously marked the dict UNSAVED"
        assert _OID not in connection.changed, f"{label} spuriously enrolled the dict"

    def test_copy_is_detached_and_does_not_share_the_data_dict(
        self, connection
    ) -> None:
        pd = _attach(PersistentDict({"a": 1}), connection)

        clone = pd.copy()
        clone["b"] = 2

        assert pd.data == {"a": 1}, "mutating the copy leaked into the original"
        assert clone.data == {"a": 1, "b": 2}

    def test_update_rejects_more_than_one_positional_argument(self) -> None:
        pd = PersistentDict()

        with pytest.raises(TypeError, match="at most 1 argument"):
            pd.update({"a": 1}, {"b": 2})

    def test_update_accepts_a_keys_only_mapping(self) -> None:
        """The ``hasattr(other, "keys")`` arm: no ``__iter__``, no ``dict`` base."""

        class KeysOnlyMapping:
            def keys(self):
                return ["x", "y"]

            def __getitem__(self, key):
                return key.upper()

        pd = PersistentDict()

        pd.update(KeysOnlyMapping())

        assert pd.data == {"x": "X", "y": "Y"}

    # -- __getstate__ / __setstate__ slot contract -----------------------

    def test_getstate_exposes_the_data_slot(self) -> None:
        assert PersistentDict({"a": 1}).__getstate__() == {"data": {"a": 1}}

    def test_setstate_restores_the_data_slot(self) -> None:
        pd = PersistentDict()

        pd.__setstate__({"data": {"z": 9}})

        assert pd.data == {"z": 9}
        assert pd == PersistentDict({"z": 9})

    def test_setstate_none_clears_the_data_slot(self) -> None:
        pd = PersistentDict({"a": 1})

        pd.__setstate__(None)

        with pytest.raises(AttributeError):
            _ = pd.data
