"""Extended tests for dhara.utils — covering missing branches and edge cases.

Targets the ~68 uncovered lines in dhara/utils.py, focusing on:
- Socket-style read/write paths (recv/send)
- ShortRead exception paths
- ByteArray slice operations, boundary errors, gen_set_size
- Byte bit manipulation edge cases (negative indices, out-of-range)
- BitArray negative indexing and boundary errors
- WordArray negative indexing and boundary errors
- IntArray blank values, get() default, maximum_int, iteritems items alias
- IntSet auto-expansion, discard within bounds
- as_bytes, empty_byte_string, all_bytes constants
- write_all, read_int8_str, write_int8_str, read_int4_str, write_int4_str
"""

from __future__ import annotations

import io
import struct

import pytest

from dhara.utils import (
    BitArray,
    Byte,
    ByteArray,
    IntArray,
    IntSet,
    ShortRead,
    WordArray,
    all_bytes,
    as_bytes,
    empty_byte_string,
    int4_to_str,
    int8_to_str,
    read,
    read_int4,
    read_int4_str,
    read_int8,
    read_int8_str,
    str_to_int4,
    str_to_int8,
    write,
    write_all,
    write_int4,
    write_int4_str,
    write_int8,
    write_int8_str,
)


# ── Constants ──


class TestConstants:
    """Verify module-level constants."""

    def test_empty_byte_string(self):
        assert empty_byte_string == b""
        assert isinstance(empty_byte_string, (bytes, bytearray))

    def test_all_bytes_length(self):
        assert len(all_bytes) == 256

    def test_all_bytes_content(self):
        for i, b in enumerate(all_bytes):
            assert len(b) == 1
            assert b == struct.pack("B", i)


# ── as_bytes ──


class TestAsBytes:
    """Test as_bytes conversion function."""

    def test_bytes_passthrough(self):
        assert as_bytes(b"hello") == b"hello"

    def test_bytearray_passthrough(self):
        assert as_bytes(bytearray(b"hello")) == bytearray(b"hello")

    def test_string_encoded_latin1(self):
        # latin1 encoding maps 0x00-0xFF directly
        assert as_bytes("\xff") == b"\xff"
        assert as_bytes("\x80") == b"\x80"
        assert as_bytes("abc") == b"abc"

    def test_empty_string(self):
        assert as_bytes("") == b""


# ── Int8 / Int4 edge cases ──


class TestInt8ConversionsExtended:
    """Extended int8 conversion tests."""

    def test_max_uint64(self):
        max_val = (1 << 64) - 1
        assert str_to_int8(int8_to_str(max_val)) == max_val

    def test_zero(self):
        assert str_to_int8(int8_to_str(0)) == 0

    def test_big_endian(self):
        # Verify big-endian byte order
        encoded = int8_to_str(1)
        assert encoded == b"\x00\x00\x00\x00\x00\x00\x00\x01"


class TestInt4ConversionsExtended:
    """Extended int4 conversion tests."""

    def test_max_uint32(self):
        max_val = (1 << 32) - 1
        assert str_to_int4(int4_to_str(max_val)) == max_val

    def test_zero(self):
        assert str_to_int4(int4_to_str(0)) == 0

    def test_big_endian(self):
        encoded = int4_to_str(1)
        assert encoded == b"\x00\x00\x00\x01"


# ── ShortRead ──


class TestShortRead:
    """Test ShortRead exception."""

    def test_is_ioerror(self):
        assert issubclass(ShortRead, IOError)

    def test_can_raise_and_catch(self):
        with pytest.raises(ShortRead):
            raise ShortRead()

    def test_catch_as_ioerror(self):
        with pytest.raises(IOError):
            raise ShortRead()


# ── read — socket path ──


class _FakeSocket:
    """Minimal socket-like object with only recv (no read/write)."""

    def __init__(self, recv_chunks):
        self._chunks = list(recv_chunks)
        self._idx = 0

    def recv(self, n):
        if self._idx >= len(self._chunks):
            return b""
        chunk = self._chunks[self._idx]
        self._idx += 1
        return chunk


class _FakeSendSocket:
    """Minimal socket-like object with only send (no read/write)."""

    def __init__(self, send_results):
        self._results = list(send_results)
        self._idx = 0
        self.sent = []

    def send(self, data):
        if self._idx >= len(self._results):
            return 0
        n = self._results[self._idx]
        self._idx += 1
        self.sent.append(data[:n])
        return n


class TestReadSocketPath:
    """Test read() using socket-like objects (recv instead of read)."""

    def test_socket_read_exact(self):
        """Socket that delivers exactly the requested bytes."""
        sock = _FakeSocket([b"hello"])
        result = read(sock, 5)
        assert result == b"hello"

    def test_socket_read_chunked(self):
        """Socket that delivers bytes in chunks."""
        sock = _FakeSocket([b"hel", b"lo"])
        result = read(sock, 5)
        assert result == b"hello"

    def test_socket_read_short_raises(self):
        """Socket that returns empty bytes triggers ShortRead."""
        sock = _FakeSocket([b""])
        with pytest.raises(ShortRead):
            read(sock, 5)

    def test_socket_read_partial_then_empty(self):
        """Socket delivers some bytes then closes mid-read."""
        sock = _FakeSocket([b"he", b""])
        with pytest.raises(ShortRead):
            read(sock, 5)

    def test_file_read_short_raises(self):
        """File-like object that returns fewer bytes than requested."""
        buf = io.BytesIO(b"hi")
        with pytest.raises(ShortRead):
            read(buf, 5)


# ── write — socket path ──


class TestWriteSocketPath:
    """Test write() using socket-like objects (send instead of write)."""

    def test_socket_write_all(self):
        """Socket that sends all bytes in one call."""
        sock = _FakeSendSocket([5])
        write(sock, b"hello")
        assert len(sock.sent) == 1
        assert sock.sent[0] == b"hello"

    def test_socket_write_partial(self):
        """Socket that sends bytes in partial writes."""
        sock = _FakeSendSocket([3, 2])
        write(sock, b"hello")
        assert len(sock.sent) == 2

    def test_socket_write_zero_repeated_raises(self):
        """Socket that repeatedly returns 0 raises OSError after 10 failures."""
        sock = _FakeSendSocket([0] * 15)
        with pytest.raises(OSError, match="send\\(\\) failed"):
            write(sock, b"hello")
        assert sock._idx == 11

    def test_write_string_converts_to_bytes(self):
        """write() converts string arguments via as_bytes."""
        buf = io.BytesIO()
        write(buf, "hello")
        buf.seek(0)
        assert buf.read() == b"hello"


# ── write_all ──


class TestWriteAll:
    """Test write_all function."""

    def test_write_all_single_arg(self):
        buf = io.BytesIO()
        write_all(buf, b"hello")
        buf.seek(0)
        assert buf.read() == b"hello"

    def test_write_all_multiple_args(self):
        buf = io.BytesIO()
        write_all(buf, b"hello", b" ", b"world")
        buf.seek(0)
        assert buf.read() == b"hello world"

    def test_write_all_mixed_types(self):
        """write_all accepts strings and bytes, converting strings via as_bytes."""
        buf = io.BytesIO()
        write_all(buf, "hello", b" ", "world")
        buf.seek(0)
        assert buf.read() == b"hello world"


# ── read_int8_str / write_int8_str ──


class TestInt8StrIO:
    """Test length-prefixed (8-byte) string I/O."""

    def test_write_and_read_int8_str(self):
        buf = io.BytesIO()
        payload = b"hello world"
        write_int8_str(buf, payload)
        buf.seek(0)
        assert read_int8_str(buf) == payload

    def test_empty_string_int8(self):
        buf = io.BytesIO()
        write_int8_str(buf, b"")
        buf.seek(0)
        assert read_int8_str(buf) == b""

    def test_long_string_int8(self):
        buf = io.BytesIO()
        payload = b"x" * 1000
        write_int8_str(buf, payload)
        buf.seek(0)
        assert read_int8_str(buf) == payload


# ── read_int4_str / write_int4_str ──


class TestInt4StrIO:
    """Test length-prefixed (4-byte) string I/O."""

    def test_write_and_read_int4_str(self):
        buf = io.BytesIO()
        payload = b"test data"
        write_int4_str(buf, payload)
        buf.seek(0)
        assert read_int4_str(buf) == payload

    def test_empty_string_int4(self):
        buf = io.BytesIO()
        write_int4_str(buf, b"")
        buf.seek(0)
        assert read_int4_str(buf) == b""


# ── ByteArray extended ──


class TestByteArrayExtended:
    """Extended ByteArray tests covering slices, errors, and gen_set_size."""

    def test_create_default_no_file(self):
        """ByteArray with no arguments creates a default BytesIO-backed array."""
        ba = ByteArray()
        assert ba.get_size() == 0
        assert len(ba) == 0

    def test_create_with_explicit_file(self):
        """ByteArray can be backed by a provided file-like object."""
        buf = io.BytesIO()
        ba = ByteArray(size=10, file=buf)
        assert ba.get_size() == 10

    def test_getitem_slice(self):
        """ByteArray supports slice getitem."""
        ba = ByteArray(size=5)
        ba[0] = b"A"
        ba[1] = b"B"
        ba[2] = b"C"
        ba[3] = b"D"
        ba[4] = b"E"
        assert ba[1:4] == b"BCD"

    def test_getitem_slice_full(self):
        ba = ByteArray(size=3)
        ba[0] = b"X"
        ba[1] = b"Y"
        ba[2] = b"Z"
        assert ba[0:3] == b"XYZ"

    def test_setitem_slice(self):
        """ByteArray supports slice setitem."""
        ba = ByteArray(size=5)
        ba[1:3] = b"AB"
        assert ba[1] == b"A"
        assert ba[2] == b"B"

    def test_setitem_slice_wrong_length_raises(self):
        """Slice assignment with wrong length raises ValueError."""
        ba = ByteArray(size=5)
        with pytest.raises(ValueError):
            ba[1:3] = b"ABC"

    def test_getitem_slice_out_of_bounds(self):
        """Slice with out-of-bounds indices raises IndexError."""
        ba = ByteArray(size=3)
        with pytest.raises(IndexError):
            ba[2:5]

    def test_setitem_slice_out_of_bounds(self):
        ba = ByteArray(size=3)
        with pytest.raises(IndexError):
            ba[2:5] = b"abc"

    def test_getitem_negative_index(self):
        """Negative indices are not explicitly supported — should raise."""
        ba = ByteArray(size=5)
        with pytest.raises(IndexError):
            ba[-1]

    def test_getitem_out_of_range(self):
        ba = ByteArray(size=3)
        with pytest.raises(IndexError):
            ba[10]

    def test_setitem_out_of_range(self):
        ba = ByteArray(size=3)
        with pytest.raises(IndexError):
            ba[10] = b"A"

    def test_setitem_wrong_length_raises(self):
        """Setting a single index with a multi-byte value raises ValueError."""
        ba = ByteArray(size=5)
        with pytest.raises(ValueError):
            ba[0] = b"AB"

    def test_getitem_slice_with_step_raises(self):
        """Slice with a step other than None or 1 raises IndexError."""
        ba = ByteArray(size=10)
        with pytest.raises(IndexError):
            ba[0:10:2]

    def test_setitem_slice_with_step_raises(self):
        ba = ByteArray(size=10)
        with pytest.raises(IndexError):
            ba[0:10:2] = b"abc"

    def test_gen_set_size_expand(self):
        """gen_set_size yields remaining bytes during expansion."""
        ba = ByteArray(size=0)
        steps = list(ba.gen_set_size(100))
        # Should have yielded at least once during expansion
        assert len(steps) >= 1
        assert ba.get_size() == 100

    def test_gen_set_size_large_expand(self):
        """gen_set_size with size > 8196 exercises the full-chunk path."""
        ba = ByteArray(size=0)
        list(ba.gen_set_size(10000))
        assert ba.get_size() == 10000

    def test_gen_set_size_same_size(self):
        """gen_set_size with same size does not yield."""
        ba = ByteArray(size=10)
        steps = list(ba.gen_set_size(10))
        assert steps == []

    def test_gen_set_size_larger(self):
        """gen_set_size with larger size yields during expansion."""
        ba = ByteArray(size=10)
        steps = list(ba.gen_set_size(20))
        assert len(steps) >= 1

    def test_gen_set_size_custom_init_byte(self):
        """gen_set_size can initialize with a custom byte."""
        ba = ByteArray(size=0)
        list(ba.gen_set_size(10, init_byte=as_bytes("\xff")))
        # Verify the bytes are initialized to 0xff
        for i in range(10):
            assert ba[i] == b"\xff"

    def test_iteration_yields_individual_bytes(self):
        """Iteration yields single-byte values."""
        ba = ByteArray(size=4)
        ba[0] = b"\x01"
        ba[1] = b"\x02"
        ba[2] = b"\x03"
        ba[3] = b"\x04"
        items = list(ba)
        assert items == [b"\x01", b"\x02", b"\x03", b"\x04"]

    def test_set_size_expand(self):
        """set_size expands the array, preserving existing data."""
        ba = ByteArray(size=3)
        ba[0] = b"A"
        ba[1] = b"B"
        ba[2] = b"C"
        ba.set_size(6)
        assert ba.get_size() == 6
        assert ba[0] == b"A"
        assert ba[1] == b"B"
        assert ba[2] == b"C"


# ── Byte extended ──


class TestByteExtended:
    """Extended Byte tests covering bit manipulation edge cases."""

    def test_negative_index_bit_get(self):
        """Byte supports negative indices for bit access."""
        b = Byte(0b10101010)
        # b[-1] == b[7] == 0 (LSB)
        assert b[-1] == 0
        # b[-8] == b[0] == 1 (MSB)
        assert b[-8] == 1

    def test_negative_index_bit_set(self):
        """Byte supports negative indices for bit setting."""
        b = Byte(0)
        b[-1] = 1  # Set LSB
        assert b[-1] == 1
        assert int(b) == 1

    def test_all_bits_zero(self):
        b = Byte(0)
        for i in range(8):
            assert b[i] == 0

    def test_all_bits_one(self):
        b = Byte(255)
        for i in range(8):
            assert b[i] == 1

    def test_set_then_clear_bit(self):
        b = Byte(0)
        b[3] = 1
        assert b[3] == 1
        b[3] = 0
        assert b[3] == 0

    def test_out_of_range_getitem_raises(self):
        b = Byte(0)
        with pytest.raises(IndexError):
            b[8]
        with pytest.raises(IndexError):
            b[100]
        with pytest.raises(IndexError):
            b[-9]

    def test_out_of_range_setitem_raises(self):
        b = Byte(0)
        with pytest.raises(IndexError):
            b[8] = 1
        with pytest.raises(IndexError):
            b[-9] = 1

    def test_from_invalid_type_raises(self):
        """Byte constructor rejects invalid types."""
        with pytest.raises(TypeError):
            Byte(256)
        with pytest.raises(TypeError):
            Byte(-1)
        with pytest.raises(TypeError):
            Byte("abc")
        with pytest.raises(TypeError):
            Byte(b"ab")  # wrong length

    def test_byte_method_roundtrip(self):
        """byte() returns the canonical single-byte representation."""
        for i in range(256):
            b = Byte(i)
            assert b.byte() == struct.pack("B", i)

    def test_int_conversion(self):
        b = Byte(42)
        assert int(b) == 42

    def test_str_conversion(self):
        b = Byte(65)
        assert str(b) == "A"

    def test_bit_pattern(self):
        """Verify bit ordering: bit 0 is MSB, bit 7 is LSB."""
        # 0b10000000 = 128
        b = Byte(128)
        assert b[0] == 1
        assert b[1] == 0
        assert b[7] == 0

        # 0b00000001 = 1
        b = Byte(1)
        assert b[0] == 0
        assert b[7] == 1


# ── BitArray extended ──


class TestBitArrayExtended:
    """Extended BitArray tests covering negative indexing and boundaries."""

    def test_negative_index(self):
        bits = BitArray(size=8)
        bits[0] = 1
        bits[-1] = 1  # Last bit
        assert bits[0] == 1
        assert bits[-1] == 1
        assert bits[7] == 1  # -1 maps to index 7

    def test_negative_index_out_of_range(self):
        bits = BitArray(size=4)
        with pytest.raises(IndexError):
            bits[-5]

    def test_positive_index_out_of_range(self):
        bits = BitArray(size=4)
        with pytest.raises(IndexError):
            bits[10]

    def test_set_negative_index_out_of_range(self):
        bits = BitArray(size=4)
        with pytest.raises(IndexError):
            bits[-5] = 1

    def test_set_positive_index_out_of_range(self):
        bits = BitArray(size=4)
        with pytest.raises(IndexError):
            bits[10] = 1

    def test_size_multiple_of_8(self):
        bits = BitArray(size=16)
        assert bits.get_size() == 16

    def test_size_not_multiple_of_8(self):
        bits = BitArray(size=13)
        assert bits.get_size() == 13

    def test_iteration_count(self):
        """Iteration yields exactly size bits."""
        bits = BitArray(size=10)
        items = list(bits)
        assert len(items) == 10

    def test_iteration_values(self):
        bits = BitArray(size=8)
        bits[0] = 1
        bits[3] = 1
        bits[7] = 1
        items = list(bits)
        assert items[0] == 1
        assert items[1] == 0
        assert items[3] == 1
        assert items[7] == 1

    def test_str_representation(self):
        bits = BitArray(size=4)
        bits[0] = 1
        bits[1] = 0
        bits[2] = 1
        bits[3] = 1
        s = str(bits)
        assert s == "1011"

    def test_set_size_expand(self):
        bits = BitArray(size=4)
        bits[0] = 1
        bits.set_size(20)
        assert bits.get_size() == 20
        # Original bit preserved
        assert bits[0] == 1

    def test_set_size_grow(self):
        """BitArray can only grow, not shrink (underlying ByteArray constraint)."""
        bits = BitArray(size=8)
        bits.set_size(16)
        assert bits.get_size() == 16

    def test_with_explicit_file(self):
        buf = io.BytesIO()
        bits = BitArray(size=16, file=buf)
        assert bits.get_size() == 16


# ── WordArray extended ──


class TestWordArrayExtended:
    """Extended WordArray tests covering negative indexing and boundaries."""

    def test_negative_index(self):
        wa = WordArray(file=None, bytes_per_word=4, number_of_words=5)
        wa[0] = b"\x00\x00\x00\x01"
        wa[-1] = b"\x00\x00\x00\x05"  # Last word
        assert wa[-1] == b"\x00\x00\x00\x05"
        assert wa[4] == b"\x00\x00\x00\x05"

    def test_negative_index_out_of_range(self):
        wa = WordArray(file=None, bytes_per_word=4, number_of_words=3)
        with pytest.raises(IndexError):
            wa[-4]

    def test_positive_index_out_of_range(self):
        wa = WordArray(file=None, bytes_per_word=4, number_of_words=3)
        with pytest.raises(IndexError):
            wa[10]

    def test_set_negative_index_out_of_range(self):
        wa = WordArray(file=None, bytes_per_word=4, number_of_words=3)
        with pytest.raises(IndexError):
            wa[-4] = b"\x00\x00\x00\x01"

    def test_set_positive_index_out_of_range(self):
        wa = WordArray(file=None, bytes_per_word=4, number_of_words=3)
        with pytest.raises(IndexError):
            wa[10] = b"\x00\x00\x00\x01"

    def test_iteration_count(self):
        wa = WordArray(file=None, bytes_per_word=4, number_of_words=5)
        items = list(wa)
        assert len(items) == 5

    def test_8_byte_words(self):
        wa = WordArray(file=None, bytes_per_word=8, number_of_words=3)
        wa[0] = int8_to_str(42)
        assert wa[0] == int8_to_str(42)

    def test_2_byte_words(self):
        wa = WordArray(file=None, bytes_per_word=2, number_of_words=4)
        wa[0] = b"\x00\xff"
        assert wa[0] == b"\x00\xff"

    def test_generate_static(self):
        """WordArray.generate initializes a file with zero-filled words."""
        buf = io.BytesIO()
        for _ in WordArray.generate(buf, bytes_per_word=4, number_of_words=3, init_byte=b"\x00"):
            pass
        buf.seek(0)
        # Read the 24-byte header
        header = buf.read(24)
        total_bytes = str_to_int8(header[0:8])
        bpw = str_to_int8(header[8:16])
        now = str_to_int8(header[16:24])
        assert total_bytes == 16 + 4 * 3
        assert bpw == 4
        assert now == 3
        # Read data — should be zeros
        data = buf.read()
        assert data == b"\x00" * 12

    def test_reuse_existing_file(self):
        """WordArray can be re-opened from an existing file position."""
        buf = io.BytesIO()
        wa1 = WordArray(file=buf, bytes_per_word=4, number_of_words=3)
        wa1[0] = b"\x00\x00\x00\x2a"
        buf.seek(0)
        wa2 = WordArray(file=buf)
        assert wa2[0] == b"\x00\x00\x00\x2a"


# ── IntArray extended ──


class TestIntArrayExtended:
    """Extended IntArray tests covering blank values, defaults, and compact storage."""

    def test_get_blank_value(self):
        """Unset entries return blank value via get_blank_value()."""
        ia = IntArray(file=None, number_of_ints=3)
        blank = ia.get_blank_value()
        # Blank is all 0xff bytes, which for an 8-byte word is max uint64
        assert blank == (1 << 64) - 1

    def test_get_default_unset(self):
        """get() returns default for unset entries."""
        ia = IntArray(file=None, number_of_ints=3)
        assert ia.get(0) is None
        assert ia.get(0, -1) == -1

    def test_get_default_out_of_range(self):
        """get() returns default for out-of-range index."""
        ia = IntArray(file=None, number_of_ints=3)
        assert ia.get(10) is None
        assert ia.get(10, -99) == -99

    def test_set_and_get_large_value(self):
        ia = IntArray(file=None, number_of_ints=3)
        ia[0] = 2**50
        assert ia[0] == 2**50

    def test_iteration_includes_blanks(self):
        """__iter__ includes blank entries."""
        ia = IntArray(file=None, number_of_ints=3)
        ia[0] = 42
        items = list(ia)
        assert len(items) == 3
        assert items[0] == 42
        # Blank value for 8-byte words
        assert items[1] == (1 << 64) - 1

    def test_iteritems_excludes_blanks(self):
        """iteritems only yields non-blank entries."""
        ia = IntArray(file=None, number_of_ints=3)
        ia[0] = 10
        ia[2] = 30
        items = list(ia.iteritems())
        assert len(items) == 2
        assert items[0] == (0, 10)
        assert items[1] == (2, 30)

    def test_items_alias(self):
        """items is an alias for iteritems."""
        ia = IntArray(file=None, number_of_ints=3)
        ia[0] = 5
        items = list(ia.items())
        assert len(items) == 1
        assert items[0] == (0, 5)

    def test_setitem_value_too_large_raises(self):
        """Setting a value that exceeds uint64 range raises struct.error."""
        ia = IntArray(file=None, number_of_ints=3)
        with pytest.raises(struct.error):
            ia[0] = (1 << 64)  # One more than max uint64

    def test_compact_storage_with_maximum_int(self):
        """IntArray with maximum_int uses fewer bytes per word."""
        ia = IntArray(file=None, number_of_ints=5, maximum_int=255)
        assert len(ia) == 5
        # Should use fewer than 8 bytes per word
        assert ia.word_array.get_bytes_per_word() < 8
        ia[0] = 100
        assert ia[0] == 100

    def test_compact_storage_value_exceeds_max_raises(self):
        """Setting a value too large for the compact word size raises ValueError.

        With maximum_int=0, bytes_per_word=1 and pad is 7 zero bytes.
        A value of 256 has int8_to_str = b'\\x00'*6 + b'\\x01\\x00',
        which doesn't start with 7 zero bytes, triggering ValueError.
        """
        ia = IntArray(file=None, number_of_ints=5, maximum_int=0)
        with pytest.raises(ValueError):
            ia[0] = 256

    def test_compact_storage_iteritems(self):
        ia = IntArray(file=None, number_of_ints=5, maximum_int=1000)
        ia[0] = 50
        ia[2] = 200
        items = list(ia.iteritems())
        assert len(items) == 2

    def test_compact_storage_get_default(self):
        ia = IntArray(file=None, number_of_ints=5, maximum_int=255)
        assert ia.get(0) is None
        assert ia.get(0, -1) == -1

    def test_reuse_existing_file(self):
        """IntArray can be re-opened from an existing file."""
        buf = io.BytesIO()
        ia1 = IntArray(file=buf, number_of_ints=3)
        ia1[0] = 42
        buf.seek(0)
        ia2 = IntArray(file=buf)
        assert ia2[0] == 42


# ── IntSet extended ──


class TestIntSetExtended:
    """Extended IntSet tests covering auto-expansion and boundary behavior."""

    def test_add_triggers_expansion(self):
        """Adding a value beyond current size auto-expands the bit array."""
        s = IntSet(size=10)  # Only holds 0..9 initially
        s.add(50)
        assert 50 in s

    def test_contains_beyond_size_returns_false(self):
        """Values beyond the bit array size are not in the set."""
        s = IntSet(size=10)
        assert 100 not in s

    def test_discard_within_bounds(self):
        """Discard clears a bit that is within the current size."""
        s = IntSet(size=20)
        s.add(5)
        assert 5 in s
        s.discard(5)
        assert 5 not in s

    def test_discard_beyond_bounds_is_noop(self):
        """Discard on a value beyond the bit array size is a no-op."""
        s = IntSet(size=10)
        s.discard(100)  # Should not raise
        assert 100 not in s

    def test_with_explicit_file(self):
        buf = io.BytesIO()
        s = IntSet(size=100, file=buf)
        s.add(50)
        assert 50 in s

    def test_multiple_operations(self):
        s = IntSet(size=20)
        s.add(0)
        s.add(5)
        s.add(19)
        assert 0 in s
        assert 5 in s
        assert 19 in s
        assert 10 not in s
        s.discard(5)
        assert 5 not in s
        # Re-adding is fine
        s.add(5)
        assert 5 in s

    def test_default_size(self):
        """IntSet default size is 2^10 - 1 = 1023."""
        s = IntSet()
        s.add(1023)
        assert 1023 in s
