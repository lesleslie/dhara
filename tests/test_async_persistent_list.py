"""Tests for dhara.collections.list.AsyncPersistentList async methods."""

from __future__ import annotations

import pytest

from dhara.collections.list import PersistentList


class TestAppendAsync:
    @pytest.mark.asyncio
    async def test_append_async(self):
        """append_async appends to data and commits."""
        from dhara.storage.memory import AsyncMemoryStorage
        from dhara.core.connection import AsyncConnection

        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        root = await conn.get_root()
        lst = PersistentList()
        # Set _p_connection directly via object.__setattr__ to avoid _p_note_change
        object.__setattr__(lst, "_p_connection", conn)
        object.__setattr__(lst, "_p_oid", root._p_oid)
        lst._p_set_status_unsaved()
        await lst.append_async("item")
        assert lst.data == ["item"]



class TestGetAsync:
    @pytest.mark.asyncio
    async def test_get_async_existing(self):
        pl = PersistentList([10, 20, 30])
        result = await pl.get_async(1)
        assert result == 20

    @pytest.mark.asyncio
    async def test_get_async_negative_index(self):
        pl = PersistentList([10, 20, 30])
        result = await pl.get_async(-1)
        assert result == 30


class TestSetAsync:
    @pytest.mark.asyncio
    async def test_set_async(self):
        from dhara.storage.memory import AsyncMemoryStorage
        from dhara.core.connection import AsyncConnection

        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        root = await conn.get_root()
        pl = PersistentList([1, 2, 3])
        object.__setattr__(pl, "_p_connection", conn)
        object.__setattr__(pl, "_p_oid", root._p_oid)
        pl._p_set_status_unsaved()
        await pl.set_async(1, 99)
        assert pl[1] == 99


class TestDeleteAsync:
    @pytest.mark.asyncio
    async def test_delete_async(self):
        from dhara.storage.memory import AsyncMemoryStorage
        from dhara.core.connection import AsyncConnection

        storage = AsyncMemoryStorage()
        await storage.init()
        conn = await AsyncConnection.new(storage)
        root = await conn.get_root()
        pl = PersistentList([1, 2, 3])
        object.__setattr__(pl, "_p_connection", conn)
        object.__setattr__(pl, "_p_oid", root._p_oid)
        pl._p_set_status_unsaved()
        await pl.delete_async(0)
        assert pl.data == [2, 3]


class TestLengthAsync:
    @pytest.mark.asyncio
    async def test_length_async(self):
        pl = PersistentList([1, 2, 3])
        result = await pl.length_async()
        assert result == 3


class TestCommitAsync:
    @pytest.mark.asyncio
    async def test_commit_async_no_connection(self):
        """With no connection, commit_async should not raise."""
        pl = PersistentList()
        await pl.commit_async()


class TestAbortAsync:
    @pytest.mark.asyncio
    async def test_abort_async_no_connection(self):
        """With no connection, abort_async should not raise."""
        pl = PersistentList()
        await pl.abort_async()
