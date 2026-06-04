"""Record format and ObjectReader/ObjectWriter for Dhara persistent storage.

Wire format (unchanged from the Durus 4.x legacy):
    [8 bytes OID big-endian]
    [4 bytes big-endian data length N]
    [N bytes data — msgpack-encoded {"__class__", "__state__"}]
    [M bytes refs — concatenated 8-byte OIDs]

This module replaces ``dhara.serialize_legacy`` (the pickle-based original)
with a safe, msgspec-backed implementation. It is the only place that
handles the per-record framing; the storage layer (``FileStorage``,
``SqliteStorage``, etc.) calls into this module.

The data payload is no longer ``pickle(type) + zlib(pickle(state))``;
it is a plain msgpack dict ``{"__class__": "module.qualname",
"__state__": {...}}``. The OID/length framing at the wire level is
preserved so that swapping in the new format does not require
changing the storage layout.
"""

from __future__ import annotations

import importlib
from contextlib import suppress
from typing import Any, Final

from dhara.serialize.msgspec import MsgspecSerializer
from dhara.utils import int4_to_str, join_bytes, str_to_int4

NEWLINE: Final[bytes] = b"\n"
# Internal record-layer serializer. Uses the default whitelist
# (``DEFAULT_ALLOWED_MODULES``); we never call ``deserialize`` on
# this instance — only ``decode_raw`` and ``serialize`` — so the
# whitelist field is dormant. Class reconstruction (which would
# trigger the whitelist check) is gated by :func:`_resolve_class`
# with a connection-level whitelist instead.
_DEFAULT_MSGSPEC: Final[MsgspecSerializer] = MsgspecSerializer(
    format="msgpack", use_builtins=True
)


# ---------------------------------------------------------------------------
# Wire-format primitives
# ---------------------------------------------------------------------------


def pack_record(oid: bytes, data: bytes, refs: bytes) -> bytes:
    """Frame an OID + data + refs as a single record."""
    # join_bytes is an untyped helper (b''.join bound method); the input
    # list is bytes-typed so the result is always bytes at runtime.
    return join_bytes([oid, int4_to_str(len(data)), data, refs])  # type: ignore[no-any-return]


def unpack_record(record: bytes) -> tuple[bytes, bytes, bytes]:
    """Inverse of :func:`pack_record`. Returns ``(oid, data, refs)``."""
    oid = record[:8]
    data_length = str_to_int4(record[8:12])
    data_end = 12 + data_length
    data = record[12:data_end]
    refs = record[data_end:]
    return oid, data, refs


def split_oids(refs: bytes) -> list[bytes]:
    """Split a refs blob into a list of 8-byte OIDs."""
    if len(refs) % 8 != 0:
        raise ValueError(f"refs blob length {len(refs)} is not a multiple of 8 bytes")
    return [refs[i : i + 8] for i in range(0, len(refs), 8)]


# ---------------------------------------------------------------------------
# Class name extraction (display only)
# ---------------------------------------------------------------------------


def extract_class_name(record: bytes) -> str:
    """Return the ``module.qualname`` string encoded in a record.

    This function is **display / logging only**. It does **not** validate
    the class name against any module whitelist, and it does **not**
    import the class. Use :func:`_resolve_class` if you intend to
    import the class for materialization.
    """
    with suppress(Exception):
        _, data, _ = unpack_record(record)
        decoded = _DEFAULT_MSGSPEC.decode_raw(data)
        if isinstance(decoded, dict) and "__class__" in decoded:
            return str(decoded["__class__"])
    return "?"


# ---------------------------------------------------------------------------
# Per-object state encode / decode
# ---------------------------------------------------------------------------


def serialize_state(obj: Any) -> bytes:
    """Encode a Persistent-style object as the ``data`` blob for pack_record.

    Produces ``msgpack({"__class__": "module.qualname", "__state__": obj.__getstate__()})``.
    """
    state = {
        "__class__": f"{type(obj).__module__}.{type(obj).__name__}",
        "__state__": obj.__getstate__(),
    }
    return _DEFAULT_MSGSPEC.serialize(state)


def deserialize_state(data: bytes) -> tuple[str, dict]:
    """Inverse of :func:`serialize_state`. Returns ``(class_name, state_dict)``.

    **SECURITY:** The returned ``class_name`` is *not* validated here.
    Callers that intend to import the class must pass it through
    :func:`_resolve_class`. This split lets display-only code (e.g.
    :func:`extract_class_name`) read the name without paying the
    import cost; production code paths must use :func:`_resolve_class`.
    """
    decoded = _DEFAULT_MSGSPEC.decode_raw(data)
    if not isinstance(decoded, dict) or "__class__" not in decoded:
        raise ValueError("record is not a state payload (missing __class__)")
    class_name = str(decoded["__class__"])
    state = decoded.get("__state__", {})
    if state is None:
        state = {}
    return class_name, state


# ---------------------------------------------------------------------------
# Module whitelist (runtime-configurable, permissive default)
# ---------------------------------------------------------------------------


def _resolve_class(class_name: str, allowed_modules: set[str] | None = None) -> type:
    """Import a class by ``module.qualname``, optionally validated against a whitelist.

    Args:
        class_name: a string like ``"dhara.core.persistent.Persistent"``.
        allowed_modules: if provided, the module prefix must be in this set.
            If ``None`` (the default), **no validation is performed** —
            matches the most permissive legacy behavior. Admins can
            tighten this for untrusted-storage scenarios.

    Returns:
        The imported class.

    Raises:
        ValueError: if the class name is malformed, the module is not
            in the whitelist, or the resolved attribute is not a class.
    """
    parts = class_name.rsplit(".", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid class name: {class_name!r}")
    module, classname = parts
    if allowed_modules is not None and module not in allowed_modules:
        raise ValueError(
            f"Module {module!r} is not in the allowed-modules whitelist. "
            f"This prevents arbitrary code execution via deserialization."
        )
    mod = importlib.import_module(module)
    klass = getattr(mod, classname)
    if not isinstance(klass, type):
        raise ValueError(f"{class_name!r} is not a class")
    return klass


# ---------------------------------------------------------------------------
# ObjectReader / ObjectWriter (per-object state)
# ---------------------------------------------------------------------------


class ObjectWriter:
    """Writes per-object state in the new msgpack format.

    Maintains the same API surface as the legacy pickle-based
    ``ObjectWriter`` so that :meth:`dhara.core.connection.Connection.commit`
    can use it without code changes to the call sites. The connection
    tracks newly-persistent objects via its cache; this writer handles
    per-object state encoding and refs concatenation.
    """

    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.refs: set[bytes] = set()
        self._closed = False

    def get_state(self, obj: Any) -> tuple[bytes, bytes]:
        """Return ``(data, refs_blob)`` for an object.

        ``data`` is the msgpack-encoded state blob.
        ``refs_blob`` is the concatenated 8-byte OIDs from ``self.refs``,
        sorted lexicographically.

        The connection is expected to populate ``self.refs`` (via the
        persistent-registration walk it does at commit time) before
        calling :meth:`get_state`.
        """
        if self._closed:
            raise RuntimeError("ObjectWriter is closed")
        data = serialize_state(obj)
        refs_blob = join_bytes(sorted(self.refs))
        return data, refs_blob

    def gen_new_objects(self, obj: Any):
        """Yield the object (legacy compatibility shim).

        The new implementation yields the root object only. The
        connection's commit loop is responsible for tracking new OIDs
        via the cache and re-iterating as needed; this method exists
        only to preserve the legacy API shape.

        Note: do NOT set ``self._closed`` here. The legacy self-mutating
        pattern closed the writer as a side-effect of iteration, which
        breaks the Connection.commit() flow because it then calls
        ``get_state()`` *after* this method returns. Finalization is
        the responsibility of :meth:`close`. The re-entry guard above
        still catches any caller that invokes this method after close().
        """
        if self._closed:
            raise RuntimeError("ObjectWriter is closed")
        yield obj

    def close(self) -> None:
        """Release resources. No-op in the msgspec world."""
        self._closed = True
        self.refs.clear()


class ObjectReader:
    """Reads per-object state from a record.

    Replaces the legacy pickle-based ``ObjectReader``. The new
    implementation decodes msgpack state and (when requested)
    instantiates a ghost object from the class name.
    """

    def __init__(
        self,
        connection: Any,
        allowed_modules: set[str] | None = None,
    ) -> None:
        self.connection = connection
        self.allowed_modules = allowed_modules
        self.load_count = 0

    def get_ghost(self, data: bytes) -> Any:
        """Materialize a ghost object from the data blob.

        Imports the class via :func:`_resolve_class` (subject to the
        ``allowed_modules`` whitelist if configured) and instantiates
        a ghost via ``__new__``.
        """
        class_name, _state = deserialize_state(data)
        klass = _resolve_class(class_name, self.allowed_modules)
        # Use the class's own __new__ so that PersistentBase.__new__
        # runs and initializes all four slots (_p_status, _p_serial,
        # _p_connection, _p_oid). Skipping __new__ (e.g. via
        # object.__new__) leaves those slots unset, which causes
        # AttributeError on the first __getattribute__ access — see
        # ``persistent_load`` below for the same rationale.
        instance = klass.__new__(klass)  # type: ignore[misc,call-arg]
        instance._p_set_status_ghost()
        return instance

    def get_state(self, data: bytes, load: bool = True) -> Any:
        """Return the state dict (when ``load=True``) or the raw bytes (``load=False``)."""
        self.load_count += 1
        if not load:
            return data
        _class_name, state = deserialize_state(data)
        return state

    def get_state_pickle(self, data: bytes) -> bytes:
        """Legacy name. Returns the raw data blob (it is no longer pickle)."""
        return data

    def get_load_count(self) -> int:
        return self.load_count


# ---------------------------------------------------------------------------
# Pure object-graph helper (no pickle involvement)
# ---------------------------------------------------------------------------


def persistent_load(connection: Any, cache_objects: Any, oid_class: tuple) -> Any:
    """Resolve an ``(oid, klass)`` tuple to a cached ghost object.

    Pure object-graph helper. The implementation mirrors the existing
    function in ``dhara/serialize_legacy.py:216-235`` verbatim — it
    tries to use the C-extension ``_setattribute`` if available, and
    falls back to ``object.__setattr__`` otherwise. No pickle
    involvement.
    """
    try:
        from dhara.core.persistent import _setattribute
    except ImportError:
        _setattribute = None  # type: ignore[assignment]

    oid, klass = oid_class
    try:
        cache = cache_objects.get(oid)
    except Exception:
        cache = None
    if cache is not None:
        return cache
    try:
        # Use the class's own __new__ (not object.__new__) so that
        # PersistentBase.__new__ runs and initializes all four slots:
        # _p_status, _p_serial, _p_connection, _p_oid. Skipping __new__
        # leaves _p_status/_p_serial/_p_connection unset, which causes
        # AttributeError on the very first __getattribute__ access
        # (e.g. inside PersistentDict.__init__ → __setattr__ → _p_note_change).
        instance = klass.__new__(klass)  # type: ignore[misc,call-arg]
    except TypeError:
        return None
    with suppress(Exception):
        if _setattribute is not None:
            _setattribute(instance, "_p_oid", oid)
        else:
            object.__setattr__(instance, "_p_oid", oid)
    with suppress(Exception):
        cache_objects[oid] = instance
    return instance


__all__ = [
    "NEWLINE",
    "pack_record",
    "unpack_record",
    "split_oids",
    "extract_class_name",
    "serialize_state",
    "deserialize_state",
    "_resolve_class",
    "ObjectReader",
    "ObjectWriter",
    "persistent_load",
]
