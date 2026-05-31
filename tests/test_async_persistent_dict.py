"""Tests for dhara.collections.dict.AsyncPersistentDict async methods."""

from __future__ import annotations

import pytest

from dhara.collections.dict import PersistentDict


class TestCommitAsync:
    @pytest.mark.asyncio
    async def test_commit_async_no_connection(self):
        """With no connection, commit_async should not raise."""
        d = PersistentDict()
        await d.commit_async()


class TestAbortAsync:
    @pytest.mark.asyncio
    async def test_abort_async_no_connection(self):
        """With no connection, abort_async should not raise."""
        d = PersistentDict()
        await d.abort_async()
