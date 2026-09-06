"""Extended tests for dhara.core.connection — coverage push.

Targets uncovered branches in AsyncConnection and Connection.abort()
that the existing test suite misses:

- AsyncConnection.new_oid() sync OID allocation
- AsyncConnection.get_cache() sync getter
- AsyncConnection.get(int) with non-byte_string oid
- AsyncConnection.get_crawler else branch (load uncached / re-load ghosts)
- AsyncConnection.load_state()
- AsyncConnection._sync() body (ghostifies cached invalid oids)
- AsyncConnection._handle_invalidations() all branches
- AsyncConnection.commit() no-changes path
- AsyncConnection.commit() with new_objects / ConflictError rollback
- AsyncConnection.new() TypeError validation (missing methods / non-callable new_oid)
- Connection.abort() async cache.clear path (line 320)
- create_async_connection() factory function
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dhara.collections.dict import PersistentDict
from dhara.core.connection import (
    ROOT_OID,
    AsyncConnection,
    Cache,
    Connection,
    ObjectReader,
    create_async_connection,
)
from dhara.error import ConflictError, DruvaKeyError, ReadConflictError, WriteConflictError
from dhara.storage.memory import AsyncMemoryStorage
from dhara.utils import int8_to_str


# ===========================================================================
# AsyncConnection.new_oid (sync counter)
# ===========================================================================


class TestAsyncConnectionNewOid:
    async def test_new_oid_returns_bytes(self):
        """new_oid returns a bytes OID on each call."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)
            oid = conn.new_oid()
            assert isinstance(oid, bytes)
            assert len(oid) == 8
        finally:
            await storage.close()

    async def test_new_oid_increments_counter(self):
        """new_oid returns distinct OIDs on each call (counter increments)."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)
            first = conn.new_oid()
            second = conn.new_oid()
            third = conn.new_oid()
            assert first != second
            assert second != third
            assert first != third
        finally:
            await storage.close()

    async def test_new_oid_initial_counter_state(self):
        """new_oid counter starts at 0 and increments from there."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)
            assert conn._last_oid == 0
            oid = conn.new_oid()
            assert conn._last_oid == 1
            assert oid == int8_to_str(1)
        finally:
            await storage.close()


# ===========================================================================
# AsyncConnection.get_cache (sync getter)
# ===========================================================================


class TestAsyncConnectionGetCache:
    async def test_get_cache_returns_cache(self):
        """get_cache returns the underlying Cache instance."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)
            cache = conn.get_cache()
            assert isinstance(cache, Cache)
            assert cache is conn.cache
        finally:
            await storage.close()

    async def test_get_cache_respects_cache_size(self):
        """get_cache returns a Cache with the configured size."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage, cache_size=42)
            cache = conn.get_cache()
            assert cache.get_size() == 42
        finally:
            await storage.close()


# ===========================================================================
# AsyncConnection.get with int OID (line 564)
# ===========================================================================


class TestAsyncConnectionGetIntOid:
    async def test_get_with_int_oid_returns_root(self):
        """AsyncConnection.get(int) converts to bytes and returns the matching object."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)
            # Pass integer 0 — should convert to ROOT_OID
            obj = await conn.get(0)
            assert obj is not None
            assert obj._p_oid == ROOT_OID
        finally:
            await storage.close()


# ===========================================================================
# AsyncConnection.get_crawler else branch (lines 598-606)
# ===========================================================================


class TestAsyncConnectionGetCrawlerElseBranch:
    async def test_get_crawler_loads_uncached_objects(self):
        """get_crawler yields objects loaded from storage when not in cache."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)
            root = await conn.get_root()
            root["k"] = "v"
            await conn.commit()

            # Reset cache to force loading from storage
            conn.cache = Cache(100)

            crawled = []
            async for obj in conn.get_crawler():
                crawled.append(obj)
            assert len(crawled) >= 1
            # Should have loaded objects (not from cache hits)
            assert any(obj._p_oid == ROOT_OID for obj in crawled)
        finally:
            await storage.close()

    async def test_get_crawler_rel_oads_ghost_objects(self):
        """get_crawler reloads state when cached object is a ghost."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)
            root = await conn.get_root()
            root["k"] = "v"
            await conn.commit()

            # Mark cached root as ghost so get_crawler must reload it
            root._p_set_status_ghost()

            crawled = []
            async for obj in conn.get_crawler():
                crawled.append(obj)
            # After crawling, the ghost object should have its state loaded
            assert len(crawled) >= 1
            assert not root._p_is_ghost()
        finally:
            await storage.close()


# ===========================================================================
# AsyncConnection.load_state (lines 615-627)
# ===========================================================================


class TestAsyncConnectionLoadState:
    async def test_load_state_on_ghost(self):
        """load_state loads state for a ghost object from storage."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)
            root = await conn.get_root()
            root["k"] = "v"
            await conn.commit()

            # Mark as ghost
            root._p_set_status_ghost()
            assert root._p_is_ghost()

            await conn.load_state(root)
            assert not root._p_is_ghost()
        finally:
            await storage.close()

    async def test_load_state_raises_when_storage_none(self):
        """load_state raises AssertionError when storage is None."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)
            root = await conn.get_root()
            root._p_set_status_ghost()
            conn.storage = None
            with pytest.raises(AssertionError, match="connection is closed"):
                await conn.load_state(root)
        finally:
            await storage.close()

    async def test_load_state_missing_record_raises_read_conflict(self):
        """load_state raises ReadConflictError when storage has no record for the oid."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)
            root = await conn.get_root()
            root._p_set_status_ghost()

            # Patch get_stored_pickle to simulate missing record
            with patch.object(
                conn, "get_stored_pickle", side_effect=DruvaKeyError("missing")
            ):
                with pytest.raises(ReadConflictError):
                    await conn.load_state(root)
        finally:
            await storage.close()


# ===========================================================================
# AsyncConnection._sync (lines 676-678)
# ===========================================================================


class TestAsyncConnectionSync:
    async def test_sync_clears_invalid_oids(self):
        """_sync clears the invalid_oids set."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)
            conn.invalid_oids.add(int8_to_str(99))
            await conn._sync()
            assert len(conn.invalid_oids) == 0
        finally:
            await storage.close()

    async def test_sync_ghostifies_invalid_cached_object(self):
        """_sync ghostifies a cached object whose OID is in invalid_oids."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)
            root = await conn.get_root()
            root._p_set_status_saved()
            conn.invalid_oids.add(ROOT_OID)

            await conn._sync()
            assert root._p_is_ghost()
            assert len(conn.invalid_oids) == 0
        finally:
            await storage.close()

    async def test_sync_keeps_uncached_invalid_oids_noop(self):
        """_sync does not fail when invalid oid is not in cache."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)
            # OID 99 was never loaded into cache
            conn.invalid_oids.add(int8_to_str(99))
            await conn._sync()
            assert len(conn.invalid_oids) == 0
        finally:
            await storage.close()


# ===========================================================================
# AsyncConnection._handle_invalidations (lines 686-701)
# ===========================================================================


class TestAsyncConnectionHandleInvalidations:
    async def test_handle_invalidations_no_conflicts(self):
        """Empty oids list — no conflict raised."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)
            await conn._handle_invalidations([])
        finally:
            await storage.close()

    async def test_handle_invalidations_unknown_oids_ignored(self):
        """OIDs not in cache are silently skipped."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)
            await conn._handle_invalidations([int8_to_str(99999)])
        finally:
            await storage.close()

    async def test_handle_invalidations_write_conflict(self):
        """When a cached object's serial matches current, WriteConflictError is raised."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)
            root = await conn.get_root()
            root._p_serial = await conn.get_transaction_serial()

            with pytest.raises(WriteConflictError):
                await conn._handle_invalidations([ROOT_OID])
            assert ROOT_OID in conn.invalid_oids
        finally:
            await storage.close()

    async def test_handle_invalidations_read_conflict_with_read_oid(self):
        """When read_oid is supplied, ReadConflictError is raised instead."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)
            root = await conn.get_root()
            root._p_serial = await conn.get_transaction_serial()

            with pytest.raises(ReadConflictError):
                await conn._handle_invalidations([ROOT_OID], read_oid=ROOT_OID)
        finally:
            await storage.close()

    async def test_handle_invalidations_ghostifies_non_ghost(self):
        """When serial doesn't match, non-ghost object is ghostified (no raise)."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)
            root = await conn.get_root()
            # Use an OID that's different from ROOT_OID to avoid conflict
            # with the root object's normal state.
            other_oid = int8_to_str(42)
            root._p_oid = other_oid
            root._p_serial = 0  # old serial, not current
            root._p_set_status_saved()
            conn.cache[other_oid] = root

            await conn._handle_invalidations([other_oid])
            # Object should be ghostified
            assert root._p_is_ghost()
        finally:
            await storage.close()

    async def test_handle_invalidations_keeps_existing_ghost(self):
        """When oid is in cache but object is already a ghost, nothing changes."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)
            root = await conn.get_root()
            root._p_oid = ROOT_OID
            root._p_set_status_ghost()

            await conn._handle_invalidations([ROOT_OID])
            # Already a ghost — should remain a ghost
            assert root._p_is_ghost()
        finally:
            await storage.close()


# ===========================================================================
# AsyncConnection.commit — no-changes and conflict rollback paths
# ===========================================================================


class TestAsyncConnectionCommitNoChanges:
    async def test_commit_with_no_changes_calls_sync_and_increments_serial(self):
        """commit() with no changes calls _sync and increments the serial."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)
            serial_before = await conn.get_transaction_serial()
            await conn.commit()
            assert await conn.get_transaction_serial() == serial_before + 1
        finally:
            await storage.close()


class TestAsyncConnectionCommitConflictRollback:
    async def test_commit_rolls_back_new_objects_on_conflict(self):
        """When storage.end raises ConflictError, new_objects are reset and cache cleaned."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)
            # Manually create changed object + a sibling new_obj that the writer will yield.
            changed_obj = MagicMock()
            changed_obj._p_oid = ROOT_OID
            changed_obj._p_set_status_saved = MagicMock()

            new_obj = MagicMock()
            new_obj._p_oid = b"\x00\x00\x00\x00\x00\x00\x00\x05"
            new_obj._p_set_status_saved = MagicMock()
            new_obj._p_set_status_unsaved = MagicMock()
            new_obj._p_connection = conn

            conn.changed = {changed_obj._p_oid: changed_obj}

            writer = MagicMock()
            writer.gen_new_objects.return_value = [changed_obj, new_obj, new_obj]
            writer.get_state.side_effect = [
                (b"data1", b"refs1"),
                (b"data2", b"refs2"),
            ]
            writer.close = MagicMock()

            original_end = storage.end

            async def conflict_end(handle_invalidations=None):
                raise ConflictError([b"\x00\x00\x00\x00\x00\x00\x00\x05"])

            storage.end = conflict_end

            with patch("dhara.core.connection.ObjectWriter", return_value=writer):
                with patch(
                    "dhara.core.connection.pack_record",
                    side_effect=lambda oid, data, refs: (oid, data, refs),
                ):
                    with pytest.raises(ConflictError):
                        await conn.commit()

            assert new_obj._p_oid is None
            assert new_obj._p_connection is None
            new_obj._p_set_status_unsaved.assert_called_once()
            assert new_obj._p_oid not in conn.cache
        finally:
            await storage.close()

    async def test_commit_new_object_flow_without_rollback(self):
        """Normal commit path with new_object branch (no ConflictError)."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)

            changed_obj = MagicMock()
            changed_obj._p_oid = ROOT_OID
            changed_obj._p_set_status_saved = MagicMock()

            unsaved_obj = MagicMock()
            unsaved_obj._p_oid = b"\x00\x00\x00\x00\x00\x00\x00\x06"
            unsaved_obj._p_set_status_saved = MagicMock()
            # Hold strong refs so the ObjectDictionary weakref doesn't get GC'd
            keep_alive = [changed_obj, unsaved_obj]

            conn.changed = {changed_obj._p_oid: changed_obj}
            cache_count_before = conn.cache.get_count()

            writer = MagicMock()
            writer.gen_new_objects.return_value = [changed_obj, unsaved_obj]
            writer.get_state.side_effect = [
                (b"data1", b"refs1"),
                (b"data2", b"refs2"),
            ]
            writer.close = MagicMock()

            with patch("dhara.core.connection.ObjectWriter", return_value=writer):
                with patch(
                    "dhara.core.connection.pack_record",
                    side_effect=lambda oid, data, refs: (oid, data, refs),
                ):
                    await conn.commit()

            # unsaved_obj should be tracked in conn.cache after the commit
            assert conn.cache.get_count() == cache_count_before + 1
            unsaved_obj._p_set_status_saved.assert_called_once()
            assert keep_alive  # silence unused warning
        finally:
            await storage.close()

    async def test_commit_skips_oid_already_in_new_objects(self):
        """When writer yields the same new object twice, the second iteration is skipped."""
        storage = AsyncMemoryStorage()
        await storage.init()
        try:
            conn = await AsyncConnection.new(storage)

            changed_obj = MagicMock()
            changed_obj._p_oid = ROOT_OID
            changed_obj._p_set_status_saved = MagicMock()

            new_obj = MagicMock()
            new_obj._p_oid = b"\x00\x00\x00\x00\x00\x00\x00\x07"
            new_obj._p_set_status_saved = MagicMock()
            # Hold strong refs so the ObjectDictionary weakref doesn't get GC'd
            keep_alive = [changed_obj, new_obj]

            conn.changed = {changed_obj._p_oid: changed_obj}

            writer = MagicMock()
            # Yield changed_obj, then new_obj twice — second visit hits the `continue`
            writer.gen_new_objects.return_value = [changed_obj, new_obj, new_obj]
            writer.get_state.side_effect = [
                (b"data1", b"refs1"),
                (b"data2", b"refs2"),
                (b"data2", b"refs2"),  # Would be called if not for `continue`
            ]
            writer.close = MagicMock()

            with patch("dhara.core.connection.ObjectWriter", return_value=writer):
                with patch(
                    "dhara.core.connection.pack_record",
                    side_effect=lambda oid, data, refs: (oid, data, refs),
                ):
                    await conn.commit()

            # Only 2 get_state calls (changed_obj + new_obj once). Third call would
            # mean the `continue` branch was missed.
            assert writer.get_state.call_count == 2
            assert keep_alive  # silence unused warning
        finally:
            await storage.close()


# ===========================================================================
# AsyncConnection.new TypeError validation (lines 459, 463)
# ===========================================================================


class TestAsyncConnectionNewValidation:
    async def test_new_raises_when_storage_missing_required_methods(self):
        """AsyncConnection.new raises TypeError when storage is missing required methods."""
        # Empty spec — no attributes at all
        storage = MagicMock(spec=[])
        with pytest.raises(TypeError, match="missing init"):
            await AsyncConnection.new(storage)

    async def test_new_raises_when_new_oid_not_callable(self):
        """AsyncConnection.new raises TypeError when new_oid attribute is not callable."""
        storage = MagicMock()
        # Spec the required methods so hasattr check passes
        storage.init = AsyncMock()
        storage.load = AsyncMock()
        storage.begin = AsyncMock()
        storage.store = AsyncMock()
        storage.end = AsyncMock()
        storage.sync = AsyncMock()
        storage.gen_oid_record = AsyncMock()
        # new_oid exists but is not callable
        storage.new_oid = "not-a-callable"

        with pytest.raises(TypeError, match="new_oid not callable"):
            await AsyncConnection.new(storage)


# ===========================================================================
# Connection.abort() async cache.clear path (line 320)
# ===========================================================================


class TestConnectionAbortAsyncCacheClear:
    def test_abort_schedules_async_cache_clear(self):
        """abort() schedules cache.clear via asyncio.create_task when cache.clear is async."""
        mock_storage = MagicMock()
        mock_storage.sync.return_value = []
        mock_storage.new_oid.return_value = "0" * 16

        mock_cache = MagicMock()

        async def async_clear():
            return None

        mock_cache.clear = async_clear

        with patch.object(
            Connection,
            "__init__",
            lambda self, storage, cache_size=100000, root_class=None, cache=None, allowed_modules=None: None,
        ):
            conn = object.__new__(Connection)
            conn.storage = mock_storage
            conn.cache = mock_cache
            conn.changed = {}
            conn.invalid_oids = set()
            conn.new_oid = mock_storage.new_oid
            conn.transaction_serial = 0

            # abort() should schedule the coroutine via asyncio.create_task.
            # We patch asyncio.create_task to capture the coroutine without running it.
            with patch("dhara.core.connection.asyncio.create_task") as mock_create_task:
                conn.abort()
                mock_create_task.assert_called_once()

    def test_abort_calls_sync_cache_clear_directly(self):
        """abort() calls cache.clear() directly when it's a sync function."""
        mock_storage = MagicMock()
        mock_storage.sync.return_value = []
        mock_storage.new_oid.return_value = "0" * 16

        mock_cache = MagicMock()
        # Default MagicMock.clear is not async — should be called directly
        mock_cache.clear = MagicMock()

        with patch.object(
            Connection,
            "__init__",
            lambda self, storage, cache_size=100000, root_class=None, cache=None, allowed_modules=None: None,
        ):
            conn = object.__new__(Connection)
            conn.storage = mock_storage
            conn.cache = mock_cache
            conn.changed = {}
            conn.invalid_oids = set()
            conn.new_oid = mock_storage.new_oid
            conn.transaction_serial = 0

            conn.abort()
            mock_cache.clear.assert_called_once()

    def test_abort_works_without_cache_clear_attribute(self):
        """abort() is a no-op for cache.clear when cache has no clear attribute."""
        mock_storage = MagicMock()
        mock_storage.sync.return_value = []
        mock_storage.new_oid.return_value = "0" * 16

        # Build a cache that lacks `clear` attribute but has shrink for abort
        mock_cache = MagicMock(spec=["get", "set_size", "shrink", "get_count"])
        # Note: spec strips out `clear`

        with patch.object(
            Connection,
            "__init__",
            lambda self, storage, cache_size=100000, root_class=None, cache=None, allowed_modules=None: None,
        ):
            conn = object.__new__(Connection)
            conn.storage = mock_storage
            conn.cache = mock_cache
            conn.changed = {}
            conn.invalid_oids = set()
            conn.new_oid = mock_storage.new_oid
            conn.transaction_serial = 0

            # Should not raise — the hasattr guard skips the clear branch
            conn.abort()


# ===========================================================================
# create_async_connection factory (lines 784-788)
# ===========================================================================


class TestCreateAsyncConnection:
    async def test_create_async_connection_with_str_path(self, tmp_path):
        """create_async_connection accepts a string path and returns an initialized AsyncConnection."""
        path = str(tmp_path / "factory.dhara")
        conn = await create_async_connection(path)
        try:
            assert isinstance(conn, AsyncConnection)
            root = await conn.get_root()
            assert root is not None
        finally:
            storage = await conn.get_storage()
            await storage.close()

    async def test_create_async_connection_with_cache_size(self, tmp_path):
        """create_async_connection honors the cache_size argument."""
        path = str(tmp_path / "factory_sized.dhara")
        conn = await create_async_connection(path, cache_size=200)
        try:
            cache = conn.get_cache()
            assert cache.get_size() == 200
        finally:
            storage = await conn.get_storage()
            await storage.close()

    async def test_create_async_connection_with_root_class(self, tmp_path):
        """create_async_connection honors the root_class argument."""
        path = str(tmp_path / "factory_class.dhara")
        conn = await create_async_connection(path, root_class=PersistentDict)
        try:
            root = await conn.get_root()
            assert isinstance(root, PersistentDict)
        finally:
            storage = await conn.get_storage()
            await storage.close()
