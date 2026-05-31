"""
$URL$
$Id$
"""

from __future__ import annotations

import collections.abc
import inspect
from typing import Any

from dhara.core.persistent import PersistentObject


class PersistentList(PersistentObject, collections.abc.MutableSequence):
    """
    Instance attributes:
      data : list
    """

    __slots__ = ["data"]

    data_is = list  # for type checking using QP's spec module

    def __init__(self, *args, **kwargs):
        self.data = list(*args, **kwargs)

    def __cast(self, other):
        if isinstance(other, PersistentList):
            return other.data

        return other

    def __lt__(self, other):
        return self is not other and self.data < self.__cast(other)

    def __le__(self, other):
        return self is other or self.data <= self.__cast(other)

    def __eq__(self, other):
        return self is other or self.data == self.__cast(other)

    def __ne__(self, other):
        return self is not other and self.data != self.__cast(other)

    def __gt__(self, other):
        return self is not other and self.data > self.__cast(other)

    def __ge__(self, other):
        return self is other or self.data >= self.__cast(other)

    def __contains__(self, item):
        return item in self.data

    def __len__(self):
        return len(self.data)

    def __getitem__(self, i):
        return self.data[i]

    def __setitem__(self, i, item):
        self._p_note_change()
        self.data[i] = item

    def __delitem__(self, i):
        self._p_note_change()
        del self.data[i]

    def __getslice__(self, i, j):
        return self.__class__(self.data[i:j])

    def __setslice__(self, i, j, other):
        self._p_note_change()
        if isinstance(other, PersistentList):
            self.data[i:j] = other.data
        elif isinstance(other, type(self.data)):
            self.data[i:j] = other
        else:
            self.data[i:j] = list(other)

    def __delslice__(self, i, j):
        self._p_note_change()
        del self.data[i:j]

    def __add__(self, other):
        if isinstance(other, PersistentList):
            return self.__class__(self.data + other.data)
        elif isinstance(other, type(self.data)):
            return self.__class__(self.data + other)

        return self.__class__(self.data + list(other))

    def __radd__(self, other):
        if isinstance(other, PersistentList):
            return self.__class__(other.data + self.data)
        elif isinstance(other, type(self.data)):
            return self.__class__(other + self.data)

        return self.__class__(list(other) + self.data)

    def __iadd__(self, other):
        self._p_note_change()
        if isinstance(other, PersistentList):
            self.data += other.data
        else:
            self.data += list(other)
        return self

    def __mul__(self, n):
        return self.__class__(self.data * n)

    __rmul__ = __mul__

    def __imul__(self, n):
        self._p_note_change()
        self.data *= n
        return self

    def append(self, item):
        self._p_note_change()
        self.data.append(item)

    def insert(self, i, item):
        self._p_note_change()
        self.data.insert(i, item)

    def pop(self, i=-1):
        self._p_note_change()
        return self.data.pop(i)

    def remove(self, item):
        self._p_note_change()
        self.data.remove(item)

    def count(self, item):
        return self.data.count(item)

    def index(self, item, *args):
        return self.data.index(item, *args)

    def reverse(self):
        self._p_note_change()
        self.data.reverse()

    def sort(self, *args, **kwargs):
        self._p_note_change()
        self.data.sort(*args, **kwargs)

    def extend(self, other):
        self._p_note_change()
        if isinstance(other, PersistentList):
            self.data.extend(other.data)
        else:
            self.data.extend(other)

    # ── Async persistence methods ─────────────────────────────────
    # The sync list operations are already non-blocking (in-memory).
    # These async methods handle connection.commit() / abort() calls.

    async def append_async(self, item: Any) -> None:
        """Async append — delegates to sync append()."""
        self.append(item)

    async def get_async(self, i: int) -> Any:
        """Async getitem — delegates to sync __getitem__."""
        return self[i]

    async def set_async(self, i: int, item: Any) -> None:
        """Async setitem — delegates to sync __setitem__."""
        self[i] = item

    async def delete_async(self, i: int) -> Any:
        """Async delitem — delegates to sync __delitem__."""
        del self[i]

    async def length_async(self) -> int:
        """Async len — delegates to sync __len__."""
        return len(self)

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
