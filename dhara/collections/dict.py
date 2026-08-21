"""
from __future__ import annotations
$URL$
$Id$
"""

import collections.abc
import inspect
from copy import copy

from dhara.core.persistent import PersistentObject
from dhara.utils import iteritems


class PersistentDict(PersistentObject, collections.abc.MutableMapping):
    """
    Instance attributes:
      data : dict
    """

    __slots__ = ["data"]

    data_is = dict  # for type checking using QP's spec module

    def __init__(self, *args, **kwargs):
        self.data = dict(*args, **kwargs)

    def __eq__(self, other):
        return isinstance(other, PersistentDict) and self.data == other.data

    def __ne__(self, other):
        return not self == other

    def __len__(self):
        return len(self.data)

    def __getitem__(self, key):
        if key in self.data:
            return self.data[key]
        if hasattr(self.__class__, "__missing__"):
            return self.__class__.__missing__(self, key)
        raise KeyError(key)

    def __setitem__(self, key, item):
        self._p_note_change()
        self.data[key] = item

    def __delitem__(self, key):
        self._p_note_change()
        del self.data[key]

    def clear(self):
        self._p_note_change()
        self.data.clear()

    def copy(self):
        result = copy(self)
        result.data = self.data.copy()
        return result

    def keys(self):
        return list(self.data.keys())

    def items(self):
        return list(self.data.items())

    def iteritems(self):
        return iteritems(self.data)

    def iterkeys(self):
        for k, v in self.iteritems():
            yield k

    def itervalues(self):
        for k, v in self.iteritems():
            yield v

    def values(self):
        return list(self.data.values())

    def has_key(self, key):
        return key in self.data

    def update(self, *others, **kwargs):
        self._p_note_change()
        if len(others) > 1:
            raise TypeError("update() expected at most 1 argument")
        elif others:
            other = others[0]
            if isinstance(other, PersistentDict):
                self.data.update(other.data)
            elif isinstance(other, dict):
                self.data.update(other)
            elif hasattr(other, "keys"):
                for k in other.keys():  # noqa: SIM118 — call .keys() explicitly; other may lack __iter__ (see SimpleMapping test)
                    self[k] = other[k]
            else:
                for k, v in other:
                    self[k] = v
        for kw, value in kwargs.items():
            self[kw] = value

    def get(self, key, failobj=None):
        return self.data.get(key, failobj)

    def setdefault(self, key, failobj=None):
        if key not in self.data:
            self._p_note_change()
            self.data[key] = failobj
            return failobj
        return self.data[key]

    def pop(self, key, *args):
        self._p_note_change()
        return self.data.pop(key, *args)

    def popitem(self):
        self._p_note_change()
        return self.data.popitem()

    def __contains__(self, key):
        return key in self.data

    @classmethod
    def fromkeys(cls, iterable, value=None):
        d = cls()
        for key in iterable:
            d[key] = value
        return d

    def __iter__(self):
        return iter(self.data)

    # ── Async persistence methods ─────────────────────────────────
    # The sync dict operations (__getitem__, __setitem__, __contains__,
    # etc.) are already non-blocking (operate on in-memory object state).
    # These async methods handle the connection.commit() / abort() calls.

    async def commit_async(self) -> None:
        """Async commit — awaits connection.commit() if it's a coroutine."""
        if self._p_connection is not None:
            conn = self._p_connection
            c = conn.commit()
            if inspect.iscoroutine(c):
                await c

    async def abort_async(self) -> None:
        """Async abort — awaits connection.abort() if it's a coroutine."""
        if self._p_connection is not None:
            conn = self._p_connection
            a = conn.abort()
            if inspect.iscoroutine(a):
                await a
