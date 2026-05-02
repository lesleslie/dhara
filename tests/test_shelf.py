"""Tests for dhara.shelf -- Shelf, OffsetMap, and read_transaction_offsets."""

from __future__ import annotations

import os
import sys

import pytest

from dhara.file import File
from dhara.shelf import OffsetMap, Shelf, read_transaction_offsets
from dhara.utils import (
    ShortRead,
    int8_to_str,
    read,
    str_to_int8,
    write,
    write_int8,
)


# ── Helpers ──


def make_name(n):
    """Create an 8-byte name from an integer OID."""
    return int8_to_str(n)


def make_items(count, value_prefix=b"val", start=0):
    """Create a list of (name, value) pairs for shelf items.

    Args:
        count: Number of items to create.
        value_prefix: Prefix for the value string.
        start: Starting OID index (default 0).
    """
    return [(make_name(start + i), f"{value_prefix.decode()}-{start + i}".encode()) for i in range(count)]


# ── Fixtures ──


@pytest.fixture
def shelf_file(tmp_path):
    return tmp_path / "test.shelf"


@pytest.fixture
def open_shelf(shelf_file):
    """Provide a Shelf opened on a temp file, closed after the test."""
    file = File(str(shelf_file))
    shelf = Shelf(file=file)
    yield shelf
    shelf.close()


@pytest.fixture
def populated_shelf(shelf_file):
    """Provide a Shelf with 5 items pre-loaded, closed after the test."""
    items = make_items(5)
    file = File(str(shelf_file))
    shelf = Shelf(file=file, items=items)
    yield shelf, items
    shelf.close()


# ── 1. TestShelfFormat ──


class TestShelfFormat:
    """Test Shelf.has_format() with valid and invalid files."""

    def test_valid_format(self, shelf_file):
        """A properly created shelf file is recognized."""
        file = File(str(shelf_file))
        shelf = Shelf(file=file)
        shelf.close()
        # Reopen and verify format
        file2 = File(str(shelf_file))
        assert Shelf.has_format(file2) is True
        file2.close()

    def test_empty_file_has_no_format(self, shelf_file):
        """An empty file does not have shelf format."""
        file = File(str(shelf_file))
        assert Shelf.has_format(file) is False
        file.close()

    def test_garbage_file_has_no_format(self, shelf_file):
        """A file with garbage data does not have shelf format."""
        file = File(str(shelf_file))
        write(file, b"GARBAGE-DATA-HERE" * 10)
        file.seek(0)
        assert Shelf.has_format(file) is False
        file.close()

    def test_truncated_prefix(self, shelf_file):
        """A file with only part of the prefix is not recognized."""
        file = File(str(shelf_file))
        prefix = Shelf.prefix
        write(file, prefix[:4])  # Write only first 4 bytes
        file.seek(0)
        assert Shelf.has_format(file) is False
        file.close()

    def test_prefix_constant(self):
        """Verify the prefix is the expected value."""
        assert Shelf.prefix == b"SHELF-1\n"
        assert len(Shelf.prefix) == 8

    def test_has_format_seeks_to_start(self, shelf_file):
        """has_format resets file position to 0 before reading."""
        file = File(str(shelf_file))
        Shelf(file=file)  # Creates a valid shelf
        file.seek(100, 0)  # Move to arbitrary position
        assert Shelf.has_format(file) is True
        # After reading the 8-byte prefix, position is at 8
        assert file.tell() == len(Shelf.prefix)
        file.close()


# ── 2. TestShelfGeneration ──


class TestShelfGeneration:
    """Test Shelf.generate_shelf() with empty and non-empty items."""

    def test_generate_empty_shelf(self, shelf_file):
        """Creating a shelf with no items produces a valid empty shelf."""
        file = File(str(shelf_file))
        for _ in Shelf.generate_shelf(file=file, items=[]):
            pass
        file.seek_end()
        assert file.tell() > 0  # File should have content (prefix + empty transaction + offset map)
        file.close()

    def test_generate_with_items(self, shelf_file):
        """Creating a shelf with items writes all items and returns yields."""
        items = make_items(3)
        file = File(str(shelf_file))
        yields = []
        for val in Shelf.generate_shelf(file=file, items=items):
            yields.append(val)
        file.close()
        # Yields include count decrements during generation
        assert len(yields) > 0

    def test_generate_shelf_fails_on_nonempty_file(self, shelf_file):
        """generate_shelf raises ValueError on a non-empty file."""
        file = File(str(shelf_file))
        write(file, b"existing data")
        file.seek(0)
        with pytest.raises(ValueError):
            for _ in Shelf.generate_shelf(file=file, items=[]):
                pass
        file.close()

    def test_generate_and_reopen(self, shelf_file):
        """A generated shelf can be reopened and read."""
        items = make_items(5)
        file = File(str(shelf_file))
        for _ in Shelf.generate_shelf(file=file, items=items):
            pass
        file.close()
        # Reopen
        file2 = File(str(shelf_file))
        shelf = Shelf(file=file2)
        # Verify all items are accessible
        for name, value in items:
            assert shelf.get_value(name) == value
        shelf.close()

    def test_generate_single_item(self, shelf_file):
        """A shelf with a single item works correctly."""
        name = make_name(42)
        value = b"the-answer"
        file = File(str(shelf_file))
        for _ in Shelf.generate_shelf(file=file, items=[(name, value)]):
            pass
        file.close()
        file2 = File(str(shelf_file))
        shelf = Shelf(file=file2)
        assert shelf.get_value(name) == value
        shelf.close()


# ── 3. TestShelfInit ──


class TestShelfInit:
    """Test Shelf.__init__() variations."""

    def test_init_with_file_path(self, shelf_file):
        """Shelf can be initialized with a file path string."""
        shelf = Shelf(file=str(shelf_file))
        assert Shelf.has_format(shelf.file)
        shelf.close()

    def test_init_with_none_creates_temp(self):
        """Shelf with file=None creates a temporary file."""
        shelf = Shelf(file=None)
        assert shelf.file is not None
        assert Shelf.has_format(shelf.file)
        shelf.close()

    def test_init_empty_file_auto_generates(self, shelf_file):
        """Opening an empty file auto-generates shelf format."""
        file = File(str(shelf_file))
        shelf = Shelf(file=file)
        assert Shelf.has_format(shelf.file)
        shelf.close()

    def test_init_with_items_creates_shelf(self, shelf_file):
        """Providing items during init creates a populated shelf."""
        items = make_items(3)
        file = File(str(shelf_file))
        shelf = Shelf(file=file, items=items)
        for name, value in items:
            assert shelf.get_value(name) == value
        shelf.close()

    def test_init_with_items_on_existing_fails(self, shelf_file):
        """Providing items on a non-empty file should fail."""
        # First create a shelf
        file = File(str(shelf_file))
        Shelf(file=file)
        file.close()
        # Try to open with items
        file2 = File(str(shelf_file))
        with pytest.raises(AssertionError):
            Shelf(file=file2, items=make_items(1))
        file2.close()

    def test_init_readonly(self, shelf_file):
        """Shelf can be opened in readonly mode."""
        items = make_items(2)
        file = File(str(shelf_file))
        shelf = Shelf(file=file, items=items)
        shelf.close()
        # Reopen readonly
        file2 = File(str(shelf_file), readonly=True)
        shelf2 = Shelf(file=file2, readonly=True)
        assert shelf2.get_value(items[0][0]) == items[0][1]
        shelf2.close()


# ── 4. TestShelfStore ──


class TestShelfStore:
    """Test Shelf.store() method."""

    def test_store_new_items(self, open_shelf):
        """Storing new items returns correct (name, old_pos, new_pos) triples."""
        items = make_items(3)
        result = open_shelf.store(items)
        assert len(result) == 3
        for i, (name, old_pos, new_pos) in enumerate(result):
            assert name == items[i][0]
            assert old_pos is None  # New items have no old position
            assert new_pos is not None

    def test_store_updates_existing(self, populated_shelf):
        """Storing an existing name updates its position."""
        shelf, items = populated_shelf
        name, old_value = items[0]
        new_value = b"updated-value"
        result = shelf.store([(name, new_value)])
        assert len(result) == 1
        stored_name, old_pos, new_pos = result[0]
        assert stored_name == name
        assert old_pos is not None  # Had a previous position
        assert new_pos is not None
        # Verify the value is updated
        assert shelf.get_value(name) == new_value

    def test_store_mixed_new_and_existing(self, populated_shelf):
        """Storing a mix of new and existing items works correctly."""
        shelf, items = populated_shelf
        existing_name = items[0][0]
        new_name = make_name(100)
        new_value = b"brand-new"
        result = shelf.store([
            (existing_name, b"updated"),
            (new_name, new_value),
        ])
        assert len(result) == 2
        assert result[0][1] is not None  # existing had old pos
        assert result[1][1] is None  # new has no old pos

    def test_store_empty_sequence(self, open_shelf):
        """Storing an empty sequence returns empty result."""
        result = open_shelf.store([])
        assert result == []

    def test_store_single_item(self, open_shelf):
        """Storing a single item works correctly."""
        name = make_name(1)
        value = b"single"
        result = open_shelf.store([(name, value)])
        assert len(result) == 1
        assert result[0][0] == name
        assert open_shelf.get_value(name) == value

    def test_store_persists_across_reopen(self, shelf_file):
        """Stored items survive reopen."""
        items = make_items(3)
        file = File(str(shelf_file))
        shelf = Shelf(file=file, items=items)
        extra_name = make_name(50)
        extra_value = b"extra"
        shelf.store([(extra_name, extra_value)])
        shelf.close()
        # Reopen
        file2 = File(str(shelf_file))
        shelf2 = Shelf(file=file2)
        assert shelf2.get_value(extra_name) == extra_value
        for name, value in items:
            assert shelf2.get_value(name) == value
        shelf2.close()

    def test_store_rollback_on_exception(self, open_shelf):
        """If store fails partway, the file is truncated (rollback)."""
        name = make_name(1)
        value = b"good-value"
        open_shelf.store([(name, value)])
        pos_before = open_shelf.file.tell()

        # Force an exception by providing a non-bytes value
        with pytest.raises(Exception):
            open_shelf.store([(name, 12345)])  # type: ignore[arg-type]

        # File should be truncated back to pos_before
        assert open_shelf.file.tell() == pos_before
        # Original value should still be intact
        assert open_shelf.get_value(name) == value

    def test_store_multiple_transactions(self, open_shelf):
        """Multiple store calls create sequential transactions."""
        items1 = make_items(3, b"batch1", start=0)
        items2 = make_items(3, b"batch2", start=10)
        result1 = open_shelf.store(items1)
        result2 = open_shelf.store(items2)
        assert len(result1) == 3
        assert len(result2) == 3
        # All items from both batches should be readable
        for name, value in items1 + items2:
            assert open_shelf.get_value(name) == value


# ── 5. TestShelfGet ──


class TestShelfGet:
    """Test get_position(), get_value(), get_item_at_position()."""

    def test_get_position_new_item(self, open_shelf):
        """get_position returns None for unknown names."""
        name = make_name(999)
        assert open_shelf.get_position(name) is None

    def test_get_position_after_store(self, open_shelf):
        """get_position returns a valid position after store."""
        name = make_name(1)
        value = b"test"
        result = open_shelf.store([(name, value)])
        pos = open_shelf.get_position(name)
        assert pos is not None
        assert pos == result[0][2]  # Should match new_pos from store

    def test_get_position_invalid_length(self, open_shelf):
        """get_position raises ValueError for non-8-byte names."""
        with pytest.raises(ValueError, match="8 bytes"):
            open_shelf.get_position(b"short")
        with pytest.raises(ValueError, match="8 bytes"):
            open_shelf.get_position(b"toolongname")

    def test_get_value_new_item(self, open_shelf):
        """get_value returns None for unknown names."""
        assert open_shelf.get_value(make_name(999)) is None

    def test_get_value_after_store(self, open_shelf):
        """get_value returns the stored value."""
        name = make_name(5)
        value = b"hello-world"
        open_shelf.store([(name, value)])
        assert open_shelf.get_value(name) == value

    def test_get_value_returns_latest(self, open_shelf):
        """get_value returns the most recently stored value."""
        name = make_name(10)
        open_shelf.store([(name, b"v1")])
        open_shelf.store([(name, b"v2")])
        open_shelf.store([(name, b"v3")])
        assert open_shelf.get_value(name) == b"v3"

    def test_get_item_at_position(self, populated_shelf):
        """get_item_at_position returns (name, value) at a position."""
        shelf, items = populated_shelf
        name, value = items[0]
        pos = shelf.get_position(name)
        assert pos is not None
        item_name, item_value = shelf.get_item_at_position(pos)
        assert item_name == name
        assert item_value == value

    def test_get_value_empty_value(self, open_shelf):
        """get_value works with an empty value."""
        name = make_name(7)
        open_shelf.store([(name, b"")])
        assert open_shelf.get_value(name) == b""

    def test_get_value_large_value(self, open_shelf):
        """get_value works with a large value."""
        name = make_name(8)
        value = b"x" * 10000
        open_shelf.store([(name, value)])
        assert open_shelf.get_value(name) == value


# ── 6. TestShelfIteration ──


class TestShelfIteration:
    """Test __iter__, iteritems(), iterindex(), __contains__."""

    def test_iter_empty_shelf(self, open_shelf):
        """Iterating over an empty shelf yields nothing."""
        assert list(open_shelf) == []

    def test_iter_populated_shelf(self, populated_shelf):
        """Iterating yields all stored names."""
        shelf, items = populated_shelf
        names = list(shelf)
        assert len(names) == len(items)
        for name in names:
            assert len(name) == 8

    def test_iteritems_empty(self, open_shelf):
        """iteritems on empty shelf yields nothing."""
        assert list(open_shelf.iteritems()) == []

    def test_iteritems_populated(self, populated_shelf):
        """iteritems yields (name, value) pairs for all items."""
        shelf, items = populated_shelf
        result = dict(shelf.iteritems())
        assert len(result) == len(items)
        for name, value in items:
            assert result[name] == value

    def test_items_alias(self, populated_shelf):
        """Shelf.items is an alias for iteritems."""
        shelf, items = populated_shelf
        result = dict(shelf.items())
        expected = dict(shelf.iteritems())
        assert result == expected

    def test_iterindex_empty(self, open_shelf):
        """iterindex on empty shelf yields nothing."""
        assert list(open_shelf.iterindex()) == []

    def test_iterindex_populated(self, populated_shelf):
        """iterindex yields (name, position) pairs."""
        shelf, items = populated_shelf
        index = dict(shelf.iterindex())
        assert len(index) == len(items)
        for name, _ in items:
            assert name in index
            assert isinstance(index[name], int)

    def test_contains_empty(self, open_shelf):
        """__contains__ returns False for all names on empty shelf."""
        assert make_name(0) not in open_shelf
        assert make_name(999) not in open_shelf

    def test_contains_after_store(self, open_shelf):
        """__contains__ returns True for stored names."""
        name = make_name(3)
        open_shelf.store([(name, b"val")])
        assert name in open_shelf
        assert make_name(999) not in open_shelf

    def test_contains_after_update(self, open_shelf):
        """__contains__ still True after updating a name."""
        name = make_name(4)
        open_shelf.store([(name, b"v1")])
        assert name in open_shelf
        open_shelf.store([(name, b"v2")])
        assert name in open_shelf

    def test_iter_after_multiple_stores(self, open_shelf):
        """Iteration includes items from multiple store calls."""
        items1 = make_items(3, b"a", start=0)
        items2 = make_items(3, b"b", start=10)
        open_shelf.store(items1)
        open_shelf.store(items2)
        names = list(open_shelf)
        # 6 unique names
        assert len(names) == 6
        # All names are 8 bytes
        for name in names:
            assert len(name) == 8

    def test_iteritems_after_overwrite(self, open_shelf):
        """iteritems returns latest values after overwrite."""
        name = make_name(10)
        open_shelf.store([(name, b"old")])
        open_shelf.store([(name, b"new")])
        result = dict(open_shelf.iteritems())
        assert result[name] == b"new"


# ── 7. TestShelfNextName ──


class TestShelfNextName:
    """Test next_name() generates unique, unused names."""

    def test_next_name_returns_8_bytes(self, open_shelf):
        """next_name returns an 8-byte string."""
        name = open_shelf.next_name()
        assert isinstance(name, bytes)
        assert len(name) == 8

    def test_next_name_unique(self, open_shelf):
        """Consecutive calls return different names."""
        names = set()
        for _ in range(20):
            name = open_shelf.next_name()
            assert name not in names, f"Duplicate name: {name!r}"
            names.add(name)

    def test_next_name_not_in_existing(self, populated_shelf):
        """next_name returns names not already in the shelf."""
        shelf, items = populated_shelf
        existing_names = {name for name, _ in items}
        for _ in range(10):
            name = shelf.next_name()
            assert name not in existing_names

    def test_next_name_after_store(self, open_shelf):
        """next_name skips names that were just stored."""
        name1 = open_shelf.next_name()
        open_shelf.store([(name1, b"taken")])
        name2 = open_shelf.next_name()
        assert name2 != name1

    def test_next_name_reuses_holes(self, populated_shelf):
        """next_name reuses OID holes from the offset map."""
        shelf, items = populated_shelf
        # Collect some names
        names = [shelf.next_name() for _ in range(5)]
        # All should be unique
        assert len(set(names)) == len(names)
        # None should conflict with existing items
        existing_names = {name for name, _ in items}
        for name in names:
            assert name not in existing_names

    def test_next_name_many(self, open_shelf):
        """next_name can produce many unique names."""
        names = set()
        for _ in range(100):
            names.add(open_shelf.next_name())
        assert len(names) == 100


# ── 8. TestShelfEmpty ──


class TestShelfEmpty:
    """Test empty shelf creation and behavior."""

    def test_create_empty_shelf(self, shelf_file):
        """An empty shelf can be created and opened."""
        file = File(str(shelf_file))
        shelf = Shelf(file=file)
        assert list(shelf) == []
        assert shelf.get_value(make_name(0)) is None
        shelf.close()

    def test_empty_shelf_has_offset_map(self, open_shelf):
        """An empty shelf has a valid offset map."""
        assert open_shelf.offset_map is not None
        assert isinstance(open_shelf.offset_map, OffsetMap)

    def test_empty_shelf_has_memory_index(self, open_shelf):
        """An empty shelf has an empty memory index."""
        assert open_shelf.memory_index == {}

    def test_empty_shelf_store_then_read(self, open_shelf):
        """Items can be stored in and read from an initially empty shelf."""
        items = make_items(5)
        open_shelf.store(items)
        for name, value in items:
            assert open_shelf.get_value(name) == value

    def test_empty_shelf_close_and_reopen(self, shelf_file):
        """An empty shelf can be closed and reopened."""
        file = File(str(shelf_file))
        shelf = Shelf(file=file)
        shelf.close()
        file2 = File(str(shelf_file))
        shelf2 = Shelf(file=file2)
        assert list(shelf2) == []
        shelf2.close()


# ── 9. TestOffsetMap ──


class TestOffsetMap:
    """Test OffsetMap creation, get/set, iteration, gen_stitch, gen_holes."""

    def test_create_offset_map(self, shelf_file):
        """OffsetMap can be created on a file."""
        file = File(str(shelf_file))
        # Write some data first so offset map has a non-zero start
        write(file, b"x" * 100)
        om = OffsetMap(file, max_oid=5, max_offset=50)
        assert isinstance(om, OffsetMap)
        file.close()

    def test_get_unset_returns_default(self, shelf_file):
        """get() returns default for unset OIDs."""
        file = File(str(shelf_file))
        write(file, b"x" * 100)
        om = OffsetMap(file, max_oid=5, max_offset=50)
        assert om.get(0) is None
        assert om.get(3) is None
        assert om.get(99, 42) == 42
        file.close()

    def test_set_and_get(self, shelf_file):
        """Values set via __setitem__ are retrievable via get()."""
        file = File(str(shelf_file))
        write(file, b"x" * 100)
        om = OffsetMap(file, max_oid=5, max_offset=50)
        om[0] = 10
        om[2] = 20
        assert om.get(0) == 10
        assert om.get(2) == 20
        assert om.get(1) is None
        file.close()

    def test_getitem_raises_on_unset(self, shelf_file):
        """__getitem__ raises IndexError for unset OIDs."""
        file = File(str(shelf_file))
        write(file, b"x" * 100)
        om = OffsetMap(file, max_oid=5, max_offset=50)
        with pytest.raises(IndexError):
            _ = om[0]
        file.close()

    def test_getitem_returns_set_value(self, shelf_file):
        """__getitem__ returns the set value."""
        file = File(str(shelf_file))
        write(file, b"x" * 100)
        om = OffsetMap(file, max_oid=5, max_offset=50)
        om[1] = 55
        assert om[1] == 55
        file.close()

    def test_setitem_asserts_no_overwrite(self, shelf_file):
        """__setitem__ asserts that we don't overwrite existing values."""
        file = File(str(shelf_file))
        write(file, b"x" * 100)
        om = OffsetMap(file, max_oid=5, max_offset=50)
        om[0] = 10
        with pytest.raises(AssertionError):
            om[0] = 20  # Should not overwrite
        file.close()

    def test_iter_empty(self, shelf_file):
        """Iteration over empty offset map yields nothing."""
        file = File(str(shelf_file))
        write(file, b"x" * 100)
        om = OffsetMap(file, max_oid=5, max_offset=50)
        assert list(om) == []
        file.close()

    def test_iter_with_values(self, shelf_file):
        """Iteration yields OIDs with values set below start."""
        file = File(str(shelf_file))
        write(file, b"x" * 100)
        om = OffsetMap(file, max_oid=5, max_offset=50)
        om[0] = 10
        om[3] = 30
        oids = list(om)
        assert 0 in oids
        assert 3 in oids
        file.close()

    def test_iteritems(self, shelf_file):
        """iteritems yields (OID, offset) pairs."""
        file = File(str(shelf_file))
        write(file, b"x" * 100)
        om = OffsetMap(file, max_oid=5, max_offset=50)
        om[1] = 11
        om[4] = 44
        items = dict(om.iteritems())
        assert items[1] == 11
        assert items[4] == 44
        file.close()

    def test_items_alias(self, shelf_file):
        """OffsetMap.items is an alias for iteritems."""
        file = File(str(shelf_file))
        write(file, b"x" * 100)
        om = OffsetMap(file, max_oid=5, max_offset=50)
        om[0] = 10
        assert list(om.items()) == list(om.iteritems())
        file.close()

    def test_get_array_size(self, shelf_file):
        """get_array_size returns total capacity."""
        file = File(str(shelf_file))
        write(file, b"x" * 100)
        om = OffsetMap(file, max_oid=10, max_offset=50)
        assert om.get_array_size() == 12  # max_oid + 2
        file.close()

    def test_get_start(self, shelf_file):
        """get_start returns the file position where offset map starts."""
        file = File(str(shelf_file))
        write(file, b"x" * 100)
        start_pos = file.tell()
        om = OffsetMap(file, max_oid=5, max_offset=50)
        assert om.get_start() == start_pos
        file.close()

    def test_gen_stitch(self, shelf_file):
        """gen_stitch builds the linked list of holes and yields indices."""
        file = File(str(shelf_file))
        write(file, b"x" * 100)
        om = OffsetMap(file, max_oid=5, max_offset=50)
        # Set some values to create holes at other positions
        om[0] = 10
        om[2] = 20
        # Consume gen_stitch
        indices = list(om.gen_stitch())
        # Should yield all indices (0..max_oid+1)
        assert len(indices) == 7  # max_oid(5) + 2 = 7 entries

    def test_gen_holes(self, shelf_file):
        """gen_holes yields hole indices (unused slots)."""
        file = File(str(shelf_file))
        write(file, b"x" * 100)
        om = OffsetMap(file, max_oid=5, max_offset=50)
        om[0] = 10
        om[3] = 30
        # Consume gen_stitch first to build the linked list
        for _ in om.gen_stitch():
            pass
        holes = list(om.gen_holes())
        # Holes should not include indices 0 or 3 (which are set)
        assert 0 not in holes
        assert 3 not in holes
        # Holes should include other indices
        assert len(holes) == 5  # 7 total - 2 set = 5 holes

    def test_generate_static(self, shelf_file):
        """OffsetMap.generate() static method creates data on file."""
        file = File(str(shelf_file))
        write(file, b"x" * 100)
        start = file.tell()
        for _ in OffsetMap.generate(file, max_oid=3, max_offset=50):
            pass
        file.seek(start)
        # Should be able to create an OffsetMap at that position
        om = OffsetMap(file)
        assert om.get_array_size() == 5  # max_oid(3) + 2

    def test_get_filters_by_start(self, shelf_file):
        """get() returns default for values >= start (linked list entries)."""
        file = File(str(shelf_file))
        write(file, b"x" * 100)
        om = OffsetMap(file, max_oid=5, max_offset=50)
        # After gen_stitch, holes have values >= start
        om[0] = 10
        for _ in om.gen_stitch():
            pass
        # Value at 0 was set to 10, which is < start, so it's valid
        assert om.get(0) == 10
        # Unset index should return None
        assert om.get(1) is None


# ── 10. TestReadTransactionOffsets ──


class TestReadTransactionOffsets:
    """Test read_transaction_offsets() for valid and invalid transactions."""

    def _write_transaction(self, file, items):
        """Helper: write a complete transaction with given items."""
        start = file.tell()
        write_int8(file, 0)  # placeholder for length
        for name, value in items:
            write_int8(file, len(name) + len(value))
            write(file, name)
            write(file, value)
        end = file.tell()
        file.seek(start)
        write_int8(file, end - start - 8)
        file.seek(end)

    def test_read_valid_transaction(self, shelf_file):
        """Reading a valid transaction returns correct offset mapping."""
        file = File(str(shelf_file))
        items = make_items(3)
        # Record where the transaction starts
        transaction_start = file.tell()
        self._write_transaction(file, items)
        # Seek back to transaction start and read it
        file.seek(transaction_start)
        offsets = read_transaction_offsets(file)
        assert offsets is not None
        assert len(offsets) == 3
        for name, _ in items:
            assert name in offsets
        file.close()

    def test_read_valid_transaction_offsets_are_positions(self, shelf_file):
        """Transaction offset values are file positions."""
        file = File(str(shelf_file))
        name1 = make_name(1)
        name2 = make_name(2)
        items = [(name1, b"a"), (name2, b"bb")]
        self._write_transaction(file, items)
        file.seek(0)
        # Skip to transaction start (after the 8-byte length prefix)
        file.seek_end()
        txn_size = 8 + sum(8 + len(n) + len(v) for n, v in items)
        file.seek(file.tell() - txn_size)
        offsets = read_transaction_offsets(file)
        assert offsets is not None
        # Offsets should be file positions (integers)
        for name, pos in offsets.items():
            assert isinstance(pos, int)
            assert pos > 0
        file.close()

    def test_read_at_end_returns_none(self, shelf_file):
        """Reading at end of file returns None."""
        file = File(str(shelf_file))
        file.seek_end()
        result = read_transaction_offsets(file)
        assert result is None
        file.close()

    def test_read_empty_file_returns_none(self, shelf_file):
        """Reading from an empty file returns None."""
        file = File(str(shelf_file))
        result = read_transaction_offsets(file)
        assert result is None
        file.close()

    def test_read_empty_transaction(self, shelf_file):
        """An empty transaction (length=0) returns empty dict."""
        file = File(str(shelf_file))
        write_int8(file, 0)  # zero-length transaction
        file.seek(file.tell() - 8)
        offsets = read_transaction_offsets(file)
        assert offsets == {}
        file.close()

    def test_read_truncated_transaction_raises(self, shelf_file):
        """A truncated transaction raises ShortRead."""
        file = File(str(shelf_file))
        # Write a transaction header claiming 100 bytes but provide fewer
        write_int8(file, 100)  # claims 100 bytes follow
        write(file, b"x" * 20)  # only 20 bytes actually follow
        file.seek(file.tell() - 28)
        with pytest.raises(ShortRead):
            read_transaction_offsets(file)
        file.close()

    def test_repair_mode_truncates(self, shelf_file):
        """In repair mode, a truncated transaction causes truncation."""
        file = File(str(shelf_file))
        # Write a valid prefix first
        write(file, Shelf.prefix)
        # Write a valid empty transaction
        write_int8(file, 0)
        # Write a truncated transaction
        trunc_start = file.tell()
        write_int8(file, 100)
        write(file, b"x" * 20)
        file.seek_end()
        original_size = file.tell()
        # Seek to the truncated transaction
        file.seek(trunc_start)
        result = read_transaction_offsets(file, repair=True)
        # Should have returned None (truncated)
        assert result is None
        # File should be truncated
        file.seek_end()
        assert file.tell() <= original_size
        assert file.tell() == trunc_start
        file.close()

    def test_repair_preserves_valid_transactions(self, shelf_file):
        """Repair mode preserves valid transactions before the bad one."""
        file = File(str(shelf_file))
        write(file, Shelf.prefix)
        # Write a valid transaction
        items = make_items(2)
        self._write_transaction(file, items)
        valid_end = file.tell()
        # Write a truncated transaction
        write_int8(file, 100)
        write(file, b"x" * 10)
        # Read valid transaction first
        file.seek(len(Shelf.prefix))
        offsets = read_transaction_offsets(file)
        assert offsets is not None
        assert len(offsets) == 2
        # Now repair the truncated one
        file.seek(valid_end)
        result = read_transaction_offsets(file, repair=True)
        assert result is None
        # File should be truncated to valid_end
        file.seek_end()
        assert file.tell() == valid_end
        file.close()

    def test_read_multiple_transactions_sequentially(self, shelf_file):
        """Multiple transactions can be read sequentially."""
        file = File(str(shelf_file))
        items1 = make_items(2, b"t1")
        items2 = make_items(3, b"t2")
        self._write_transaction(file, items1)
        self._write_transaction(file, items2)
        # Read first transaction
        file.seek_end()
        total = file.tell()
        txn1_size = 8 + sum(8 + len(n) + len(v) for n, v in items1)
        txn2_size = 8 + sum(8 + len(n) + len(v) for n, v in items2)
        file.seek(total - txn1_size - txn2_size)
        offsets1 = read_transaction_offsets(file)
        assert len(offsets1) == 2
        offsets2 = read_transaction_offsets(file)
        assert len(offsets2) == 3
        file.close()

    def test_read_transaction_with_single_item(self, shelf_file):
        """A transaction with a single item works correctly."""
        file = File(str(shelf_file))
        name = make_name(42)
        transaction_start = file.tell()
        self._write_transaction(file, [(name, b"answer")])
        file.seek(transaction_start)
        offsets = read_transaction_offsets(file)
        assert name in offsets
        file.close()


# ── 11. TestShelfRepair ──


class TestShelfRepair:
    """Test repair mode for truncated shelf files."""

    def test_repair_truncated_after_init_items(self, shelf_file):
        """A shelf with truncated data after initial items can be repaired."""
        items = make_items(3)
        file = File(str(shelf_file))
        for _ in Shelf.generate_shelf(file=file, items=items):
            pass
        # Corrupt the end by writing partial data
        write_int8(file, 100)  # Claim 100 bytes
        write(file, b"x" * 10)  # Only write 10 bytes
        file.close()
        # Open with repair=True
        file2 = File(str(shelf_file))
        shelf = Shelf(file=file2, repair=True)
        # Original items should still be accessible
        for name, value in items:
            assert shelf.get_value(name) == value
        shelf.close()

    def test_repair_truncated_after_store(self, shelf_file):
        """A shelf with truncated data after a store can be repaired."""
        items = make_items(3)
        file = File(str(shelf_file))
        shelf = Shelf(file=file, items=items)
        extra_items = make_items(2, b"extra", start=10)
        shelf.store(extra_items)
        # Now manually corrupt the end
        write_int8(shelf.file, 999)  # Bogus transaction
        write(shelf.file, b"\xff" * 5)
        shelf.close()
        # Reopen with repair
        file2 = File(str(shelf_file))
        shelf2 = Shelf(file=file2, repair=True)
        # Original items and stored items should be intact
        for name, value in items:
            assert shelf2.get_value(name) == value
        for name, value in extra_items:
            assert shelf2.get_value(name) == value
        shelf2.close()

    def test_no_repair_needed(self, shelf_file):
        """A valid shelf opened with repair=True works normally."""
        items = make_items(5)
        file = File(str(shelf_file))
        shelf = Shelf(file=file, items=items)
        shelf.close()
        file2 = File(str(shelf_file))
        shelf2 = Shelf(file=file2, repair=True)
        for name, value in items:
            assert shelf2.get_value(name) == value
        shelf2.close()


# ── 12. TestShelfClose ──


class TestShelfClose:
    """Test Shelf.close() behavior."""

    def test_close(self, open_shelf):
        """close() closes the underlying file."""
        open_shelf.close()
        # Accessing the file after close should raise
        with pytest.raises(ValueError):
            open_shelf.file.tell()

    def test_get_file(self, open_shelf):
        """get_file() returns the underlying File object."""
        assert open_shelf.get_file() is open_shelf.file

    def test_get_offset_map(self, open_shelf):
        """get_offset_map() returns the OffsetMap."""
        assert open_shelf.get_offset_map() is open_shelf.offset_map


# ── 13. TestShelfEdgeCases ──


class TestShelfEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_store_then_delete_via_overwrite_none(self, open_shelf):
        """Overwriting with a different value works correctly."""
        name = make_name(1)
        open_shelf.store([(name, b"first")])
        assert open_shelf.get_value(name) == b"first"
        open_shelf.store([(name, b"second")])
        assert open_shelf.get_value(name) == b"second"
        # First value should be gone
        assert open_shelf.get_value(name) == b"second"

    def test_many_items_single_store(self, open_shelf):
        """A single store call with many items works."""
        items = make_items(50)
        result = open_shelf.store(items)
        assert len(result) == 50
        for name, value in items:
            assert open_shelf.get_value(name) == value

    def test_same_name_in_single_store(self, open_shelf):
        """Storing the same name twice in one batch: last one wins."""
        name = make_name(1)
        result = open_shelf.store([
            (name, b"first"),
            (name, b"second"),
        ])
        assert len(result) == 2
        # Both entries should have the name
        assert result[0][0] == name
        assert result[1][0] == name
        # The value should be the last one stored
        assert open_shelf.get_value(name) == b"second"

    def test_reopen_preserves_all_state(self, shelf_file):
        """Reopening preserves all items from multiple store calls."""
        file = File(str(shelf_file))
        shelf = Shelf(file=file)
        batch1 = make_items(3, b"b1", start=0)
        batch2 = make_items(3, b"b2", start=10)
        batch3 = make_items(3, b"b3", start=20)
        shelf.store(batch1)
        shelf.store(batch2)
        shelf.store(batch3)
        shelf.close()

        file2 = File(str(shelf_file))
        shelf2 = Shelf(file=file2)
        for name, value in batch1 + batch2 + batch3:
            assert shelf2.get_value(name) == value
        shelf2.close()

    def test_value_with_null_bytes(self, open_shelf):
        """Values containing null bytes are handled correctly."""
        name = make_name(1)
        value = b"hello\x00world\x00\x00"
        open_shelf.store([(name, value)])
        assert open_shelf.get_value(name) == value

    def test_name_with_all_zero_bytes(self, open_shelf):
        """A name of all zero bytes works."""
        name = b"\x00" * 8
        value = b"zero-name"
        open_shelf.store([(name, value)])
        assert open_shelf.get_value(name) == value

    def test_name_with_max_bytes(self, open_shelf):
        """A name of all 0xff bytes works."""
        name = b"\xff" * 8
        value = b"max-name"
        open_shelf.store([(name, value)])
        assert open_shelf.get_value(name) == value
