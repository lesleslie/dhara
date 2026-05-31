"""Tests for dhara.collections.btree async wrapper methods."""

from __future__ import annotations

import pytest

from dhara.collections.btree import BTree


class TestBtreeAsyncWrapper:
    @pytest.mark.asyncio
    async def test_set_async(self):
        tree = BTree()
        await tree.set_async("key", "value")
        # Verify using the sync _get_impl (direct tree access)
        result = tree._get_impl("key")
        assert result == "value"

    @pytest.mark.asyncio
    async def test_get_async(self):
        tree = BTree()
        tree._set_impl("key", "value")
        result = await tree.get_async("key")
        assert result == "value"

    @pytest.mark.asyncio
    async def test_get_async_missing(self):
        tree = BTree()
        result = await tree.get_async("missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_async(self):
        tree = BTree()
        tree._set_impl("key", "value")
        result = await tree.delete_async("key")
        assert result is True
        assert tree._get_impl("key") is None

    @pytest.mark.asyncio
    async def test_delete_async_missing(self):
        tree = BTree()
        result = await tree.delete_async("missing")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_async(self):
        tree = BTree()
        tree._set_impl("key", "value1")
        result = await tree.update_async("key", "value2")
        assert result is True
        assert tree._get_impl("key") == "value2"

    @pytest.mark.asyncio
    async def test_update_async_missing(self):
        tree = BTree()
        result = await tree.update_async("missing", "value")
        assert result is False

    @pytest.mark.asyncio
    async def test_items_async(self):
        tree = BTree()
        tree._set_impl("a", "1")
        tree._set_impl("b", "2")
        tree._set_impl("c", "3")
        items = [item async for item in tree.items_async()]
        assert len(items) == 3

    @pytest.mark.asyncio
    async def test_keys_async(self):
        tree = BTree()
        tree._set_impl("x", "1")
        tree._set_impl("y", "2")
        keys = [k async for k in tree.keys_async()]
        assert len(keys) == 2

    @pytest.mark.asyncio
    async def test_values_async(self):
        tree = BTree()
        tree._set_impl("a", "one")
        tree._set_impl("b", "two")
        values = [v async for v in tree.values_async()]
        assert len(values) == 2
