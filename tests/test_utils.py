"""Tests for dhara.utils — ByteArray, Byte, BitArray, WordArray, IntArray, IntSet."""

from __future__ import annotations

import io

import pytest

from dhara.utils import (
    BitArray,
    Byte,
    ByteArray,
    IntArray,
    IntSet,
    WordArray,
    int4_to_str,
    int8_to_str,
    read,
    read_int4,
    read_int8,
    str_to_int4,
    str_to_int8,
    write,
    write_int4,
    write_int8,
)


# ── Int8 / Int4 conversions ──


class TestInt8Conversions:
    """Test str_to_int8 and int8_to_str."""

    def test_str_to_int8_bytes(self):
        result = str_to_int8(b"\x00\x00\x00\x00\x00\x00\x00\x2a")
        assert result == 42

    def test_int8_to_str_bytes(self):
        result = int8_to_str(42)
        assert isinstance(result, bytes)
        assert len(result) == 8

    def test_int8_roundtrip(self):
        original = 123456789
        encoded = int8_to_str(original)
        decoded = str_to_int8(encoded)
        assert decoded == original


class TestInt4Conversions:
    """Test str_to_int4 and int4_to_str."""

    def test_str_to_int4(self):
        result = str_to_int4(b"\x00\x00\x00\x2a")
        assert result == 42

    def test_int4_to_str(self):
        result = int4_to_str(42)
        assert isinstance(result, bytes)
        assert len(result) == 4

    def test_int4_roundtrip(self):
        original = 100000
        encoded = int4_to_str(original)
        decoded = str_to_int4(encoded)
        assert decoded == original


# ── File I/O helpers ──


class TestFileReadWrite:
    """Test read/write helpers."""

    def test_write_and_read(self):
        buf = io.BytesIO()
        write(buf, b"hello")
        buf.seek(0)
        assert read(buf, 5) == b"hello"

    def test_read_int8_write_int8(self):
        buf = io.BytesIO()
        write_int8(buf, 42)
        buf.seek(0)
        assert read_int8(buf) == 42

    def test_read_int4_write_int4(self):
        buf = io.BytesIO()
        write_int4(buf, 42)
        buf.seek(0)
        assert read_int4(buf) == 42


# ── ByteArray ──


class TestByteArray:
    """Test ByteArray storage class."""

    def test_create_with_size(self):
        ba = ByteArray(size=4)
        assert ba.get_size() == 4

    def test_len(self):
        ba = ByteArray(size=10)
        assert len(ba) == 10

    def test_setitem_getitem(self):
        ba = ByteArray(size=4)
        ba[0] = b"A"
        assert ba[0] == b"A"

    def test_iteration(self):
        ba = ByteArray(size=3)
        ba[0] = b"X"
        ba[2] = b"Z"
        items = list(ba)
        assert items[0] == b"X"
        assert items[2] == b"Z"

    def test_set_size(self):
        ba = ByteArray(size=4)
        ba.set_size(8)
        assert ba.get_size() == 8


# ── Byte ──


class TestByte:
    """Test Byte wrapper class."""

    def test_from_bytes(self):
        b = Byte(b"A")
        assert int(b) == 65
        assert str(b) == "A"

    def test_from_int(self):
        b = Byte(65)
        assert int(b) == 65
        assert str(b) == "A"

    def test_byte_method(self):
        b = Byte(b"Z")
        assert b.byte() == b"Z"

    def test_getitem(self):
        b = Byte(b"A")
        # Byte stores as a single byte; getitem returns 0-indexed bit
        result = b[0]
        assert isinstance(result, int)


# ── BitArray ──


class TestBitArray:
    """Test BitArray storage class."""

    def test_create_with_size(self):
        bits = BitArray(size=16)
        assert bits.get_size() == 16

    def test_len(self):
        bits = BitArray(size=8)
        assert len(bits) == 8

    def test_set_and_get(self):
        bits = BitArray(size=8)
        bits[0] = 1
        assert bits[0] == 1

    def test_set_size(self):
        bits = BitArray(size=8)
        bits.set_size(16)
        assert bits.get_size() == 16

    def test_iteration(self):
        bits = BitArray(size=4)
        bits[0] = 1
        bits[3] = 1
        items = list(bits)
        assert items[0] == 1
        assert items[3] == 1


# ── WordArray ──


class TestWordArray:
    """Test WordArray storage class."""

    def test_create_with_params(self):
        wa = WordArray(file=None, bytes_per_word=4, number_of_words=10)
        assert len(wa) == 10

    def test_len(self):
        wa = WordArray(file=None, bytes_per_word=4, number_of_words=10)
        assert len(wa) == 10

    def test_get_bytes_per_word(self):
        wa = WordArray(file=None, bytes_per_word=8, number_of_words=5)
        assert wa.get_bytes_per_word() == 8

    def test_setitem_getitem(self):
        wa = WordArray(file=None, bytes_per_word=4, number_of_words=3)
        # WordArray stores bytes, not ints
        wa[0] = b"\x00\x00\x00\x2a"
        assert wa[0] == b"\x00\x00\x00\x2a"

    def test_iteration(self):
        wa = WordArray(file=None, bytes_per_word=4, number_of_words=3)
        wa[0] = b"\x00\x00\x00\x0a"
        wa[1] = b"\x00\x00\x00\x14"
        items = list(wa)
        assert len(items) == 3


# ── IntArray ──


class TestIntArray:
    """Test IntArray storage class."""

    def test_create(self):
        ia = IntArray(file=None, number_of_ints=5)
        assert len(ia) == 5

    def test_set_and_get(self):
        ia = IntArray(file=None, number_of_ints=3)
        ia[0] = 100
        assert ia[0] == 100

    def test_iteration(self):
        ia = IntArray(file=None, number_of_ints=3)
        ia[0] = 1
        ia[2] = 3
        items = list(ia)
        assert items[0] == 1
        assert items[2] == 3

    def test_iteritems(self):
        ia = IntArray(file=None, number_of_ints=3)
        ia[0] = 10
        ia[1] = 20
        items = list(ia.iteritems())
        # iteritems only returns non-default (set) items
        assert len(items) == 2
        assert items[0] == (0, 10)
        assert items[1] == (1, 20)

    def test_get_method(self):
        ia = IntArray(file=None, number_of_ints=3)
        ia[1] = 42
        assert ia.get(1) == 42


# ── IntSet ──


class TestIntSet:
    """Test IntSet storage class."""

    def test_create_default(self):
        s = IntSet()
        assert 0 not in s

    def test_add_and_contains(self):
        s = IntSet()
        s.add(5)
        assert 5 in s
        assert 10 not in s

    def test_discard(self):
        s = IntSet()
        s.add(5)
        s.discard(5)
        assert 5 not in s

    def test_discard_nonexistent(self):
        s = IntSet()
        # Discarding nonexistent should not raise
        s.discard(999)

    def test_multiple_adds(self):
        s = IntSet()
        s.add(1)
        s.add(2)
        s.add(3)
        assert 1 in s
        assert 2 in s
        assert 3 in s
